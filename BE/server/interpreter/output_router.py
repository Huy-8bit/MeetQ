from __future__ import annotations

import base64
import logging
from typing import Dict, Optional, Set

import livekit.rtc as rtc

logger = logging.getLogger(__name__)


_FRAME_MS = 20
_CHANNELS = 1
_BYTES_PER_SAMPLE = 2


class OutputRouter:
    def __init__(
        self,
        room: rtc.Room,
        speaker_id: str,
        src_lang: str,
        *,
        output_sample_rate: int = 24000,
    ) -> None:
        self.room = room
        self.speaker_id = speaker_id
        self.src_lang = src_lang
        self.output_sample_rate = output_sample_rate
        self._frame_bytes = int(output_sample_rate * _FRAME_MS / 1000) * _BYTES_PER_SAMPLE
        self.sources: Dict[str, rtc.AudioSource] = {}
        self.track_sids: Dict[str, str] = {}
        self.track_names: Dict[str, str] = {}
        self.listener_languages: Dict[str, str] = {}
        self.buffers: Dict[str, bytearray] = {}

    def audio_track_name(self, listener_id: str) -> Optional[str]:
        return self.track_names.get(listener_id)

    def listener_ids_for_language(self, tgt_lang: str) -> Set[str]:
        return {
            listener_id
            for listener_id, listener_lang in self.listener_languages.items()
            if listener_lang == tgt_lang
        }

    async def ensure_listener(self, listener_id: str, tgt_lang: str) -> None:
        current_lang = self.listener_languages.get(listener_id)
        if current_lang == tgt_lang and listener_id in self.sources:
            return

        if current_lang is not None:
            await self.remove_listener(listener_id)

        source = rtc.AudioSource(self.output_sample_rate, _CHANNELS, queue_size_ms=1500)
        track_name = self._build_track_name(listener_id, tgt_lang)
        track = rtc.LocalAudioTrack.create_audio_track(track_name, source)

        self.listener_languages[listener_id] = tgt_lang
        self.sources[listener_id] = source
        self.track_names[listener_id] = track_name
        self.buffers[listener_id] = bytearray()

        try:
            publication = await self.room.local_participant.publish_track(track)
            self.track_sids[listener_id] = publication.sid
            self._update_permissions()
        except Exception:
            logger.exception(
                "Failed to publish interpreter track for %s -> %s",
                self.speaker_id,
                listener_id,
            )

    async def remove_listener(self, listener_id: str) -> None:
        self.clear_queues({listener_id})
        self.listener_languages.pop(listener_id, None)
        self.buffers.pop(listener_id, None)
        self.track_names.pop(listener_id, None)
        self.sources.pop(listener_id, None)

        track_sid = self.track_sids.pop(listener_id, None)
        if track_sid:
            try:
                await self.room.local_participant.unpublish_track(track_sid)
            except Exception:
                logger.exception(
                    "Failed to unpublish interpreter track for %s -> %s",
                    self.speaker_id,
                    listener_id,
                )
        self._update_permissions()

    async def capture_base64_audio(self, tgt_lang: str, encoded_chunk: str) -> None:
        await self.capture_pcm(tgt_lang, base64.b64decode(encoded_chunk))

    async def capture_pcm(self, tgt_lang: str, pcm_bytes: bytes) -> None:
        listener_ids = self.listener_ids_for_language(tgt_lang)
        if not listener_ids:
            return

        for listener_id in listener_ids:
            buffer = self.buffers.setdefault(listener_id, bytearray())
            buffer.extend(pcm_bytes)
            await self._publish_buffered_frames(listener_id, flush=False)

    async def flush(self, tgt_lang: Optional[str] = None) -> None:
        listener_ids = (
            self.listener_ids_for_language(tgt_lang)
            if tgt_lang is not None
            else set(self.sources.keys())
        )
        for listener_id in listener_ids:
            await self._publish_buffered_frames(listener_id, flush=True)

    def clear_queues(self, listener_ids: Optional[Set[str]] = None) -> None:
        target_ids = listener_ids or set(self.sources.keys())
        for listener_id in target_ids:
            buffer = self.buffers.get(listener_id)
            if buffer is not None:
                buffer.clear()

            source = self.sources.get(listener_id)
            if source is not None:
                try:
                    source.clear_queue()
                except Exception:
                    logger.exception(
                        "Failed to clear interpreter audio queue for %s -> %s",
                        self.speaker_id,
                        listener_id,
                    )

    async def shutdown(self) -> None:
        for listener_id in list(self.listener_languages.keys()):
            await self.remove_listener(listener_id)
        self.clear_queues()

    def _update_permissions(self) -> None:
        permissions = []
        for listener_id, track_sid in self.track_sids.items():
            permissions.append(
                rtc.ParticipantTrackPermission(
                    participant_identity=listener_id,
                    allow_all=False,
                    allowed_track_sids=[track_sid],
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

    async def _publish_buffered_frames(self, listener_id: str, *, flush: bool) -> None:
        source = self.sources.get(listener_id)
        if source is None:
            return

        buffer = self.buffers.setdefault(listener_id, bytearray())
        while len(buffer) >= self._frame_bytes:
            frame_bytes = bytes(buffer[: self._frame_bytes])
            del buffer[: self._frame_bytes]
            if not await self._capture_frame(listener_id, source, frame_bytes):
                return

        if flush and buffer:
            padded = bytes(buffer) + (b"\x00" * (self._frame_bytes - len(buffer)))
            buffer.clear()
            await self._capture_frame(listener_id, source, padded)

    async def _capture_frame(
        self,
        listener_id: str,
        source: rtc.AudioSource,
        frame_bytes: bytes,
    ) -> bool:
        frame = rtc.AudioFrame(
            data=frame_bytes,
            sample_rate=self.output_sample_rate,
            num_channels=_CHANNELS,
            samples_per_channel=self._frame_bytes // _BYTES_PER_SAMPLE,
        )
        try:
            await source.capture_frame(frame)
            return True
        except Exception:
            logger.exception(
                "Failed to capture interpreter frame for %s -> %s",
                self.speaker_id,
                listener_id,
            )
            return False
