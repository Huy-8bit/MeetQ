from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Set

import livekit.rtc as rtc

logger = logging.getLogger(__name__)


_FRAME_MS = 20
_CHANNELS = 1
_BYTES_PER_SAMPLE = 2


@dataclass
class _ListenerTrackState:
    listener_id: str
    target_lang: str
    source: rtc.AudioSource
    track_name: str
    track_sid: Optional[str] = None
    buffer: bytearray = field(default_factory=bytearray)
    active: bool = True


class OutputRouter:
    def __init__(
        self,
        room: rtc.Room,
        speaker_id: str,
        src_lang: str,
        *,
        output_sample_rate: int = 24000,
        on_track_failure: Optional[Callable[[str, str, str], None]] = None,
    ) -> None:
        self.room = room
        self.speaker_id = speaker_id
        self.src_lang = src_lang
        self.output_sample_rate = output_sample_rate
        self._frame_bytes = int(output_sample_rate * _FRAME_MS / 1000) * _BYTES_PER_SAMPLE
        self._states: Dict[str, _ListenerTrackState] = {}
        self._closed = False
        self._on_track_failure = on_track_failure

    @property
    def listener_languages(self) -> Dict[str, str]:
        return {
            listener_id: state.target_lang
            for listener_id, state in self._states.items()
            if state.active
        }

    def audio_track_name(self, listener_id: str) -> Optional[str]:
        state = self._states.get(listener_id)
        if state is None or not state.active or not state.track_sid:
            return None
        return state.track_name

    def listener_ids_for_language(self, tgt_lang: str) -> Set[str]:
        return {
            listener_id
            for listener_id, state in self._states.items()
            if state.active and state.target_lang == tgt_lang
        }

    def track_descriptor(self, listener_id: str) -> Optional[Dict[str, Any]]:
        state = self._states.get(listener_id)
        if state is None or not state.active:
            return None
        return {
            "listener_id": listener_id,
            "track_name": state.track_name,
            "track_sid": state.track_sid,
            "source_language": self.src_lang,
            "target_language": state.target_lang,
            "track_available": state.track_sid is not None,
            "authoritative": True,
            "mode": "interpreter_track",
        }

    def track_descriptors_for_language(self, tgt_lang: str) -> list[Dict[str, Any]]:
        descriptors: list[Dict[str, Any]] = []
        for listener_id in sorted(self.listener_ids_for_language(tgt_lang)):
            descriptor = self.track_descriptor(listener_id)
            if descriptor is not None:
                descriptors.append(descriptor)
        return descriptors

    async def ensure_listener(self, listener_id: str, tgt_lang: str) -> None:
        if self._closed:
            return

        current = self._states.get(listener_id)
        if (
            current is not None
            and current.active
            and current.target_lang == tgt_lang
            and current.track_sid
        ):
            return

        if current is not None:
            await self.remove_listener(listener_id)

        state = _ListenerTrackState(
            listener_id=listener_id,
            target_lang=tgt_lang,
            source=rtc.AudioSource(self.output_sample_rate, _CHANNELS, queue_size_ms=1500),
            track_name=self._build_track_name(listener_id, tgt_lang),
        )
        self._states[listener_id] = state

        if not self._room_is_connected():
            self._notify_track_failure(
                listener_id,
                tgt_lang,
                "LiveKit room is not connected; interpreter track cannot be published yet.",
            )
            return

        track = rtc.LocalAudioTrack.create_audio_track(state.track_name, state.source)
        try:
            publication = await self.room.local_participant.publish_track(track)
        except Exception as exc:
            logger.exception(
                "Failed to publish interpreter track for %s -> %s",
                self.speaker_id,
                listener_id,
            )
            if self._states.get(listener_id) is state:
                self._states.pop(listener_id, None)
            state.active = False
            self._notify_track_failure(
                listener_id,
                tgt_lang,
                f"Failed to publish interpreter audio track: {exc}",
            )
            return

        if self._states.get(listener_id) is not state or not state.active:
            try:
                await self.room.local_participant.unpublish_track(publication.sid)
            except Exception:
                logger.exception(
                    "Failed to unpublish stale interpreter track for %s -> %s",
                    self.speaker_id,
                    listener_id,
                )
            return

        state.track_sid = publication.sid
        logger.info(
            "Interpreter track ready speaker=%s listener=%s route=%s->%s sid=%s",
            self.speaker_id,
            listener_id,
            self.src_lang,
            tgt_lang,
            publication.sid,
        )
        self._update_permissions()

    async def remove_listener(self, listener_id: str) -> None:
        state = self._states.pop(listener_id, None)
        if state is None:
            return

        state.active = False
        state.buffer.clear()
        try:
            state.source.clear_queue()
        except Exception:
            logger.exception(
                "Failed to clear interpreter audio queue for %s -> %s",
                self.speaker_id,
                listener_id,
            )

        if state.track_sid and self._room_is_connected():
            try:
                await self.room.local_participant.unpublish_track(state.track_sid)
            except Exception:
                logger.exception(
                    "Failed to unpublish interpreter track for %s -> %s",
                    self.speaker_id,
                    listener_id,
                )

        self._update_permissions()

    async def capture_base64_audio(self, tgt_lang: str, encoded_chunk: str) -> bool:
        return await self.capture_pcm(tgt_lang, base64.b64decode(encoded_chunk))

    async def capture_pcm(self, tgt_lang: str, pcm_bytes: bytes) -> bool:
        listener_ids = self.listener_ids_for_language(tgt_lang)
        if not listener_ids:
            return True

        ok = True
        for listener_id in listener_ids:
            state = self._states.get(listener_id)
            if state is None or not state.active:
                continue
            state.buffer.extend(pcm_bytes)
            ok = await self._publish_buffered_frames(listener_id, flush=False) and ok
        return ok

    async def flush(self, tgt_lang: Optional[str] = None) -> bool:
        listener_ids = (
            self.listener_ids_for_language(tgt_lang)
            if tgt_lang is not None
            else set(self._states.keys())
        )
        ok = True
        for listener_id in listener_ids:
            ok = await self._publish_buffered_frames(listener_id, flush=True) and ok
        return ok

    def clear_queues(self, listener_ids: Optional[Set[str]] = None) -> None:
        target_ids = listener_ids or set(self._states.keys())
        for listener_id in target_ids:
            state = self._states.get(listener_id)
            if state is None:
                continue
            state.buffer.clear()
            try:
                state.source.clear_queue()
            except Exception:
                logger.exception(
                    "Failed to clear interpreter audio queue for %s -> %s",
                    self.speaker_id,
                    listener_id,
                )

    async def shutdown(self) -> None:
        self._closed = True
        for listener_id in list(self._states.keys()):
            await self.remove_listener(listener_id)

    def _update_permissions(self) -> None:
        if not self._room_is_connected():
            return

        permissions = []
        for state in self._states.values():
            if not state.active or not state.track_sid:
                continue
            permissions.append(
                rtc.ParticipantTrackPermission(
                    participant_identity=state.listener_id,
                    allow_all=False,
                    allowed_track_sids=[state.track_sid],
                )
            )

        try:
            self.room.local_participant.set_track_subscription_permissions(
                allow_all_participants=False,
                participant_permissions=permissions,
            )
        except Exception:
            logger.exception("Failed to update interpreter track permissions")

    def _build_track_name(self, listener_id: str, tgt_lang: str) -> str:
        return f"interp::{self.speaker_id}::{listener_id}::{self.src_lang}::{tgt_lang}"

    async def _publish_buffered_frames(self, listener_id: str, *, flush: bool) -> bool:
        state = self._states.get(listener_id)
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

    async def _capture_frame(self, state: _ListenerTrackState, frame_bytes: bytes) -> bool:
        if (
            self._states.get(state.listener_id) is not state
            or not state.active
            or not state.track_sid
            or not self._room_is_connected()
        ):
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
                "Failed to capture interpreter frame for %s -> %s",
                self.speaker_id,
                state.listener_id,
            )
            if self._states.get(state.listener_id) is state and state.active:
                await self._reset_listener(state.listener_id, state.target_lang)
            self._notify_track_failure(
                state.listener_id,
                state.target_lang,
                f"Interpreter audio track became unusable: {exc}",
            )
            return False

    async def _reset_listener(self, listener_id: str, tgt_lang: str) -> None:
        logger.warning(
            "Resetting interpreter track speaker=%s listener=%s route=%s->%s",
            self.speaker_id,
            listener_id,
            self.src_lang,
            tgt_lang,
        )
        await self.remove_listener(listener_id)
        if self._closed:
            return
        await self.ensure_listener(listener_id, tgt_lang)

    def _notify_track_failure(self, listener_id: str, tgt_lang: str, message: str) -> None:
        logger.warning(
            "Interpreter track failure for speaker=%s listener=%s target=%s: %s",
            self.speaker_id,
            listener_id,
            tgt_lang,
            message,
        )
        if self._on_track_failure is not None:
            self._on_track_failure(listener_id, tgt_lang, message)

    def _room_is_connected(self) -> bool:
        return self.room.connection_state == rtc.ConnectionState.CONN_CONNECTED
