"""Live operations data for the admin portal: Redis room state + runtime ops state + LiveKit."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from server.config import Settings
from server.models import ChatMessage, ParticipantState, RoomState, TranscriptEvent
from server.service.admin import metrics
from server.service.admin.errors import room_not_found
from server.service.admin.livekit_inspector import LiveKitInspector
from server.service.admin.schemas import (
    AiErrorSummary,
    LiveParticipant,
    LiveRoomDetail,
    LiveRoomRow,
    LiveRoomsResponse,
    ParticipantMedia,
    RoomBrseState,
    SpeakerAiStatus,
    TimelineItem,
    TimelineResponse,
    TranscriptLine,
    TranscriptResponse,
)
from server.service.ops.catalog import issue_definition
from server.service.ops.keys import (
    RUNTIME_HEARTBEAT_KEY,
    room_ai_events_key,
    room_ai_status_key,
)

logger = logging.getLogger(__name__)

ROOM_META_PATTERN = "room:*:meta"
ROOM_RECENT_ERROR_WINDOW = timedelta(minutes=10)
ROOM_STATUS_ORDER = {"error": 0, "live": 1, "empty": 2, "expired": 3}


def _loads(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


class _RoomBundle:
    def __init__(
        self,
        room: RoomState,
        participants: List[ParticipantState],
        statuses: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
    ) -> None:
        self.room = room
        self.participants = participants
        self.statuses = statuses
        self.events = events


class AdminLiveService:
    def __init__(
        self,
        redis: Any,
        settings: Settings,
        inspector: Optional[LiveKitInspector] = None,
    ) -> None:
        self.redis = redis
        self.settings = settings
        self.inspector = inspector

    # ── Loading ────────────────────────────────────────────────────────────

    async def heartbeat(self) -> Optional[Dict[str, Any]]:
        try:
            return _loads(await self.redis.get(RUNTIME_HEARTBEAT_KEY))
        except Exception:
            logger.warning("admin heartbeat read failed", exc_info=True)
            return None

    async def room_ids(self) -> List[str]:
        ids: List[str] = []
        async for key in self.redis.scan_iter(match=ROOM_META_PATTERN, count=500):
            key = key.decode() if isinstance(key, bytes) else key
            parts = key.split(":")
            if len(parts) == 3:
                ids.append(parts[1])
        return ids

    async def _load(self, room_id: str, *, event_limit: int = 40) -> Optional[_RoomBundle]:
        meta = _loads(await self.redis.get(f"room:{room_id}:meta"))
        if meta is None:
            return None
        try:
            room = RoomState.model_validate(meta)
        except Exception:
            logger.warning("admin skipped unreadable room meta room_id=%s", room_id)
            return None
        raw_participants = await self.redis.hgetall(f"room:{room_id}:participants") or {}
        participants: List[ParticipantState] = []
        for value in raw_participants.values():
            parsed = _loads(value)
            if parsed is None:
                continue
            try:
                participants.append(ParticipantState.model_validate(parsed))
            except Exception:
                continue
        raw_statuses = await self.redis.hgetall(room_ai_status_key(room_id)) or {}
        statuses = [entry for entry in (_loads(value) for value in raw_statuses.values()) if entry]
        raw_events = await self.redis.lrange(room_ai_events_key(room_id), -event_limit, -1) or []
        events = [entry for entry in (_loads(value) for value in raw_events) if entry]
        return _RoomBundle(room, participants, statuses, events)

    # ── Rows ───────────────────────────────────────────────────────────────

    def _row(self, bundle: _RoomBundle, heartbeat: Optional[Dict[str, Any]], now: datetime) -> LiveRoomRow:
        room = bundle.room
        humans = [participant for participant in bundle.participants if metrics.is_human(participant)]
        online = metrics.online_humans(humans)
        state = metrics.aggregate_ai_state(room.brse_enabled, bundle.statuses)
        error_times = [
            metrics.parse_dt(event.get("occurred_at"))
            for event in bundle.events
            if event.get("severity") == "error"
        ]
        error_times = [moment for moment in error_times if moment is not None]
        recent_errors = [moment for moment in error_times if now - moment <= ROOM_RECENT_ERROR_WINDOW]
        last_error_at = max(error_times) if error_times else None
        runtime_attached = None
        # The runtime intentionally stops for rooms with nobody online; only flag it when people are there.
        if heartbeat is not None and room.brse_enabled and online:
            runtime_attached = room.room_id in (heartbeat.get("active_room_ids") or [])
        return LiveRoomRow(
            room_id=room.room_id,
            state=room.state,
            status=metrics.room_status(
                expires_at=room.expires_at,
                online_human_count=len(online),
                ai_state=state,
                last_error_at=last_error_at,
                now=now,
            ),
            room_languages=metrics.room_languages_of(room),
            participants_online=len(online),
            participants_total=len(humans),
            ai_mode=metrics.ai_mode_of(room),
            brse_enabled=room.brse_enabled,
            brse_state=state,
            runtime_attached=runtime_attached,
            created_at=room.created_at,
            activated_at=room.activated_at,
            expires_at=room.expires_at,
            seconds_left=metrics.seconds_left(room.expires_at, now),
            password_protected=bool(getattr(room, "password_required", False)),
            recent_error_count=len(recent_errors),
            last_error_at=metrics.iso(last_error_at),
        )

    async def all_rows(self) -> tuple[List[LiveRoomRow], Optional[Dict[str, Any]]]:
        now = metrics.utc_now()
        heartbeat, room_ids = await asyncio.gather(self.heartbeat(), self.room_ids())
        bundles = await asyncio.gather(*(self._load(room_id) for room_id in room_ids))
        rows = [self._row(bundle, heartbeat, now) for bundle in bundles if bundle is not None]
        rows.sort(
            key=lambda row: (
                ROOM_STATUS_ORDER.get(row.status, 9),
                -(metrics.parse_dt(row.created_at) or now).timestamp(),
            )
        )
        return rows, heartbeat

    async def list_rooms(
        self,
        *,
        q: Optional[str],
        status: Optional[str],
        ai_mode: Optional[str],
        language: Optional[str],
        page: int,
        page_size: int,
    ) -> LiveRoomsResponse:
        rows, heartbeat = await self.all_rows()
        counts: Dict[str, int] = {key: 0 for key in metrics.ROOM_STATUSES}
        for row in rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        filtered = filter_live_rows(rows, q=q, status=status, ai_mode=ai_mode, language=language)
        start = (page - 1) * page_size
        return LiveRoomsResponse(
            items=filtered[start : start + page_size],
            page=page,
            page_size=page_size,
            total=len(filtered),
            counts_by_status=counts,
            runtime_online=heartbeat is not None,
        )

    # ── Detail ─────────────────────────────────────────────────────────────

    async def room_detail(self, room_id: str) -> LiveRoomDetail:
        bundle = await self._load(room_id, event_limit=150)
        if bundle is None:
            raise room_not_found(room_id)
        now = metrics.utc_now()
        heartbeat = await self.heartbeat()
        row = self._row(bundle, heartbeat, now)

        media_by_identity: Optional[Dict[str, Dict[str, Any]]] = None
        if self.inspector is not None:
            media_by_identity = await self.inspector.participant_media(room_id)

        names = {participant.participant_id: participant.display_name for participant in bundle.participants}
        participants = [
            self._participant(participant, media_by_identity)
            for participant in bundle.participants
            if metrics.is_human(participant)
        ]
        participants.sort(key=lambda item: (item.status == "disconnected", item.joined_at or ""))
        for virtual in bundle.room.virtual_participants if bundle.room.brse_enabled else []:
            participants.append(self._participant(virtual, media_by_identity))

        return LiveRoomDetail(
            room=row,
            participants=participants,
            media_source="livekit" if media_by_identity is not None else "unavailable",
            brse=self._brse_state(bundle, row, names),
        )

    def _participant(self, participant: Any, media_by_identity: Optional[Dict[str, Dict[str, Any]]]) -> LiveParticipant:
        identity = getattr(participant, "livekit_identity", None) or participant.participant_id
        media = None
        if media_by_identity is not None:
            found = media_by_identity.get(identity)
            media = ParticipantMedia(**found) if found else ParticipantMedia(connection="not_connected")
        return LiveParticipant(
            participant_id=participant.participant_id,
            display_name=participant.display_name,
            language=participant.language,
            kind=participant.kind,
            is_virtual=bool(participant.is_virtual),
            status=participant.status,
            ws_connected=bool(getattr(participant, "ws_connected", False)),
            media_connected=bool(getattr(participant, "media_connected", False)),
            joined_at=participant.joined_at,
            last_seen_at=getattr(participant, "last_seen_at", None),
            is_screen_sharing=bool(getattr(participant, "is_screen_sharing", False)),
            media=media,
        )

    def _brse_state(self, bundle: _RoomBundle, row: LiveRoomRow, names: Dict[str, str]) -> RoomBrseState:
        statuses = sorted(bundle.statuses, key=lambda entry: entry.get("updated_at") or "", reverse=True)
        latest = statuses[0] if statuses else {}
        current_speaker_id = latest.get("active_speaker_id")
        queue_values = [entry.get("pending_relay_count") for entry in statuses if isinstance(entry.get("pending_relay_count"), int)]
        traces = [event for event in bundle.events if event.get("event_type") == "relay_trace"]
        delivered = [event for event in traces if event.get("outcome") in ("delivered", "caption_delivered")]
        problems = [
            event
            for event in bundle.events
            if event.get("severity") in ("error", "warning")
        ]
        last_problem = problems[-1] if problems else None
        latency: Dict[str, Any] = {}
        if delivered:
            latency["last"] = delivered[-1].get("metrics") or {}
        for key in ("stt_ms", "first_text_ms", "first_audio_ms", "total_ms"):
            latency[key] = metrics.latency_summary((event.get("metrics") or {}).get(key) for event in traces)
        audio_routing = bundle.room.audio_routing
        return RoomBrseState(
            enabled=bundle.room.brse_enabled,
            ai_mode=row.ai_mode,
            runtime_attached=row.runtime_attached,
            state=row.brse_state,
            current_speaker_id=current_speaker_id,
            current_speaker_name=names.get(current_speaker_id) if current_speaker_id else None,
            queue_depth=max(queue_values) if queue_values else None,
            speakers=[
                SpeakerAiStatus(
                    speaker_id=entry["speaker_id"],
                    speaker_name=names.get(entry["speaker_id"]),
                    status=entry.get("status"),
                    source_language=entry.get("source_language"),
                    target_language=entry.get("target_language"),
                    pending_relay_count=entry.get("pending_relay_count"),
                    overlap_level=entry.get("overlap_level"),
                    audience_count=entry.get("audience_count"),
                    message=entry.get("message"),
                    updated_at=entry.get("updated_at"),
                )
                for entry in statuses
                if entry.get("speaker_id")
            ],
            latency=latency,
            last_success_at=delivered[-1].get("occurred_at") if delivered else None,
            last_error=(
                AiErrorSummary(
                    occurred_at=last_problem.get("occurred_at"),
                    code=last_problem.get("code") or last_problem.get("outcome"),
                    issue_code=last_problem.get("issue_code"),
                    message=last_problem.get("message") or last_problem.get("reason"),
                )
                if last_problem
                else None
            ),
            output_mode_downgrade_reason=audio_routing.output_mode_downgrade_reason,
            audio_suppressed_reason=audio_routing.ai_audio_suppressed_reason,
        )

    # ── Timeline / transcript ──────────────────────────────────────────────

    async def _recent_transcripts(self, room_id: str) -> List[TranscriptEvent]:
        raw = await self.redis.lrange(f"room:{room_id}:transcripts", 0, -1) or []
        result: List[TranscriptEvent] = []
        for value in raw:
            parsed = _loads(value)
            if parsed is None:
                continue
            try:
                result.append(TranscriptEvent.model_validate(parsed))
            except Exception:
                continue
        return result

    async def room_timeline(self, room_id: str, *, limit: int) -> Optional[TimelineResponse]:
        """Newest-first relay traces and AI errors from the live store, or None if absent."""
        raw = await self.redis.lrange(room_ai_events_key(room_id), -limit, -1) or []
        events = [entry for entry in (_loads(value) for value in raw) if entry]
        if not events and await self.redis.get(f"room:{room_id}:meta") is None:
            return None
        texts = text_index(await self._recent_transcripts(room_id))
        items = [timeline_item(event, texts) for event in reversed(events)]
        return TimelineResponse(items=items, source="live")

    async def room_transcript(self, room_id: str, *, kind: str, limit: int) -> TranscriptResponse:
        if await self.redis.get(f"room:{room_id}:meta") is None:
            raise room_not_found(room_id)
        lines: List[TranscriptLine] = []
        if kind in ("all", "source", "relay"):
            for event in await self._recent_transcripts(room_id):
                line = transcript_line(event)
                if kind == "all" or line.kind == kind or (kind == "relay" and line.kind == "translated"):
                    lines.append(line)
        if kind in ("all", "chat"):
            raw = await self.redis.lrange(f"room:{room_id}:chat", 0, -1) or []
            for value in raw:
                parsed = _loads(value)
                if parsed is None:
                    continue
                try:
                    lines.append(chat_line(ChatMessage.model_validate(parsed)))
                except Exception:
                    continue
        if kind in ("all", "system"):
            raw = await self.redis.lrange(room_ai_events_key(room_id), 0, -1) or []
            for value in raw:
                event = _loads(value)
                if event and event.get("event_type") == "ai_error":
                    lines.append(system_line(event))
        lines.sort(key=lambda line: line.created_at or "")
        return TranscriptResponse(
            items=lines[-limit:],
            limit_note="Live rooms keep the latest 50 transcript lines and 100 chat messages.",
        )


# ── Helpers shared with history views ───────────────────────────────────────

def filter_live_rows(
    rows: Sequence[LiveRoomRow],
    *,
    q: Optional[str],
    status: Optional[str],
    ai_mode: Optional[str],
    language: Optional[str],
) -> List[LiveRoomRow]:
    needle = (q or "").strip().lower()
    result = []
    for row in rows:
        if needle and needle not in row.room_id.lower():
            continue
        if status and row.status != status:
            continue
        if ai_mode and row.ai_mode != ai_mode:
            continue
        if language and language not in row.room_languages:
            continue
        result.append(row)
    return result


def text_index(transcripts: Iterable[Any]) -> Dict[str, Dict[str, Optional[str]]]:
    """utterance_id -> {source_text, relay:<lang> text} from transcript events or archive docs."""
    index: Dict[str, Dict[str, Optional[str]]] = {}
    for item in transcripts:
        get = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)
        utterance_id = get("utterance_id")
        if not utterance_id:
            continue
        entry = index.setdefault(utterance_id, {})
        kind = get("kind")
        if kind == "source":
            entry["source_text"] = get("source_text") or get("text")
        elif kind in ("relay", "translated"):
            entry.setdefault("source_text", get("source_text"))
            target = get("target_lang")
            entry[f"relay:{target}"] = get("brse_text") or get("translated_text") or get("text")
    return index


def timeline_item(event: Dict[str, Any], texts: Dict[str, Dict[str, Optional[str]]]) -> TimelineItem:
    text = texts.get(event.get("utterance_id") or "", {})
    is_trace = event.get("event_type") == "relay_trace"
    relay_text = None
    if is_trace:
        relay_text = text.get(f"relay:{event.get('target_lang')}")
        if relay_text is None:
            relay_text = next(
                (value for key, value in text.items() if key.startswith("relay:") and value),
                None,
            )
    return TimelineItem(
        event_id=str(event.get("event_id") or ""),
        event_type=str(event.get("event_type") or ""),
        occurred_at=event.get("occurred_at"),
        room_id=event.get("room_id"),
        utterance_id=event.get("utterance_id"),
        speaker_id=event.get("speaker_id"),
        speaker_name=event.get("speaker_name"),
        src_lang=event.get("src_lang"),
        target_lang=event.get("target_lang"),
        outcome=event.get("outcome"),
        reason=event.get("reason"),
        issue_code=event.get("issue_code"),
        severity=event.get("severity"),
        code=event.get("code"),
        message=event.get("message"),
        relay_style=event.get("relay_style"),
        stages=metrics.build_trace_stages(event) if is_trace else [],
        metrics=event.get("metrics") or {},
        source_text=text.get("source_text") if is_trace else None,
        relay_text=relay_text,
    )


def transcript_line(event: TranscriptEvent) -> TranscriptLine:
    if event.kind == "source":
        return TranscriptLine(
            id=event.transcript_id,
            kind="source",
            created_at=event.created_at,
            speaker_id=event.speaker_id,
            speaker_name=event.speaker_display_name,
            language=event.src_lang,
            text=event.source_text or event.text,
        )
    return TranscriptLine(
        id=event.transcript_id,
        kind="relay" if event.kind == "relay" else "translated",
        created_at=event.created_at,
        speaker_id=event.speaker_id,
        speaker_name=event.speaker_display_name,
        language=event.src_lang,
        target_language=event.target_lang,
        text=event.brse_text or event.translated_text or event.text,
        source_text=event.source_text,
    )


def chat_line(message: ChatMessage) -> TranscriptLine:
    return TranscriptLine(
        id=message.message_id,
        kind="chat",
        created_at=message.created_at,
        speaker_id=message.participant_id,
        speaker_name=message.display_name,
        language=message.language,
        text=message.text,
        translations=[translation.model_dump() for translation in message.translations],
    )


def system_line(event: Dict[str, Any]) -> TranscriptLine:
    definition = issue_definition(str(event.get("issue_code") or "AI_ERROR"))
    return TranscriptLine(
        id=str(event.get("event_id") or ""),
        kind="system",
        created_at=event.get("occurred_at"),
        speaker_id=event.get("speaker_id"),
        speaker_name="BRSE AI",
        text=f"{definition.title}: {event.get('message') or event.get('code') or ''}".strip(),
    )
