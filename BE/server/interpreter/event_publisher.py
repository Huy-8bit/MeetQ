from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from redis.asyncio import Redis

from server.events import EventType, INTERPRETER_EVENTS_CHANNEL, build_envelope

logger = logging.getLogger(__name__)

_AUDIO_MODEL = "translated_audio_first"
_CROSS_LANGUAGE_REMOTE_AUDIO = "interpreter_track"
_CANONICAL_REMOTE_AUDIO = "interpreter_track_for_cross_language"
_SAME_LANGUAGE_POLICY = "human_passthrough"


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

    async def publish_source_transcript_partial(
        self,
        *,
        transcript_id: str,
        utterance_id: str,
        speaker_id: str,
        speaker_name: str,
        src_lang: str,
        text: str,
        created_at: str,
        fallback_used: bool = False,
    ) -> None:
        await self._publish(
            EventType.TRANSCRIPT_PARTIAL,
            self._build_transcript_payload(
                transcript_id=transcript_id,
                utterance_id=utterance_id,
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                src_lang=src_lang,
                kind="source",
                text=text,
                source_text=text,
                translated_text=text,
                target_id=speaker_id,
                target_lang=src_lang,
                audio_track_name=None,
                audio_output=None,
                created_at=created_at,
                fallback_used=fallback_used,
                is_final=False,
            ),
        )

    async def publish_source_transcript_final(
        self,
        *,
        transcript_id: str,
        utterance_id: str,
        speaker_id: str,
        speaker_name: str,
        src_lang: str,
        text: str,
        created_at: str,
        fallback_used: bool = False,
    ) -> None:
        await self._publish(
            EventType.TRANSCRIPT_FINAL,
            self._build_transcript_payload(
                transcript_id=transcript_id,
                utterance_id=utterance_id,
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                src_lang=src_lang,
                kind="source",
                text=text,
                source_text=text,
                translated_text=text,
                target_id=speaker_id,
                target_lang=src_lang,
                audio_track_name=None,
                audio_output=None,
                created_at=created_at,
                fallback_used=fallback_used,
                is_final=True,
            ),
        )

    async def publish_transcript_partial(
        self,
        *,
        transcript_id: str,
        utterance_id: str,
        speaker_id: str,
        speaker_name: str,
        src_lang: str,
        target_id: str,
        target_lang: str,
        source_text: str,
        translated_text: str,
        created_at: str,
        audio_track_name: Optional[str] = None,
        fallback_used: bool = False,
    ) -> None:
        audio_output = self._build_listener_audio_output(
            speaker_id=speaker_id,
            listener_id=target_id,
            src_lang=src_lang,
            target_lang=target_lang,
            audio_track_name=audio_track_name,
        )
        await self._publish(
            EventType.TRANSCRIPT_PARTIAL,
            self._build_transcript_payload(
                transcript_id=transcript_id,
                utterance_id=utterance_id,
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                src_lang=src_lang,
                kind="translated",
                text=translated_text,
                source_text=source_text,
                translated_text=translated_text,
                target_id=target_id,
                target_lang=target_lang,
                audio_track_name=audio_track_name,
                audio_output=audio_output,
                created_at=created_at,
                fallback_used=fallback_used,
                is_final=False,
            ),
        )

    async def publish_transcript_final(
        self,
        *,
        transcript_id: str,
        utterance_id: str,
        speaker_id: str,
        speaker_name: str,
        src_lang: str,
        target_id: str,
        target_lang: str,
        source_text: str,
        translated_text: str,
        created_at: str,
        audio_track_name: Optional[str] = None,
        fallback_used: bool = False,
        latency_ms: Optional[int] = None,
    ) -> None:
        audio_output = self._build_listener_audio_output(
            speaker_id=speaker_id,
            listener_id=target_id,
            src_lang=src_lang,
            target_lang=target_lang,
            audio_track_name=audio_track_name,
        )
        payload = self._build_transcript_payload(
            transcript_id=transcript_id,
            utterance_id=utterance_id,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            src_lang=src_lang,
            kind="translated",
            text=translated_text,
            source_text=source_text,
            translated_text=translated_text,
            target_id=target_id,
            target_lang=target_lang,
            audio_track_name=audio_track_name,
            audio_output=audio_output,
            created_at=created_at,
            fallback_used=fallback_used,
            is_final=True,
        )
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
        source_language: Optional[str] = None,
        audio_track_name: Optional[str] = None,
        listener_ids: Optional[list[str]] = None,
        audio_tracks: Optional[list[Dict[str, Any]]] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "speaker_id": speaker_id,
            "target_language": target_lang,
            "status": status,
            "fallback_used": fallback_used,
            "message": message,
        }
        if source_language is not None:
            payload["source_language"] = source_language
        if listener_ids is not None:
            payload["listener_ids"] = listener_ids
        if audio_track_name is not None:
            payload["audio_track_name"] = audio_track_name
        payload["audio_output"] = self._build_runtime_audio_output(
            speaker_id=speaker_id,
            src_lang=source_language,
            target_lang=target_lang,
            audio_track_name=audio_track_name,
            listener_ids=listener_ids or [],
            audio_tracks=audio_tracks or [],
        )
        await self._publish(
            EventType.INTERPRETER_STATUS,
            payload,
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

    def _build_listener_audio_output(
        self,
        *,
        speaker_id: str,
        listener_id: str,
        src_lang: str,
        target_lang: str,
        audio_track_name: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "model": _AUDIO_MODEL,
            "mode": "interpreter_track",
            "canonical": True,
            "cross_language_remote_audio": _CROSS_LANGUAGE_REMOTE_AUDIO,
            "canonical_remote_audio": _CANONICAL_REMOTE_AUDIO,
            "track_available": audio_track_name is not None,
            "track_name": audio_track_name
            or self._build_track_name(
                speaker_id=speaker_id,
                listener_id=listener_id,
                src_lang=src_lang,
                target_lang=target_lang,
            ),
            "speaker_id": speaker_id,
            "listener_id": listener_id,
            "source_language": src_lang,
            "target_language": target_lang,
            "same_language_policy": _SAME_LANGUAGE_POLICY,
        }

    def _build_transcript_payload(
        self,
        *,
        transcript_id: str,
        utterance_id: str,
        speaker_id: str,
        speaker_name: str,
        src_lang: str,
        kind: str,
        text: str,
        source_text: str,
        translated_text: Optional[str],
        target_id: Optional[str],
        target_lang: Optional[str],
        audio_track_name: Optional[str],
        audio_output: Optional[Dict[str, Any]],
        created_at: Optional[str],
        fallback_used: bool,
        is_final: bool,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "transcript_id": transcript_id,
            "utterance_id": utterance_id,
            "kind": kind,
            "speaker": {
                "participant_id": speaker_id,
                "display_name": speaker_name,
                "language": src_lang,
                "source_language": src_lang,
            },
            "text": text,
            "src_lang": src_lang,
            "source_text": source_text,
            "translated_text": translated_text,
            "audio_track_name": audio_track_name,
            "audio_output": audio_output,
            "fallback_used": fallback_used,
            "is_final": is_final,
            "created_at": created_at or self._now_str(),
        }
        if target_id is not None and target_lang is not None:
            payload["listener"] = {
                "participant_id": target_id,
                "target_language": target_lang,
            }
            payload["tgt_lang"] = target_lang
        else:
            payload["tgt_lang"] = None
        return payload

    def _build_runtime_audio_output(
        self,
        *,
        speaker_id: str,
        src_lang: Optional[str],
        target_lang: str,
        audio_track_name: Optional[str],
        listener_ids: list[str],
        audio_tracks: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "model": _AUDIO_MODEL,
            "mode": "interpreter_track",
            "canonical": True,
            "cross_language_remote_audio": _CROSS_LANGUAGE_REMOTE_AUDIO,
            "canonical_remote_audio": _CANONICAL_REMOTE_AUDIO,
            "speaker_id": speaker_id,
            "source_language": src_lang,
            "target_language": target_lang,
            "audio_track_name": audio_track_name,
            "listener_ids": listener_ids,
            "tracks": audio_tracks,
            "same_language_policy": _SAME_LANGUAGE_POLICY,
        }

    def _build_track_name(
        self,
        *,
        speaker_id: str,
        listener_id: str,
        src_lang: str,
        target_lang: str,
    ) -> str:
        return f"interp::{speaker_id}::{listener_id}::{src_lang}::{target_lang}"

    def _now_str(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
