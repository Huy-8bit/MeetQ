from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import logging
import time
from typing import Any, AsyncIterable, Callable, Deque, Optional, Set

import livekit.rtc as rtc
import numpy as np

from server.service.livekit_lines.analysis import (
    LineClock,
    LineVad,
    pcm16_band_levels_db,
    pcm16_level_db,
)
from server.service.livekit_lines.config import LineIsolationConfig
from server.service.livekit_lines.crosstalk import CrosstalkArbiter, CrosstalkVerdict

logger = logging.getLogger(__name__)


@dataclass
class _PendingFrame:
    frame: Any
    pcm: bytes
    ts: float


class SpeakerLineStream:
    """Consumer view of a SpeakerLine.

    Drop-in for `rtc.AudioStream` as consumed by `LiveKitAudioInput`: it is an
    async iterator of `rtc.AudioFrameEvent` and exposes `aclose()`. It can be
    iterated again after a consumer task is cancelled, which is how the room
    runtime reuses a stream across route reconfiguration. Closing a view never
    closes the underlying LiveKit track; the line hub owns that lifecycle.
    """

    def __init__(self, line: "SpeakerLine", maxsize: int) -> None:
        self.line = line
        self._queue: asyncio.Queue[Optional[rtc.AudioFrameEvent]] = asyncio.Queue()
        self._maxsize = max(1, maxsize)
        self._attached = True
        self._closed = False

    @property
    def participant_identity(self) -> str:
        return self.line.line_id

    def __aiter__(self) -> "SpeakerLineStream":
        return self

    async def __anext__(self) -> rtc.AudioFrameEvent:
        if self._closed and self._queue.empty():
            raise StopAsyncIteration
        self._attached = True
        try:
            item = await self._queue.get()
        except asyncio.CancelledError:
            # Consumer went away (e.g. LiveKitAudioInput.stop); stop buffering
            # until somebody iterates again so stale audio is not replayed.
            self._attached = False
            self._drain()
            raise
        if item is None:
            self._closed = True
            raise StopAsyncIteration
        return item

    async def aclose(self) -> None:
        self._end()
        self.line.detach(self)

    def _push(self, event: rtc.AudioFrameEvent) -> None:
        if self._closed or not self._attached:
            return
        while self._queue.qsize() >= self._maxsize:
            self._queue.get_nowait()
        self._queue.put_nowait(event)

    def _end(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put_nowait(None)

    def _drain(self) -> None:
        while not self._queue.empty():
            if self._queue.get_nowait() is None:
                self._closed = True


class SpeakerLine:
    """One participant's microphone audio, isolated from the other lines.

    Pumps the LiveKit AudioStream for a single remote track, measures level and
    speech per frame, holds frames for a short lookahead, then asks the room's
    CrosstalkArbiter whether the frame is the participant's own voice or bleed
    of another participant. Bleed frames are replaced with silence (timeline is
    preserved so downstream VAD timing stays correct).
    """

    def __init__(
        self,
        line_id: str,
        source: AsyncIterable[Any],
        arbiter: CrosstalkArbiter,
        config: LineIsolationConfig,
        *,
        room_id: str = "",
        clock: Callable[[], float] = time.monotonic,
        on_closed: Optional[Callable[["SpeakerLine"], None]] = None,
    ) -> None:
        self.line_id = line_id
        self.room_id = room_id
        self.source = source
        self.arbiter = arbiter
        self.config = config
        self._clock = clock
        self._on_closed = on_closed
        self._line_clock = LineClock()
        self._vad = LineVad(
            abs_min_db=config.vad_abs_min_db,
            margin_db=config.vad_margin_db,
            onset_frames=config.vad_onset_frames,
            hangover_frames=config.vad_hangover_frames,
        )
        self._pending: Deque[_PendingFrame] = deque()
        self._lookahead_s = max(0, config.lookahead_ms) / 1000.0
        self._release_s = max(0, config.release_ms) / 1000.0
        self._views: Set[SpeakerLineStream] = set()
        self._task: Optional[asyncio.Task[None]] = None
        self._closed = False
        self._isolated = False
        self._isolated_by: Optional[str] = None
        self._clean_since: Optional[float] = None
        self.frames_total = 0
        self.speech_frames_total = 0
        self.isolated_frames_total = 0
        self.isolation_events_total = 0
        self.ingest_failures_total = 0
        self._stats_logged_at = clock()
        self._stats_isolated_at_log = 0
        arbiter.register(line_id)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def isolated(self) -> bool:
        return self._isolated

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._pump())

    def open_stream(self) -> SpeakerLineStream:
        view = SpeakerLineStream(self, self.config.consumer_queue_frames)
        if self._closed:
            view._end()
        else:
            self._views.add(view)
        return view

    def detach(self, view: SpeakerLineStream) -> None:
        self._views.discard(view)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        task = self._task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._close_source()
        self._finish()

    def stats_snapshot(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "frames_total": self.frames_total,
            "speech_frames_total": self.speech_frames_total,
            "isolated_frames_total": self.isolated_frames_total,
            "isolation_events_total": self.isolation_events_total,
            "isolated": self._isolated,
            "isolated_by": self._isolated_by,
            "noise_floor_db": round(self._vad.noise_floor_db, 1),
        }

    async def _pump(self) -> None:
        try:
            async for event in self.source:
                if self._closed:
                    break
                frame = getattr(event, "frame", event)
                try:
                    self.ingest(frame)
                except Exception:
                    # Fail open: isolation must never cost the speaker their audio.
                    self._log_ingest_failure()
                    self._emit(frame, _frame_bytes(frame))
        except Exception:
            logger.exception("Speaker line pump failed room=%s line=%s", self.room_id, self.line_id)
        finally:
            if not self._closed:
                self._closed = True
                await self._close_source()
                self._finish()

    def ingest(self, frame: Any) -> None:
        pcm = _frame_bytes(frame)
        if not pcm:
            return
        duration_s = _frame_duration_s(frame, len(pcm))
        ts = self._line_clock.stamp(self._clock(), duration_s)
        level_db = pcm16_level_db(pcm)
        speech = self._vad.update(level_db)
        self.frames_total += 1
        if speech:
            self.speech_frames_total += 1
        sample_rate = int(getattr(frame, "sample_rate", 0) or 0)
        num_channels = int(getattr(frame, "num_channels", 1) or 1)
        bands_db = pcm16_band_levels_db(pcm, sample_rate, num_channels)
        self.arbiter.observe(self.line_id, ts, level_db, speech, bands_db)

        self._pending.append(_PendingFrame(frame=frame, pcm=pcm, ts=ts))
        while self._pending and ts - self._pending[0].ts >= self._lookahead_s:
            self._release(self._pending.popleft())
        self._maybe_log_stats()

    def _release(self, pending: _PendingFrame) -> None:
        verdict = self.arbiter.decide(
            self.line_id,
            pending.ts,
            held_by=self._isolated_by if self._isolated else None,
        )
        was_isolated = self._isolated
        self._update_isolation(verdict, pending.ts)

        pcm = pending.pcm
        if self._isolated or was_isolated:
            pcm = _gate_pcm(pcm, was_isolated=was_isolated, now_isolated=self._isolated)
        if self._isolated:
            self.isolated_frames_total += 1
        self._emit(pending.frame, pcm)

    def _update_isolation(self, verdict: CrosstalkVerdict, ts: float) -> None:
        if verdict.is_bleed:
            self._clean_since = None
            if not self._isolated:
                self._isolated = True
                self.isolation_events_total += 1
                logger.info(
                    "Speaker line isolated room=%s line=%s bleed_of=%s corr=%.2f gap_db=%.1f",
                    self.room_id,
                    self.line_id,
                    verdict.dominated_by,
                    verdict.correlation,
                    verdict.level_gap_db,
                )
            self._isolated_by = verdict.dominated_by
            return

        if not self._isolated:
            return
        if verdict.own_voice:
            logger.info(
                "Speaker line reopened on own voice room=%s line=%s was_bleed_of=%s",
                self.room_id,
                self.line_id,
                self._isolated_by,
            )
            self._isolated = False
            self._isolated_by = None
            self._clean_since = None
            return
        if self._clean_since is None:
            self._clean_since = ts
        if ts - self._clean_since >= self._release_s:
            logger.debug(
                "Speaker line reopened room=%s line=%s after bleed_of=%s",
                self.room_id,
                self.line_id,
                self._isolated_by,
            )
            self._isolated = False
            self._isolated_by = None
            self._clean_since = None

    def _emit(self, frame: Any, pcm: bytes) -> None:
        if not self._views:
            return
        sample_rate = int(getattr(frame, "sample_rate", 24000) or 24000)
        num_channels = int(getattr(frame, "num_channels", 1) or 1)
        samples_per_channel = len(pcm) // (2 * num_channels)
        event = rtc.AudioFrameEvent(
            frame=rtc.AudioFrame(
                data=pcm,
                sample_rate=sample_rate,
                num_channels=num_channels,
                samples_per_channel=samples_per_channel,
            )
        )
        for view in list(self._views):
            view._push(event)

    def _flush_pending(self) -> None:
        while self._pending:
            self._release(self._pending.popleft())

    def _finish(self) -> None:
        self._flush_pending()
        for view in list(self._views):
            view._end()
        self._views.clear()
        self.arbiter.unregister(self.line_id)
        if self._on_closed is not None:
            self._on_closed(self)

    async def _close_source(self) -> None:
        aclose = getattr(self.source, "aclose", None)
        if not callable(aclose):
            return
        try:
            await aclose()
        except Exception:
            logger.debug("Failed to close LiveKit audio stream for line %s", self.line_id)

    def _log_ingest_failure(self) -> None:
        self.ingest_failures_total += 1
        if self.ingest_failures_total == 1 or self.ingest_failures_total % 500 == 0:
            logger.exception(
                "Speaker line isolation failed; passing audio through room=%s line=%s failures=%d",
                self.room_id,
                self.line_id,
                self.ingest_failures_total,
            )

    def _maybe_log_stats(self) -> None:
        interval = self.config.stats_log_interval_s
        if interval <= 0:
            return
        now = self._clock()
        if now - self._stats_logged_at < interval:
            return
        self._stats_logged_at = now
        isolated_delta = self.isolated_frames_total - self._stats_isolated_at_log
        self._stats_isolated_at_log = self.isolated_frames_total
        if isolated_delta <= 0:
            return
        logger.info(
            "Speaker line stats room=%s line=%s isolated_ms_recent=%d events_total=%d "
            "speech_ms_total=%d noise_floor_db=%.1f",
            self.room_id,
            self.line_id,
            isolated_delta * 20,
            self.isolation_events_total,
            self.speech_frames_total * 20,
            self._vad.noise_floor_db,
        )


def _frame_bytes(frame: Any) -> bytes:
    raw = getattr(frame, "data", frame)
    if isinstance(raw, memoryview):
        return raw.cast("B").tobytes()
    return bytes(raw)


def _frame_duration_s(frame: Any, byte_count: int) -> float:
    sample_rate = int(getattr(frame, "sample_rate", 0) or 0)
    num_channels = int(getattr(frame, "num_channels", 1) or 1)
    if sample_rate <= 0:
        return 0.02
    return byte_count / (2 * num_channels * sample_rate)


def _gate_pcm(pcm: bytes, *, was_isolated: bool, now_isolated: bool) -> bytes:
    if was_isolated and now_isolated:
        return bytes(len(pcm))
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    ramp = np.linspace(0.0, 1.0, num=samples.size, dtype=np.float32)
    if now_isolated:
        ramp = ramp[::-1]
    return (samples * ramp).astype(np.int16).tobytes()
