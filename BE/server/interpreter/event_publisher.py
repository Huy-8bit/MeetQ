from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from redis.asyncio import Redis

from server.events import EventType, INTERPRETER_EVENTS_CHANNEL, build_envelope

logger = logging.getLogger(__name__)


class RedisEventPublisher:
    def __init__(self, redis: Redis, room_id: str):
        self.redis = redis
        self.room_id = room_id

    async def _publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        envelope = build_envelope(event_type, self.room_id, payload)
        try:
            await self.redis.publish(INTERPRETER_EVENTS_CHANNEL, json.dumps(envelope))
        except Exception:
            logger.exception("Failed to publish %s for room %s", event_type, self.room_id)

    async def publish_media_connected(self, participant_id: str) -> None:
        await self._publish(
            EventType.PARTICIPANT_MEDIA_CONNECTED,
            {"participant_id": participant_id},
        )

    async def publish_media_disconnected(self, participant_id: str) -> None:
        await self._publish(
            EventType.PARTICIPANT_MEDIA_DISCONNECTED,
            {"participant_id": participant_id},
        )

    async def publish_transcript_partial(
        self,
        transcript_id: str,
        speaker_id: str,
        speaker_name: str,
        src_lang: str,
        target_id: str,
        target_lang: str,
        source_text: str,
        translated_text: str,
        audio_track_name: Optional[str] = None,
        fallback_used: bool = False,
    ) -> None:
        await self._publish(
            EventType.TRANSCRIPT_PARTIAL,
            {
                "transcript_id": transcript_id,
                "speaker": {
                    "participant_id": speaker_id,
                    "display_name": speaker_name,
                    "source_language": src_lang,
                },
                "listener": {
                    "participant_id": target_id,
                    "target_language": target_lang,
                },
                "source_text": source_text,
                "translated_text": translated_text,
                "audio_track_name": audio_track_name,
                "fallback_used": fallback_used,
                "is_final": False,
            },
        )

    async def publish_transcript_final(
        self,
        transcript_id: str,
        speaker_id: str,
        speaker_name: str,
        src_lang: str,
        target_id: str,
        target_lang: str,
        source_text: str,
        translated_text: str,
        audio_track_name: Optional[str] = None,
        fallback_used: bool = False,
        latency_ms: Optional[int] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "transcript_id": transcript_id,
            "speaker": {
                "participant_id": speaker_id,
                "display_name": speaker_name,
                "source_language": src_lang,
            },
            "listener": {
                "participant_id": target_id,
                "target_language": target_lang,
            },
            "source_text": source_text,
            "translated_text": translated_text,
            "audio_track_name": audio_track_name,
            "fallback_used": fallback_used,
            "is_final": True,
        }
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms
        await self._publish(EventType.TRANSCRIPT_FINAL, payload)

    async def publish_status(
        self,
        speaker_id: str,
        target_lang: str,
        status: str,
        fallback_used: bool = False,
        message: Optional[str] = None,
    ) -> None:
        await self._publish(
            EventType.INTERPRETER_STATUS,
            {
                "speaker_id": speaker_id,
                "target_language": target_lang,
                "status": status,
                "fallback_used": fallback_used,
                "message": message,
            },
        )

    async def publish_error(
        self,
        code: str,
        message: str,
        *,
        speaker_id: Optional[str] = None,
        target_language: Optional[str] = None,
        fallback_used: bool = False,
    ) -> None:
        payload: Dict[str, Any] = {
            "code": code,
            "message": message,
            "fallback_used": fallback_used,
        }
        if speaker_id is not None:
            payload["speaker_id"] = speaker_id
        if target_language is not None:
            payload["target_language"] = target_language
        await self._publish(EventType.INTERPRETER_ERROR, payload)
