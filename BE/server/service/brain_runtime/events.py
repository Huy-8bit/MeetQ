from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from redis.asyncio import Redis

from server.events import EventType, build_envelope
from server.meeting_modes import (
    BRSE_PARTICIPANT_DISPLAY_NAME,
    BRSE_PARTICIPANT_ID,
    INTERPRETER_MODE_BRSE_PARTICIPANT,
    PARTICIPANT_KIND_VIRTUAL_BRSE,
)

logger = logging.getLogger(__name__)


class RedisEventPublisher:
    def __init__(self, redis: Redis, room_id: str, channel: str):
        self.redis = redis
        self.room_id = room_id
        self.channel = channel

    async def _publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        envelope = build_envelope(event_type, self.room_id, payload)
        try:
            await self.redis.publish(self.channel, json.dumps(envelope))
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
        relay_focus: Optional[Dict[str, Any]] = None,
        overlap: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self._publish(
            EventType.TRANSCRIPT_PARTIAL,
            self._build_source_payload(
                transcript_id=transcript_id,
                utterance_id=utterance_id,
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                src_lang=src_lang,
                text=text,
                created_at=created_at,
                fallback_used=fallback_used,
                is_final=False,
                relay_focus=relay_focus,
                overlap=overlap,
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
        relay_focus: Optional[Dict[str, Any]] = None,
        overlap: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self._publish(
            EventType.TRANSCRIPT_FINAL,
            self._build_source_payload(
                transcript_id=transcript_id,
                utterance_id=utterance_id,
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                src_lang=src_lang,
                text=text,
                created_at=created_at,
                fallback_used=fallback_used,
                is_final=True,
                relay_focus=relay_focus,
                overlap=overlap,
            ),
        )

    async def publish_relay_transcript_partial(
        self,
        *,
        transcript_id: str,
        utterance_id: str,
        speaker_id: str,
        speaker_name: str,
        src_lang: str,
        target_lang: str,
        source_text: str,
        brse_text: str,
        created_at: str,
        brse_livekit_identity: str,
        audio_track_name: Optional[str] = None,
        audience_participant_ids: Optional[list[str]] = None,
        fallback_used: bool = False,
        relay_style: str = "normal",
        relay_focus: Optional[Dict[str, Any]] = None,
        overlap: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self._publish(
            EventType.TRANSCRIPT_PARTIAL,
            self._build_relay_payload(
                transcript_id=transcript_id,
                utterance_id=utterance_id,
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                src_lang=src_lang,
                target_lang=target_lang,
                source_text=source_text,
                brse_text=brse_text,
                created_at=created_at,
                brse_livekit_identity=brse_livekit_identity,
                audio_track_name=audio_track_name,
                audience_participant_ids=audience_participant_ids or [],
                fallback_used=fallback_used,
                is_final=False,
                relay_style=relay_style,
                relay_focus=relay_focus,
                overlap=overlap,
            ),
        )

    async def publish_relay_transcript_final(
        self,
        *,
        transcript_id: str,
        utterance_id: str,
        speaker_id: str,
        speaker_name: str,
        src_lang: str,
        target_lang: str,
        source_text: str,
        brse_text: str,
        created_at: str,
        brse_livekit_identity: str,
        audio_track_name: Optional[str] = None,
        audience_participant_ids: Optional[list[str]] = None,
        fallback_used: bool = False,
        latency_ms: Optional[int] = None,
        relay_style: str = "normal",
        relay_focus: Optional[Dict[str, Any]] = None,
        overlap: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = self._build_relay_payload(
            transcript_id=transcript_id,
            utterance_id=utterance_id,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            src_lang=src_lang,
            target_lang=target_lang,
            source_text=source_text,
            brse_text=brse_text,
            created_at=created_at,
            brse_livekit_identity=brse_livekit_identity,
            audio_track_name=audio_track_name,
            audience_participant_ids=audience_participant_ids or [],
            fallback_used=fallback_used,
            is_final=True,
            relay_style=relay_style,
            relay_focus=relay_focus,
            overlap=overlap,
        )
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms
        await self._publish(EventType.TRANSCRIPT_FINAL, payload)

    async def publish_status(
        self,
        *,
        speaker_id: str,
        target_lang: str,
        status: str,
        brse_livekit_identity: str,
        source_language: Optional[str] = None,
        fallback_used: bool = False,
        message: Optional[str] = None,
        audio_track_name: Optional[str] = None,
        audience_participant_ids: Optional[list[str]] = None,
        audio_track: Optional[Dict[str, Any]] = None,
        relay_focus: Optional[Dict[str, Any]] = None,
        overlap: Optional[Dict[str, Any]] = None,
    ) -> None:
        audience_ids = audience_participant_ids or []
        payload: Dict[str, Any] = {
            "speaker_id": speaker_id,
            "target_language": target_lang,
            "status": status,
            "fallback_used": fallback_used,
            "message": message,
            "relay_mode": INTERPRETER_MODE_BRSE_PARTICIPANT,
            "brse_participant": self._build_brse_participant_ref(brse_livekit_identity),
            "audience_participant_ids": audience_ids,
            "listener_ids": audience_ids,
        }
        if source_language is not None:
            payload["source_language"] = source_language
        if audio_track_name is not None:
            payload["audio_track_name"] = audio_track_name
        if relay_focus is not None:
            payload["relay_focus"] = relay_focus
        if overlap is not None:
            payload["overlap"] = overlap
        payload["audio_output"] = self._build_audio_output(
            speaker_id=speaker_id,
            src_lang=source_language,
            target_lang=target_lang,
            brse_livekit_identity=brse_livekit_identity,
            audio_track_name=audio_track_name,
            audience_participant_ids=audience_ids,
            audio_track=audio_track,
        )
        await self._publish(EventType.INTERPRETER_STATUS, payload)

    async def publish_error(
        self,
        code: str,
        message: str,
        *,
        speaker_id: Optional[str] = None,
        target_language: Optional[str] = None,
        fallback_used: bool = False,
        brse_livekit_identity: Optional[str] = None,
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
        if brse_livekit_identity is not None:
            payload["brse_participant"] = self._build_brse_participant_ref(brse_livekit_identity)
            payload["relay_mode"] = INTERPRETER_MODE_BRSE_PARTICIPANT
        await self._publish(EventType.INTERPRETER_ERROR, payload)

    def _build_source_payload(
        self,
        *,
        transcript_id: str,
        utterance_id: str,
        speaker_id: str,
        speaker_name: str,
        src_lang: str,
        text: str,
        created_at: str,
        fallback_used: bool,
        is_final: bool,
        relay_focus: Optional[Dict[str, Any]] = None,
        overlap: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        speaker_ref = self._build_speaker_ref(speaker_id, speaker_name, src_lang)
        payload = {
            "transcript_id": transcript_id,
            "utterance_id": utterance_id,
            "kind": "source",
            "speaker": speaker_ref,
            "original_speaker": speaker_ref,
            "text": text,
            "src_lang": src_lang,
            "tgt_lang": src_lang,
            "source_text": text,
            "translated_text": text,
            "brse_text": None,
            "audio_track_name": None,
            "audio_output": None,
            "fallback_used": fallback_used,
            "is_final": is_final,
            "created_at": created_at or self._now_str(),
            "relay_mode": None,
        }
        if relay_focus is not None:
            payload["relay_focus"] = relay_focus
        if overlap is not None:
            payload["overlap"] = overlap
        return payload

    def _build_relay_payload(
        self,
        *,
        transcript_id: str,
        utterance_id: str,
        speaker_id: str,
        speaker_name: str,
        src_lang: str,
        target_lang: str,
        source_text: str,
        brse_text: str,
        created_at: str,
        brse_livekit_identity: str,
        audio_track_name: Optional[str],
        audience_participant_ids: list[str],
        fallback_used: bool,
        is_final: bool,
        relay_style: str = "normal",
        relay_focus: Optional[Dict[str, Any]] = None,
        overlap: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        speaker_ref = self._build_speaker_ref(speaker_id, speaker_name, src_lang)
        audio_output = self._build_audio_output(
            speaker_id=speaker_id,
            src_lang=src_lang,
            target_lang=target_lang,
            brse_livekit_identity=brse_livekit_identity,
            audio_track_name=audio_track_name,
            audience_participant_ids=audience_participant_ids,
        )
        payload = {
            "transcript_id": transcript_id,
            "utterance_id": utterance_id,
            "kind": "relay",
            "speaker": speaker_ref,
            "original_speaker": speaker_ref,
            "brse_participant": self._build_brse_participant_ref(brse_livekit_identity),
            "relay_target": {
                "target_language": target_lang,
                "participant_ids": audience_participant_ids,
            },
            "text": brse_text,
            "src_lang": src_lang,
            "tgt_lang": target_lang,
            "source_text": source_text,
            "translated_text": brse_text,
            "brse_text": brse_text,
            "audio_track_name": audio_track_name,
            "audio_output": audio_output,
            "fallback_used": fallback_used,
            "is_final": is_final,
            "created_at": created_at or self._now_str(),
            "relay_mode": INTERPRETER_MODE_BRSE_PARTICIPANT,
            "relay_style": relay_style,
        }
        if relay_focus is not None:
            payload["relay_focus"] = relay_focus
        if overlap is not None:
            payload["overlap"] = overlap
        return payload

    def _build_audio_output(
        self,
        *,
        speaker_id: Optional[str],
        src_lang: Optional[str],
        target_lang: str,
        brse_livekit_identity: str,
        audio_track_name: Optional[str],
        audience_participant_ids: list[str],
        audio_track: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": "brse_participant_audio",
            "mode": "virtual_participant_track",
            "canonical": True,
            "track_available": audio_track_name is not None,
            "track_name": audio_track_name,
            "speaker_id": speaker_id,
            "source_language": src_lang,
            "target_language": target_lang,
            "participant_id": BRSE_PARTICIPANT_ID,
            "participant_kind": PARTICIPANT_KIND_VIRTUAL_BRSE,
            "livekit_identity": brse_livekit_identity,
            "audience_participant_ids": audience_participant_ids,
        }
        if audio_track is not None:
            payload["track"] = audio_track
            for key in (
                "model",
                "mode",
                "canonical",
                "track_available",
                "track_name",
                "track_sid",
                "output_suppressed",
                "suppressed_reason",
            ):
                if key in audio_track:
                    payload[key] = audio_track.get(key)
            if payload["track_name"] is None:
                payload["track_name"] = audio_track.get("track_name")
                payload["track_available"] = bool(audio_track.get("track_available"))
        return payload

    def _build_speaker_ref(self, speaker_id: str, speaker_name: str, src_lang: str) -> Dict[str, Any]:
        return {
            "participant_id": speaker_id,
            "display_name": speaker_name,
            "language": src_lang,
            "source_language": src_lang,
            "kind": "human",
            "is_virtual": False,
        }

    def _build_brse_participant_ref(self, brse_livekit_identity: str) -> Dict[str, Any]:
        return {
            "participant_id": BRSE_PARTICIPANT_ID,
            "display_name": BRSE_PARTICIPANT_DISPLAY_NAME,
            "language": "auto",
            "source_language": "auto",
            "kind": PARTICIPANT_KIND_VIRTUAL_BRSE,
            "is_virtual": True,
            "livekit_identity": brse_livekit_identity,
        }

    def _now_str(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
