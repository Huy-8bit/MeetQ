from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import livekit.rtc as rtc

logger = logging.getLogger(__name__)


_FRAME_MS = 20
_CHANNELS = 1
_BYTES_PER_SAMPLE = 2


@dataclass
class _RelayTrackState:
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
    ) -> None:
        self.room = room
        self.brse_participant_id = brse_participant_id
        self.brse_livekit_identity = brse_livekit_identity
        self.speaker_id = speaker_id
        self.src_lang = src_lang
        self.target_lang = target_lang
        self.output_sample_rate = output_sample_rate
        self._frame_bytes = int(output_sample_rate * _FRAME_MS / 1000) * _BYTES_PER_SAMPLE
        self._closed = False
        self._on_track_failure = on_track_failure
        self._state: Optional[_RelayTrackState] = None

    def audio_track_name(self) -> Optional[str]:
        state = self._state
        if state is None or not state.active or not state.track_sid:
            return None
        return state.track_name

    def track_descriptor(self) -> Dict[str, Any]:
        state = self._state
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
        }

    async def ensure_track(self) -> None:
        if self._closed:
            return

        current = self._state
        if current is not None and current.active and current.track_sid:
            return

        if current is not None:
            self._state = None
            await self._release_state(current)

        state = _RelayTrackState(
            source=rtc.AudioSource(self.output_sample_rate, _CHANNELS, queue_size_ms=1500),
            track_name=self._build_track_name(),
        )
        self._state = state

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
            "BRSE relay track ready speaker=%s route=%s->%s sid=%s",
            self.speaker_id,
            self.src_lang,
            self.target_lang,
            publication.sid,
        )

    async def capture_base64_audio(self, encoded_chunk: str) -> bool:
        return await self.capture_pcm(base64.b64decode(encoded_chunk))

    async def capture_pcm(self, pcm_bytes: bytes) -> bool:
        state = self._state
        if state is None:
            await self.ensure_track()
            state = self._state
        if state is None or not state.active:
            return False

        state.buffer.extend(pcm_bytes)
        return await self._publish_buffered_frames(flush=False)

    async def flush(self) -> bool:
        return await self._publish_buffered_frames(flush=True)

    def clear_queue(self) -> None:
        state = self._state
        if state is None:
            return
        state.buffer.clear()
        try:
            state.source.clear_queue()
        except Exception:
            logger.exception(
                "Failed to clear BRSE relay audio queue for speaker=%s",
                self.speaker_id,
            )

    async def shutdown(self) -> None:
        self._closed = True
        state = self._state
        self._state = None
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

        while len(state.buffer) >= self._frame_bytes:
            frame_bytes = bytes(state.buffer[: self._frame_bytes])
            del state.buffer[: self._frame_bytes]
            if not await self._capture_frame(state, frame_bytes):
                return False

        if flush and state.buffer:
            padded = bytes(state.buffer) + (b"\x00" * (self._frame_bytes - len(state.buffer)))
            state.buffer.clear()
            if not await self._capture_frame(state, padded):
                return False

        return True

    async def _capture_frame(self, state: _RelayTrackState, frame_bytes: bytes) -> bool:
        if self._state is not state or not state.active or not state.track_sid or not self._room_is_connected():
            return False

        frame = rtc.AudioFrame(
            data=frame_bytes,
            sample_rate=self.output_sample_rate,
            num_channels=_CHANNELS,
            samples_per_channel=self._frame_bytes // _BYTES_PER_SAMPLE,
        )
        try:
            await state.source.capture_frame(frame)
            return True
        except Exception as exc:
            logger.exception(
                "Failed to capture BRSE relay frame for speaker=%s route=%s->%s",
                self.speaker_id,
                self.src_lang,
                self.target_lang,
            )
            await self._reset_track(f"BRSE relay audio track became unusable: {exc}")
            return False

    async def _reset_track(self, message: str) -> None:
        logger.warning(
            "Resetting BRSE relay track speaker=%s route=%s->%s",
            self.speaker_id,
            self.src_lang,
            self.target_lang,
        )
        state = self._state
        self._state = None
        if state is not None:
            await self._release_state(state)
        if self._closed:
            return
        await self.ensure_track()
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

    def _room_is_connected(self) -> bool:
        return self.room.connection_state == rtc.ConnectionState.CONN_CONNECTED
