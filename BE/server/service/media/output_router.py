from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import livekit.rtc as rtc

logger = logging.getLogger(__name__)


_FRAME_MS = 20
_CHANNELS = 1
_BYTES_PER_SAMPLE = 2
_SOURCE_QUEUE_MS = 6000
_PUBLIC_AUDIO_HOLD_MAX_MS = 3000


@dataclass
class _RelayTrackState:
    generation: int
    source: rtc.AudioSource
    track_name: str
    track_sid: Optional[str] = None
    buffer: bytearray = field(default_factory=bytearray)
    active: bool = True


class OutputRouter:
    def __init__(
        self,
        room: rtc.Room,
        *,
        brse_participant_id: str,
        brse_livekit_identity: str,
        speaker_id: str,
        src_lang: str,
        target_lang: str,
        output_sample_rate: int = 24000,
        on_track_failure: Optional[Callable[[str, str], None]] = None,
        output_enabled: bool = True,
    ) -> None:
        self.room = room
        self.brse_participant_id = brse_participant_id
        self.brse_livekit_identity = brse_livekit_identity
        self.speaker_id = speaker_id
        self.src_lang = src_lang
        self.target_lang = target_lang
        self.output_sample_rate = output_sample_rate
        self.output_enabled = output_enabled
        self._frame_bytes = int(output_sample_rate * _FRAME_MS / 1000) * _BYTES_PER_SAMPLE
        self._closed = False
        self._on_track_failure = on_track_failure
        self._state: Optional[_RelayTrackState] = None
        self._generation = 0
        self._op_lock = asyncio.Lock()
        self._pending_clear = False
        self._captured_chunks = 0
        self._captured_frames = 0
        self._flush_count = 0
        self._clear_count = 0
        self._reset_count = 0
        self._decode_errors = 0
        self._first_frame_at: Optional[float] = None
        self._suppression_logged = False
        self._public_audio_enabled = True
        self._public_audio_rejected = False
        self._public_audio_gate_reason: Optional[str] = None
        self._public_audio_hold_overflow_logged = False
        self._public_audio_hold_max_bytes = (
            int(output_sample_rate * _PUBLIC_AUDIO_HOLD_MAX_MS / 1000)
            * _BYTES_PER_SAMPLE
        )

    def audio_track_name(self) -> Optional[str]:
        state = self._state
        if state is None or not state.active or not state.track_sid:
            return None
        return state.track_name

    def track_descriptor(self) -> Dict[str, Any]:
        state = self._state
        if not self.output_enabled:
            return {
                "model": "brse_silent_listener",
                "mode": "disabled",
                "canonical": False,
                "track_available": False,
                "track_name": None,
                "track_sid": None,
                "participant_id": self.brse_participant_id,
                "participant_kind": "virtual_brse",
                "livekit_identity": self.brse_livekit_identity,
                "speaker_id": self.speaker_id,
                "source_language": self.src_lang,
                "target_language": self.target_lang,
                "output_suppressed": True,
                "suppressed_reason": "brse_silent_summary_mode",
                "stats": self.stats_snapshot(),
            }
        return {
            "model": "brse_participant_audio",
            "mode": "virtual_participant_track",
            "canonical": True,
            "track_available": bool(state and state.track_sid),
            "track_name": state.track_name if state is not None else self._build_track_name(),
            "track_sid": state.track_sid if state is not None else None,
            "participant_id": self.brse_participant_id,
            "participant_kind": "virtual_brse",
            "livekit_identity": self.brse_livekit_identity,
            "speaker_id": self.speaker_id,
            "source_language": self.src_lang,
            "target_language": self.target_lang,
            "stats": self.stats_snapshot(),
        }

    def stats_snapshot(self) -> Dict[str, Any]:
        state = self._state
        return {
            "generation": self._generation,
            "active": bool(state and state.active),
            "buffer_bytes": len(state.buffer) if state is not None else 0,
            "captured_chunks": self._captured_chunks,
            "captured_frames": self._captured_frames,
            "flush_count": self._flush_count,
            "clear_count": self._clear_count,
            "reset_count": self._reset_count,
            "decode_errors": self._decode_errors,
            "output_enabled": self.output_enabled,
            "output_suppressed": not self.output_enabled,
            "public_audio_enabled": self._public_audio_enabled,
            "public_audio_rejected": self._public_audio_rejected,
            "public_audio_gate_reason": self._public_audio_gate_reason,
        }

    async def ensure_track(self) -> None:
        async with self._op_lock:
            await self._ensure_track_locked()

    async def _ensure_track_locked(self) -> None:
        if self._closed:
            return
        if not self.output_enabled:
            self._log_output_suppressed_once("track_publish")
            return

        current = self._state
        if current is not None and current.active and current.track_sid:
            return

        if current is not None:
            self._state = None
            await self._release_state(current)

        state = _RelayTrackState(
            generation=self._next_generation(),
            source=rtc.AudioSource(self.output_sample_rate, _CHANNELS, queue_size_ms=_SOURCE_QUEUE_MS),
            track_name=self._build_track_name(),
        )
        self._state = state
        self._pending_clear = False
        self._first_frame_at = None

        logger.info(
            "BRSE relay source created speaker=%s route=%s->%s generation=%d queue_ms=%d",
            self.speaker_id,
            self.src_lang,
            self.target_lang,
            state.generation,
            _SOURCE_QUEUE_MS,
        )

        if not self._room_is_connected():
            self._notify_track_failure(
                "LiveKit room is not connected; BRSE relay track cannot be published yet.",
            )
            return

        track = rtc.LocalAudioTrack.create_audio_track(state.track_name, state.source)
        try:
            publication = await self.room.local_participant.publish_track(track)
        except Exception as exc:
            logger.exception(
                "Failed to publish BRSE relay track for speaker=%s route=%s->%s",
                self.speaker_id,
                self.src_lang,
                self.target_lang,
            )
            self._state = None
            state.active = False
            self._notify_track_failure(f"Failed to publish BRSE relay audio track: {exc}")
            return

        if self._state is not state or not state.active:
            try:
                await self.room.local_participant.unpublish_track(publication.sid)
            except Exception:
                logger.exception("Failed to unpublish stale BRSE relay track for speaker=%s", self.speaker_id)
            return

        state.track_sid = publication.sid
        logger.info(
            "BRSE relay track ready speaker=%s route=%s->%s sid=%s generation=%d",
            self.speaker_id,
            self.src_lang,
            self.target_lang,
            publication.sid,
            state.generation,
        )

    async def capture_base64_audio(self, encoded_chunk: str) -> bool:
        try:
            pcm = base64.b64decode(encoded_chunk, validate=True)
        except (binascii.Error, ValueError) as exc:
            self._decode_errors += 1
            logger.warning(
                "Dropping invalid BRSE relay audio chunk speaker=%s route=%s->%s decode_errors=%d error=%s",
                self.speaker_id,
                self.src_lang,
                self.target_lang,
                self._decode_errors,
                exc,
            )
            return False
        return await self.capture_pcm(pcm)

    async def capture_pcm(self, pcm_bytes: bytes) -> bool:
        if not self.output_enabled:
            self._log_output_suppressed_once("audio_capture")
            return True
        async with self._op_lock:
            if self._public_audio_rejected:
                return True
            state = self._state
            if state is None:
                await self._ensure_track_locked()
                state = self._state
            if state is None or not state.active:
                return False

            self._captured_chunks += 1
            state.buffer.extend(pcm_bytes)
            if not self._public_audio_enabled:
                self._trim_public_audio_hold_buffer(state)
                return True
            return await self._publish_buffered_frames(flush=False)

    async def flush(self) -> bool:
        if not self.output_enabled:
            self._log_output_suppressed_once("audio_flush")
            return True
        async with self._op_lock:
            self._flush_count += 1
            if self._public_audio_rejected or not self._public_audio_enabled:
                return True
            return await self._publish_buffered_frames(flush=True)

    def clear_queue(self) -> None:
        if not self.output_enabled:
            return
        state = self._state
        if state is None:
            return
        self._clear_count += 1
        buffer_bytes = len(state.buffer)
        state.buffer.clear()
        self._pending_clear = True
        logger.debug(
            "Clearing BRSE relay audio queue speaker=%s route=%s->%s generation=%d "
            "buffer_bytes=%d clear_count=%d",
            self.speaker_id,
            self.src_lang,
            self.target_lang,
            state.generation,
            buffer_bytes,
            self._clear_count,
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                state.source.clear_queue()
                self._pending_clear = False
            except Exception:
                logger.exception(
                    "Failed to clear BRSE relay audio queue for speaker=%s",
                    self.speaker_id,
                )
            return

        loop.create_task(self._apply_pending_clear())

    def hold_public_output(self, *, reason: str) -> None:
        if self._public_audio_rejected:
            return
        if not self._public_audio_enabled and self._public_audio_gate_reason == reason:
            return
        self._public_audio_enabled = False
        self._public_audio_gate_reason = reason
        logger.info(
            "BRSE relay public audio held speaker=%s route=%s->%s reason=%s",
            self.speaker_id,
            self.src_lang,
            self.target_lang,
            reason,
        )

    async def release_public_output(self, *, reason: str) -> None:
        if not self.output_enabled:
            return
        async with self._op_lock:
            if self._public_audio_rejected:
                return
            if self._public_audio_enabled:
                return
            self._public_audio_enabled = True
            self._public_audio_gate_reason = None
            self._public_audio_hold_overflow_logged = False
            logger.info(
                "BRSE relay public audio released speaker=%s route=%s->%s reason=%s",
                self.speaker_id,
                self.src_lang,
                self.target_lang,
                reason,
            )
            await self._publish_buffered_frames(flush=False)

    async def reject_public_output(self, *, reason: str) -> None:
        async with self._op_lock:
            self._public_audio_rejected = True
            self._public_audio_enabled = False
            self._public_audio_gate_reason = reason
            state = self._state
            if state is not None:
                state.buffer.clear()
            self._pending_clear = True
            logger.info(
                "BRSE relay public audio rejected speaker=%s route=%s->%s reason=%s",
                self.speaker_id,
                self.src_lang,
                self.target_lang,
                reason,
            )
        await self._apply_pending_clear()

    def reset_public_output_gate(self) -> None:
        self._public_audio_enabled = True
        self._public_audio_rejected = False
        self._public_audio_gate_reason = None
        self._public_audio_hold_overflow_logged = False

    async def _apply_pending_clear(self) -> None:
        async with self._op_lock:
            state = self._state
            if state is None or not self._pending_clear:
                return
            try:
                state.source.clear_queue()
                self._pending_clear = False
            except Exception:
                logger.exception(
                    "Failed to clear BRSE relay audio queue for speaker=%s",
                    self.speaker_id,
                )

    async def shutdown(self) -> None:
        async with self._op_lock:
            self._closed = True
            state = self._state
            self._state = None
            self._pending_clear = False
            if state is None:
                return
            await self._release_state(state)

    async def _publish_buffered_frames(self, *, flush: bool) -> bool:
        state = self._state
        if (
            state is None
            or not state.active
            or not state.track_sid
            or not self._room_is_connected()
        ):
            return False if flush else True

        if self._pending_clear:
            try:
                state.source.clear_queue()
                self._pending_clear = False
            except Exception:
                logger.exception(
                    "Failed to clear BRSE relay audio queue for speaker=%s",
                    self.speaker_id,
                )

        while len(state.buffer) >= self._frame_bytes:
            frame_bytes = bytes(state.buffer[: self._frame_bytes])
            del state.buffer[: self._frame_bytes]
            ok, reset_message = await self._capture_frame(state, frame_bytes)
            if not ok:
                await self._reset_track_locked(reset_message)
                return False

        if flush and state.buffer:
            padded = bytes(state.buffer) + (b"\x00" * (self._frame_bytes - len(state.buffer)))
            state.buffer.clear()
            ok, reset_message = await self._capture_frame(state, padded)
            if not ok:
                await self._reset_track_locked(reset_message)
                return False

        return True

    def _trim_public_audio_hold_buffer(self, state: _RelayTrackState) -> None:
        max_bytes = self._public_audio_hold_max_bytes
        if max_bytes <= 0 or len(state.buffer) <= max_bytes:
            return
        overflow = len(state.buffer) - max_bytes
        del state.buffer[:overflow]
        if self._public_audio_hold_overflow_logged:
            return
        self._public_audio_hold_overflow_logged = True
        logger.warning(
            "BRSE relay held audio buffer trimmed speaker=%s route=%s->%s "
            "overflow_bytes=%d reason=%s",
            self.speaker_id,
            self.src_lang,
            self.target_lang,
            overflow,
            self._public_audio_gate_reason,
        )

    async def _capture_frame(self, state: _RelayTrackState, frame_bytes: bytes) -> tuple[bool, str]:
        if self._state is not state or not state.active or not state.track_sid or not self._room_is_connected():
            return False, "relay output state is stale or disconnected"

        frame = rtc.AudioFrame(
            data=frame_bytes,
            sample_rate=self.output_sample_rate,
            num_channels=_CHANNELS,
            samples_per_channel=self._frame_bytes // _BYTES_PER_SAMPLE,
        )
        try:
            await state.source.capture_frame(frame)
            self._captured_frames += 1
            if self._first_frame_at is None:
                self._first_frame_at = time.monotonic()
                logger.info(
                    "BRSE first relay audio frame speaker=%s route=%s->%s generation=%d",
                    self.speaker_id,
                    self.src_lang,
                    self.target_lang,
                    state.generation,
                )
            return True, ""
        except Exception as exc:
            logger.exception(
                "Failed to capture BRSE relay frame for speaker=%s route=%s->%s generation=%d",
                self.speaker_id,
                self.src_lang,
                self.target_lang,
                state.generation,
            )
            state.active = False
            return False, f"BRSE relay audio track became unusable: {exc}"

    async def _reset_track_locked(self, message: str) -> None:
        self._reset_count += 1
        logger.warning(
            "Resetting BRSE relay track speaker=%s route=%s->%s reset_count=%d reason=%s",
            self.speaker_id,
            self.src_lang,
            self.target_lang,
            self._reset_count,
            message,
        )
        state = self._state
        self._state = None
        self._pending_clear = False
        if state is not None:
            await self._release_state(state)
        if self._closed:
            return
        await self._ensure_track_locked()
        self._notify_track_failure(message)

    async def _release_state(self, state: _RelayTrackState) -> None:
        state.active = False
        state.buffer.clear()
        try:
            state.source.clear_queue()
        except Exception:
            logger.exception("Failed to clear BRSE relay audio queue during release")

        if state.track_sid and self._room_is_connected():
            try:
                await self.room.local_participant.unpublish_track(state.track_sid)
            except Exception:
                logger.exception(
                    "Failed to unpublish BRSE relay track for speaker=%s",
                    self.speaker_id,
                )

    def _notify_track_failure(self, message: str) -> None:
        logger.warning(
            "BRSE relay track failure for speaker=%s target=%s: %s",
            self.speaker_id,
            self.target_lang,
            message,
        )
        if self._on_track_failure is not None:
            self._on_track_failure(self.target_lang, message)

    def _build_track_name(self) -> str:
        return f"brse::{self.speaker_id}::{self.src_lang}::{self.target_lang}"

    def _next_generation(self) -> int:
        self._generation += 1
        return self._generation

    def _room_is_connected(self) -> bool:
        return self.room.connection_state == rtc.ConnectionState.CONN_CONNECTED

    def _log_output_suppressed_once(self, operation: str) -> None:
        if self._suppression_logged:
            return
        self._suppression_logged = True
        logger.info(
            "BRSE relay output suppressed by silent summary mode speaker=%s route=%s->%s operation=%s",
            self.speaker_id,
            self.src_lang,
            self.target_lang,
            operation,
        )
