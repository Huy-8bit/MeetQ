"""Stores BRSE operations events for the admin portal.

* Redis (per room, expires with the room): latest interpreter status per speaker
  and the most recent ops events, for the live room inspector.
* MongoDB ``ai_ops_events`` (TTL-retained): relay traces and AI errors, for
  history, issues and AI metrics.

Recording is best-effort and never blocks meeting traffic: Mongo writes run as
background tasks and failures are only logged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from server.service.ops.catalog import (
    classify_ai_error,
    classify_relay_trace,
    language_pair,
    sanitize_message,
)
from server.service.ops.keys import (
    ROOM_AI_EVENTS_LIMIT,
    room_ai_events_key,
    room_ai_status_key,
)

logger = logging.getLogger(__name__)

AI_OPS_EVENTS_COLLECTION = "ai_ops_events"
EVENT_TYPE_RELAY_TRACE = "relay_trace"
EVENT_TYPE_AI_ERROR = "ai_error"

ASCENDING = 1
DESCENDING = -1


def _now_str() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def build_relay_trace_doc(room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    occurred_at = payload.get("occurred_at") or _now_str()
    issue_code, severity = classify_relay_trace(payload)
    metrics = payload.get("metrics") or {}
    return {
        "event_id": f"ops_{uuid.uuid4().hex[:16]}",
        "event_type": EVENT_TYPE_RELAY_TRACE,
        "room_id": room_id,
        "occurred_at": occurred_at,
        "occurred_at_dt": parse_dt(occurred_at),
        "issue_code": issue_code,
        "severity": severity,
        "utterance_id": payload.get("utterance_id"),
        "speaker_id": payload.get("speaker_id"),
        "speaker_name": payload.get("speaker_name"),
        "src_lang": payload.get("src_lang"),
        "target_lang": payload.get("target_lang"),
        "language_pair": language_pair(payload.get("src_lang"), payload.get("target_lang")),
        "outcome": payload.get("outcome"),
        "reason": payload.get("reason"),
        "relay_style": payload.get("relay_style"),
        "route_mode": payload.get("route_mode"),
        "overlap_level": payload.get("overlap_level"),
        "delivery_mode": payload.get("delivery_mode"),
        "source_accepted": payload.get("source_accepted"),
        "source_reason": payload.get("source_reason"),
        "policy_decision": payload.get("policy_decision"),
        "policy_reason": payload.get("policy_reason"),
        "output_rejected_reason": payload.get("output_rejected_reason"),
        "translation_requested": bool(payload.get("translation_requested")),
        "audio_requested": bool(payload.get("audio_requested")),
        "audio_delivered": bool(payload.get("audio_delivered")),
        "metrics": {key: value for key, value in metrics.items() if isinstance(value, (int, float))},
        "captions": [
            {
                "target_lang": item.get("target_lang"),
                "ok": bool(item.get("ok")),
                "latency_ms": item.get("latency_ms"),
            }
            for item in payload.get("captions") or []
            if isinstance(item, dict)
        ],
    }


def build_ai_error_doc(
    room_id: str,
    payload: Dict[str, Any],
    *,
    source: str,
    sent_at: Optional[str] = None,
) -> Dict[str, Any]:
    occurred_at = payload.get("occurred_at") or sent_at or _now_str()
    message = sanitize_message(payload.get("message"))
    issue_code, severity = classify_ai_error(payload.get("code"), message)
    src_lang = payload.get("source_language")
    tgt_lang = payload.get("target_language")
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    return {
        "event_id": f"ops_{uuid.uuid4().hex[:16]}",
        "event_type": EVENT_TYPE_AI_ERROR,
        "room_id": room_id,
        "occurred_at": occurred_at,
        "occurred_at_dt": parse_dt(occurred_at),
        "issue_code": issue_code,
        "severity": severity,
        "code": payload.get("code"),
        "message": message,
        "source": source,
        "speaker_id": payload.get("speaker_id"),
        "src_lang": src_lang,
        "target_lang": tgt_lang,
        "language_pair": language_pair(src_lang, tgt_lang),
        "utterance_id": details.get("utterance_id"),
        "details": {
            key: value
            for key, value in details.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        },
    }


def _redis_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    view = {key: value for key, value in doc.items() if not key.endswith("_dt")}
    return view


class OpsRecorder:
    def __init__(
        self,
        redis: Any,
        db: Optional[Any],
        *,
        room_ttl_seconds: int,
        retention_days: int = 30,
    ) -> None:
        self.redis = redis
        self.db = db
        self.room_ttl_seconds = room_ttl_seconds
        self.retention_days = max(1, int(retention_days))
        self._tasks: Set[asyncio.Task] = set()

    @property
    def history_enabled(self) -> bool:
        return self.db is not None

    async def ensure_indexes(self) -> None:
        if self.db is None:
            return
        collection = self.db[AI_OPS_EVENTS_COLLECTION]
        await collection.create_index(
            [("occurred_at_dt", DESCENDING)],
            name="ai_ops_events_retention",
            expireAfterSeconds=self.retention_days * 86400,
        )
        await collection.create_index(
            [("room_id", ASCENDING), ("occurred_at_dt", DESCENDING)],
            name="ai_ops_events_by_room",
        )
        await collection.create_index(
            [("issue_code", ASCENDING), ("occurred_at_dt", DESCENDING)],
            name="ai_ops_events_by_issue",
        )
        await collection.create_index(
            [("event_type", ASCENDING), ("occurred_at_dt", DESCENDING)],
            name="ai_ops_events_by_type",
        )
        await collection.create_index(
            [("room_id", ASCENDING), ("utterance_id", ASCENDING)],
            name="ai_ops_events_by_utterance",
        )

    async def record_relay_trace(self, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        doc = build_relay_trace_doc(room_id, payload)
        await self._store(room_id, doc)
        return doc

    async def record_ai_error(
        self,
        room_id: str,
        payload: Dict[str, Any],
        *,
        source: str,
        sent_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        doc = build_ai_error_doc(room_id, payload, source=source, sent_at=sent_at)
        await self._store(room_id, doc)
        return doc

    async def record_status(
        self,
        room_id: str,
        payload: Dict[str, Any],
        *,
        sent_at: Optional[str] = None,
    ) -> None:
        speaker_id = payload.get("speaker_id")
        if not speaker_id:
            return
        relay_focus = payload.get("relay_focus") if isinstance(payload.get("relay_focus"), dict) else {}
        overlap = payload.get("overlap") if isinstance(payload.get("overlap"), dict) else {}
        audio_output = payload.get("audio_output") if isinstance(payload.get("audio_output"), dict) else {}
        entry = {
            "speaker_id": speaker_id,
            "status": payload.get("status"),
            "source_language": payload.get("source_language"),
            "target_language": payload.get("target_language"),
            "message": sanitize_message(payload.get("message")) or None,
            "updated_at": sent_at or _now_str(),
            "active_speaker_id": relay_focus.get("active_speaker_id"),
            "pending_relay_count": relay_focus.get("pending_relay_count"),
            "blocked_speaker_ids": relay_focus.get("blocked_speaker_ids") or [],
            "overlap_level": overlap.get("level"),
            "audio_track_available": audio_output.get("track_available"),
            "audience_count": len(payload.get("audience_participant_ids") or []),
        }
        key = room_ai_status_key(room_id)
        try:
            await self.redis.hset(key, speaker_id, json.dumps(entry))
            await self.redis.expire(key, self.room_ttl_seconds)
        except Exception:
            logger.warning("ops status write failed room_id=%s", room_id, exc_info=True)

    async def _store(self, room_id: str, doc: Dict[str, Any]) -> None:
        key = room_ai_events_key(room_id)
        try:
            pipe = self.redis.pipeline()
            pipe.rpush(key, json.dumps(_redis_view(doc)))
            pipe.ltrim(key, -ROOM_AI_EVENTS_LIMIT, -1)
            pipe.expire(key, self.room_ttl_seconds)
            await pipe.execute()
        except Exception:
            logger.warning("ops live event write failed room_id=%s", room_id, exc_info=True)
        if self.db is not None:
            self._schedule(lambda: self.db[AI_OPS_EVENTS_COLLECTION].insert_one(dict(doc)))

    def _schedule(self, factory: Callable[[], Awaitable[Any]]) -> None:
        try:
            task = asyncio.get_running_loop().create_task(self._run(factory))
        except RuntimeError:
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, factory: Callable[[], Awaitable[Any]]) -> None:
        try:
            await factory()
        except Exception as exc:
            logger.warning("ops history write failed: %s", type(exc).__name__)

    async def shutdown(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
