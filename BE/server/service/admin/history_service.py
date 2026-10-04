"""Historical data for the admin portal, read from the existing MongoDB archive.

Collections used (all written by the gateway already):
  rooms, room_participants, room_messages, meeting_summaries  — meeting archive
  ai_ops_events                                                — BRSE ops events (OpsRecorder)
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from server.meeting_modes import BRSE_MODE_SILENT_SUMMARY
from server.service.admin import metrics
from server.service.admin.errors import AdminApiError, history_unavailable
from server.service.admin.live_service import text_index, timeline_item
from server.service.admin.schemas import (
    AiHealth,
    AiMetricsResponse,
    AnalyticsResponse,
    IssueAggregate,
    IssueDetailResponse,
    IssueOccurrence,
    IssuesResponse,
    Kpi,
    MeetingDetail,
    MeetingParticipantRow,
    MeetingRow,
    Page,
    RelayRow,
    StageHealth,
    TimelineResponse,
    TranscriptLine,
)
from server.service.ops.catalog import (
    ISSUES,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    issue_definition,
)
from server.service.ops.recorder import AI_OPS_EVENTS_COLLECTION

logger = logging.getLogger(__name__)

ROOMS = "rooms"
PARTICIPANTS = "room_participants"
MESSAGES = "room_messages"
SUMMARIES = "meeting_summaries"

ASCENDING = 1
DESCENDING = -1

# Bounded scans for in-process aggregation; responses flag `truncated` when hit.
METRICS_SAMPLE_LIMIT = 20000
ANALYTICS_ROOM_LIMIT = 20000
PARTICIPANT_SEARCH_LIMIT = 500

WINDOWS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
BLOCKING_REALTIME_ISSUES = ("REALTIME_AUTH_FAILED", "REALTIME_UNAVAILABLE")

TRACE_METRIC_PROJECTION = {
    "_id": 0,
    "outcome": 1,
    "reason": 1,
    "output_rejected_reason": 1,
    "translation_requested": 1,
    "audio_requested": 1,
    "audio_delivered": 1,
    "policy_decision": 1,
    "language_pair": 1,
    "src_lang": 1,
    "captions": 1,
    "metrics": 1,
}


def window_delta(window: str) -> timedelta:
    if window not in WINDOWS:
        raise AdminApiError(422, "invalid_window", f"window must be one of {', '.join(WINDOWS)}")
    return WINDOWS[window]


def ai_mode_filter(ai_mode: str) -> Dict[str, Any]:
    enabled_relay = {"brse_enabled": True, "brse_mode": {"$ne": BRSE_MODE_SILENT_SUMMARY}}
    if ai_mode == metrics.AI_MODE_OFF:
        return {"brse_enabled": {"$ne": True}}
    if ai_mode == metrics.AI_MODE_SUMMARY_CAPTURE:
        return {"brse_enabled": True, "brse_mode": BRSE_MODE_SILENT_SUMMARY}
    if ai_mode == metrics.AI_MODE_CAPTIONS:
        return {**enabled_relay, "room_languages": {"$size": 1}}
    if ai_mode == metrics.AI_MODE_VOICE_TEXT:
        return {**enabled_relay, "room_languages": {"$size": 2}, "brse_output_mode": {"$ne": "text_only"}}
    if ai_mode == metrics.AI_MODE_TEXT_ONLY:
        return {
            **enabled_relay,
            "$or": [
                {"room_languages": {"$size": 2}, "brse_output_mode": "text_only"},
                {"room_languages.2": {"$exists": True}},
            ],
        }
    raise AdminApiError(422, "invalid_ai_mode", f"ai_mode must be one of {', '.join(metrics.AI_MODES)}")


def meeting_status_filter(status: str, now: datetime) -> Dict[str, Any]:
    if status == metrics.MEETING_STATUS_LIVE:
        return {"status_summary.terminal": {"$ne": True}, "expires_at_dt": {"$gt": now}}
    if status == metrics.MEETING_STATUS_ENDED:
        return {"$or": [{"status_summary.terminal": True}, {"expires_at_dt": {"$lte": now}}]}
    raise AdminApiError(422, "invalid_status", f"status must be one of {', '.join(metrics.MEETING_STATUSES)}")


def _summary_meta(room_doc: Dict[str, Any], summary_type: str) -> Optional[Dict[str, Any]]:
    entry = (room_doc.get("meeting_summaries") or {}).get(summary_type)
    if entry is None and summary_type == "final":
        entry = room_doc.get("meeting_summary")
    return entry if isinstance(entry, dict) else None


def meeting_row(room_doc: Dict[str, Any], now: datetime) -> MeetingRow:
    final_meta = _summary_meta(room_doc, "final") or {}
    interim_meta = _summary_meta(room_doc, "interim") or {}
    return MeetingRow(
        room_id=room_doc["room_id"],
        status=metrics.meeting_status(room_doc, now),
        end_reason=metrics.meeting_end_reason(room_doc, now),
        created_at=room_doc.get("created_at"),
        ended_at=room_doc.get("ended_at"),
        duration_seconds=room_doc.get("duration_seconds"),
        room_languages=metrics.room_languages_of(room_doc),
        participant_count=int(room_doc.get("participant_count_total") or 0),
        ai_mode=metrics.ai_mode_of(room_doc),
        final_summary_status=final_meta.get("status"),
        live_summary_status=interim_meta.get("status"),
        password_protected=bool(room_doc.get("password_required")),
    )


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in doc.items() if key != "_id" and not key.endswith("_dt")}


def occurrence_from_event(doc: Dict[str, Any]) -> IssueOccurrence:
    code = str(doc.get("issue_code") or "AI_ERROR")
    definition = issue_definition(code)
    if doc.get("event_type") == "relay_trace":
        detail = " · ".join(part for part in (doc.get("outcome"), doc.get("reason")) if part)
    else:
        detail = doc.get("message") or doc.get("code")
    return IssueOccurrence(
        event_id=str(doc.get("event_id") or ""),
        occurred_at=doc.get("occurred_at"),
        room_id=doc.get("room_id"),
        issue_code=code,
        title=definition.title,
        severity=str(doc.get("severity") or definition.severity),
        speaker_name=doc.get("speaker_name"),
        language_pair=doc.get("language_pair"),
        detail=detail,
    )


def occurrence_from_summary(doc: Dict[str, Any]) -> IssueOccurrence:
    definition = ISSUES["SUMMARY_FAILED"]
    return IssueOccurrence(
        event_id=str(doc.get("summary_id") or f"{doc.get('room_id')}:{doc.get('summary_type')}"),
        occurred_at=doc.get("updated_at") or doc.get("created_at"),
        room_id=doc.get("room_id"),
        issue_code=definition.code,
        title=definition.title,
        severity=definition.severity,
        detail=f"{doc.get('summary_type') or 'final'} summary: {doc.get('error') or 'failed'}"[:300],
    )


def aggregate_issues(
    events: Sequence[Dict[str, Any]],
    failed_summaries: Sequence[Dict[str, Any]],
) -> List[IssueAggregate]:
    buckets: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "rooms": set(), "first": None, "latest": None, "pairs": Counter()}
    )

    def add(code: str, room_id: Any, occurred_at: Any, pair: Any) -> None:
        bucket = buckets[code]
        bucket["count"] += 1
        if room_id:
            bucket["rooms"].add(room_id)
        moment = metrics.parse_dt(occurred_at)
        if moment is not None:
            bucket["first"] = moment if bucket["first"] is None else min(bucket["first"], moment)
            bucket["latest"] = moment if bucket["latest"] is None else max(bucket["latest"], moment)
        if pair:
            bucket["pairs"][pair] += 1

    for doc in events:
        if doc.get("issue_code"):
            add(doc["issue_code"], doc.get("room_id"), doc.get("occurred_at_dt") or doc.get("occurred_at"), doc.get("language_pair"))
    for doc in failed_summaries:
        add("SUMMARY_FAILED", doc.get("room_id"), doc.get("updated_at") or doc.get("created_at"), None)

    severity_rank = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}
    items = []
    for code, bucket in buckets.items():
        definition = issue_definition(code)
        top_pair = bucket["pairs"].most_common(1)
        items.append(
            IssueAggregate(
                code=code,
                title=definition.title,
                stage=definition.stage,
                severity=definition.severity,
                description=definition.description,
                occurrences=bucket["count"],
                affected_rooms=len(bucket["rooms"]),
                first_at=metrics.iso(bucket["first"]),
                latest_at=metrics.iso(bucket["latest"]),
                top_language_pair=top_pair[0][0] if top_pair else None,
            )
        )
    items.sort(key=lambda item: (severity_rank.get(item.severity, 3), -item.occurrences))
    return items


def unavailable_ai_health(reason: str = "History storage unavailable") -> AiHealth:
    unknown = StageHealth(status="unknown", reason=reason)
    return AiHealth(
        window_minutes=metrics.HEALTH_WINDOW_MINUTES,
        stt=unknown,
        translation=unknown,
        voice=unknown,
        summary=unknown,
    )


class AdminHistoryService:
    def __init__(self, db: Optional[Any], *, room_service: Any = None) -> None:
        self.db = db
        self.room_service = room_service

    @property
    def available(self) -> bool:
        return self.db is not None

    def _require(self) -> Any:
        if self.db is None:
            raise history_unavailable()
        return self.db

    async def ping(self) -> bool:
        if self.db is None:
            return False
        try:
            await self.db.command("ping")
            return True
        except Exception as exc:
            logger.info("admin mongo ping failed: %s", type(exc).__name__)
            return False

    async def ensure_indexes(self) -> None:
        if self.db is None:
            return
        await self.db[ROOMS].create_index([("created_at_dt", DESCENDING)], name="admin_rooms_by_created")
        await self.db[MESSAGES].create_index(
            [("kind", ASCENDING), ("created_at_dt", DESCENDING)],
            name="admin_messages_by_kind_created",
        )
        await self.db[PARTICIPANTS].create_index(
            [("display_name", ASCENDING)],
            name="admin_participants_by_name",
        )
        await self.db[SUMMARIES].create_index(
            [("status", ASCENDING), ("created_at_dt", DESCENDING)],
            name="admin_summaries_by_status_created",
        )

    # ── Meetings ───────────────────────────────────────────────────────────

    async def list_meetings(
        self,
        *,
        q: Optional[str],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
        language: Optional[str],
        ai_mode: Optional[str],
        summary_status: Optional[str],
        status: Optional[str],
        page: int,
        page_size: int,
    ) -> Page[MeetingRow]:
        db = self._require()
        now = metrics.utc_now()
        clauses: List[Dict[str, Any]] = []
        if date_from or date_to:
            created: Dict[str, Any] = {}
            if date_from:
                created["$gte"] = date_from
            if date_to:
                created["$lt"] = date_to
            clauses.append({"created_at_dt": created})
        if language:
            clauses.append({"room_languages": language})
        if ai_mode:
            clauses.append(ai_mode_filter(ai_mode))
        if summary_status:
            if summary_status == "none":
                clauses.append({"meeting_summaries.final": {"$exists": False}, "meeting_summary": {"$exists": False}})
            else:
                clauses.append({"meeting_summaries.final.status": summary_status})
        if status:
            clauses.append(meeting_status_filter(status, now))
        if q and q.strip():
            needle = q.strip()
            escaped = re.escape(needle)
            participant_rooms = await db[PARTICIPANTS].find(
                {"display_name": {"$regex": escaped, "$options": "i"}, "is_virtual": {"$ne": True}},
                {"_id": 0, "room_id": 1},
            ).limit(PARTICIPANT_SEARCH_LIMIT).to_list(length=PARTICIPANT_SEARCH_LIMIT)
            room_ids = sorted({doc["room_id"] for doc in participant_rooms if doc.get("room_id")})
            clauses.append(
                {"$or": [{"room_id": {"$regex": escaped, "$options": "i"}}, {"room_id": {"$in": room_ids}}]}
            )
        query: Dict[str, Any] = {"$and": clauses} if clauses else {}
        total = await db[ROOMS].count_documents(query)
        docs = await db[ROOMS].find(
            query,
            {
                "_id": 0,
                "room_id": 1,
                "state": 1,
                "status_summary": 1,
                "created_at": 1,
                "created_at_dt": 1,
                "ended_at": 1,
                "expires_at": 1,
                "expires_at_dt": 1,
                "duration_seconds": 1,
                "room_languages": 1,
                "meeting_languages": 1,
                "participant_count_total": 1,
                "brse_enabled": 1,
                "brse_mode": 1,
                "brse_output_mode": 1,
                "password_required": 1,
                "meeting_summaries": 1,
                "meeting_summary": 1,
            },
        ).sort("created_at_dt", DESCENDING).skip((page - 1) * page_size).limit(page_size).to_list(length=page_size)
        return Page[MeetingRow](
            items=[meeting_row(doc, now) for doc in docs],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def _room_doc(self, room_id: str) -> Dict[str, Any]:
        db = self._require()
        doc = await db[ROOMS].find_one({"room_id": room_id}, {"_id": 0, "participant_summaries": 0})
        if doc is None:
            raise AdminApiError(404, "meeting_not_found", f"Meeting {room_id} was not found in history.")
        return doc

    async def meeting_detail(self, room_id: str, *, live_in_store: bool) -> MeetingDetail:
        doc = await self._room_doc(room_id)
        now = metrics.utc_now()
        kind_counts = doc.get("transcript_kind_counts") or {}
        counts = {
            "source": int(kind_counts.get("source") or 0),
            "relay": int(kind_counts.get("relay") or 0),
            "translated": int(kind_counts.get("translated") or 0),
            "chat": int(doc.get("chat_message_count") or 0),
            "messages": int(doc.get("message_count") or 0),
            "participants": int(doc.get("participant_count_total") or 0),
        }
        return MeetingDetail(
            meeting=meeting_row(doc, now),
            activated_at=doc.get("activated_at"),
            expires_at=doc.get("expires_at"),
            brse_mode=doc.get("brse_mode"),
            brse_output_mode=doc.get("brse_output_mode"),
            counts=counts,
            summaries={
                "final": _summary_meta(doc, "final"),
                "interim": _summary_meta(doc, "interim"),
            },
            is_live_in_runtime_store=live_in_store,
        )

    async def _messages(
        self,
        room_id: str,
        kinds: Sequence[str],
        page: int,
        page_size: int,
    ) -> Tuple[List[Dict[str, Any]], int]:
        db = self._require()
        query = {"room_id": room_id, "kind": {"$in": list(kinds)}}
        total = await db[MESSAGES].count_documents(query)
        docs = await db[MESSAGES].find(query, {"_id": 0, "metadata": 0}).sort(
            "created_at_dt", ASCENDING
        ).skip((page - 1) * page_size).limit(page_size).to_list(length=page_size)
        return docs, total

    async def transcripts(self, room_id: str, page: int, page_size: int) -> Page[TranscriptLine]:
        await self._room_doc(room_id)
        docs, total = await self._messages(room_id, ["source"], page, page_size)
        return Page[TranscriptLine](
            items=[
                TranscriptLine(
                    id=str(doc.get("message_id")),
                    kind="source",
                    created_at=doc.get("created_at"),
                    speaker_id=doc.get("participant_id"),
                    speaker_name=doc.get("display_name"),
                    language=doc.get("src_lang") or doc.get("language"),
                    text=doc.get("source_text") or doc.get("text") or "",
                )
                for doc in docs
            ],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def relays(self, room_id: str, page: int, page_size: int) -> Page[RelayRow]:
        await self._room_doc(room_id)
        docs, total = await self._messages(room_id, ["relay", "translated"], page, page_size)
        utterance_ids = sorted({doc["utterance_id"] for doc in docs if doc.get("utterance_id")})
        traces: Dict[str, Dict[str, Any]] = {}
        if utterance_ids:
            trace_docs = await self.db[AI_OPS_EVENTS_COLLECTION].find(
                {"room_id": room_id, "event_type": "relay_trace", "utterance_id": {"$in": utterance_ids}},
                {"_id": 0, "utterance_id": 1, "outcome": 1, "reason": 1, "metrics": 1, "audio_requested": 1, "audio_delivered": 1, "captions": 1},
            ).to_list(length=len(utterance_ids) * 2)
            traces = {doc["utterance_id"]: doc for doc in trace_docs}
        rows = []
        for doc in docs:
            trace = traces.get(doc.get("utterance_id") or "")
            latency = None
            if trace:
                latency = (trace.get("metrics") or {}).get("total_ms")
                for caption in trace.get("captions") or []:
                    if caption.get("target_lang") == doc.get("target_lang"):
                        latency = caption.get("latency_ms")
            rows.append(
                RelayRow(
                    id=str(doc.get("message_id")),
                    created_at=doc.get("created_at"),
                    utterance_id=doc.get("utterance_id"),
                    speaker_name=doc.get("display_name"),
                    source_language=doc.get("src_lang"),
                    target_language=doc.get("target_lang"),
                    original=doc.get("source_text"),
                    translation=doc.get("brse_text") or doc.get("translated_text") or doc.get("text") or "",
                    relay_style=doc.get("relay_style"),
                    delivery_state=trace.get("outcome") if trace else None,
                    delivery_reason=trace.get("reason") if trace else None,
                    latency_ms=latency,
                    voice_delivered=(
                        bool(trace.get("audio_delivered")) if trace and trace.get("audio_requested") else None
                    ),
                )
            )
        return Page[RelayRow](items=rows, page=page, page_size=page_size, total=total)

    async def chat(self, room_id: str, page: int, page_size: int) -> Page[TranscriptLine]:
        await self._room_doc(room_id)
        docs, total = await self._messages(room_id, ["chat"], page, page_size)
        return Page[TranscriptLine](
            items=[
                TranscriptLine(
                    id=str(doc.get("message_id")),
                    kind="chat",
                    created_at=doc.get("created_at"),
                    speaker_id=doc.get("participant_id"),
                    speaker_name=doc.get("display_name"),
                    language=doc.get("language"),
                    text=doc.get("text") or "",
                    translations=list(doc.get("translations") or []),
                )
                for doc in docs
            ],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def summaries(self, room_id: str) -> Dict[str, Optional[Dict[str, Any]]]:
        await self._room_doc(room_id)
        docs = await self.db[SUMMARIES].find({"room_id": room_id}, {"_id": 0}).to_list(length=10)
        by_type: Dict[str, Optional[Dict[str, Any]]] = {"final": None, "interim": None}
        for doc in docs:
            by_type[str(doc.get("summary_type") or "final")] = _clean(doc)
        return by_type

    async def participants(self, room_id: str) -> List[MeetingParticipantRow]:
        await self._room_doc(room_id)
        docs = await self.db[PARTICIPANTS].find(
            {"room_id": room_id},
            {"_id": 0, "sessions": 0, "metadata": 0},
        ).sort("first_joined_at_dt", ASCENDING).to_list(length=500)
        return [
            MeetingParticipantRow(
                participant_id=doc.get("participant_id"),
                display_name=doc.get("display_name"),
                language=doc.get("language"),
                kind=doc.get("kind"),
                is_virtual=bool(doc.get("is_virtual")),
                first_joined_at=doc.get("first_joined_at"),
                last_joined_at=doc.get("last_joined_at"),
                last_left_at=doc.get("last_left_at"),
                join_count=int(doc.get("join_count") or 0),
            )
            for doc in docs
        ]

    async def timeline(self, room_id: str, *, limit: int) -> TimelineResponse:
        db = self._require()
        events = await db[AI_OPS_EVENTS_COLLECTION].find(
            {"room_id": room_id},
            {"_id": 0},
        ).sort("occurred_at_dt", DESCENDING).limit(limit).to_list(length=limit)
        utterance_ids = sorted({event["utterance_id"] for event in events if event.get("utterance_id")})
        messages: List[Dict[str, Any]] = []
        if utterance_ids:
            messages = await db[MESSAGES].find(
                {"room_id": room_id, "utterance_id": {"$in": utterance_ids}, "kind": {"$in": ["source", "relay", "translated"]}},
                {"_id": 0, "utterance_id": 1, "kind": 1, "text": 1, "source_text": 1, "brse_text": 1, "translated_text": 1, "target_lang": 1},
            ).to_list(length=len(utterance_ids) * 4)
        texts = text_index(messages)
        return TimelineResponse(items=[timeline_item(event, texts) for event in events], source="history")

    async def regenerate_final_summary(self, room_id: str, language: Optional[str]) -> Dict[str, Any]:
        from server.service.gateway.room_service import (
            InvalidMeetingSummaryLanguageError,
            MeetingSummaryNotFoundError,
            MeetingSummaryNotReadyError,
            MeetingSummaryUnavailableError,
            RoomNotFoundError,
        )

        if self.room_service is None:
            raise history_unavailable()
        try:
            summary = await self.room_service.generate_meeting_summary(
                room_id,
                "final",
                requested_language=language,
            )
        except MeetingSummaryNotReadyError:
            raise AdminApiError(409, "meeting_summary_not_ready", "Final summary can only be generated after the room ends.")
        except MeetingSummaryUnavailableError:
            raise history_unavailable()
        except (RoomNotFoundError, MeetingSummaryNotFoundError):
            raise AdminApiError(404, "meeting_not_found", f"Meeting {room_id} was not found.")
        except InvalidMeetingSummaryLanguageError as exc:
            raise AdminApiError(422, "invalid_summary_language", str(exc) or "Unsupported summary language.")
        return summary.model_dump()

    # ── AI metrics / health ────────────────────────────────────────────────

    async def _traces(self, start: datetime, limit: int = METRICS_SAMPLE_LIMIT) -> List[Dict[str, Any]]:
        db = self._require()
        return await db[AI_OPS_EVENTS_COLLECTION].find(
            {"event_type": "relay_trace", "occurred_at_dt": {"$gte": start}},
            TRACE_METRIC_PROJECTION,
        ).sort("occurred_at_dt", DESCENDING).limit(limit).to_list(length=limit)

    async def _summaries_since(self, start: datetime) -> List[Dict[str, Any]]:
        db = self._require()
        return await db[SUMMARIES].find(
            {"created_at_dt": {"$gte": start}},
            {"_id": 0, "status": 1, "summary_type": 1, "created_at": 1, "created_at_dt": 1, "generated_at": 1, "generated_at_dt": 1, "room_id": 1, "updated_at": 1, "error": 1, "summary_id": 1},
        ).limit(METRICS_SAMPLE_LIMIT).to_list(length=METRICS_SAMPLE_LIMIT)

    async def ai_health(self) -> AiHealth:
        now = metrics.utc_now()
        if self.db is None:
            return unavailable_ai_health()
        start = now - timedelta(minutes=metrics.HEALTH_WINDOW_MINUTES)
        traces = await self._traces(start)
        blocking = await self.db[AI_OPS_EVENTS_COLLECTION].count_documents(
            {"occurred_at_dt": {"$gte": start}, "issue_code": {"$in": list(BLOCKING_REALTIME_ISSUES)}}
        )
        stages = metrics.compute_stage_stats(traces)
        summaries = await self._summaries_since(now - timedelta(hours=24))
        return AiHealth(
            window_minutes=metrics.HEALTH_WINDOW_MINUTES,
            stt=StageHealth(**metrics.stage_health(stages["stt"], "stt", blocking_errors=blocking)),
            translation=StageHealth(**metrics.stage_health(stages["translation"], "translation", blocking_errors=blocking)),
            voice=StageHealth(**metrics.stage_health(stages["voice"], "voice", blocking_errors=blocking)),
            summary=StageHealth(**metrics.summary_health(metrics.summary_stats(summaries))),
        )

    async def ai_metrics(self, window: str) -> AiMetricsResponse:
        delta = window_delta(window)
        now = metrics.utc_now()
        start = now - delta
        traces = await self._traces(start)
        summaries = await self._summaries_since(start)
        return AiMetricsResponse(
            window=window,
            range_start=metrics.iso(start),
            range_end=metrics.iso(now),
            sample_limit=METRICS_SAMPLE_LIMIT,
            sampled=len(traces),
            truncated=len(traces) >= METRICS_SAMPLE_LIMIT,
            history_available=True,
            stages=metrics.compute_stage_stats(traces),
            summary=metrics.summary_stats(summaries),
            language_pairs=metrics.language_pair_stats(traces),
            health=await self.ai_health(),
            percentile_min_samples={f"p{q}": n for q, n in metrics.PERCENTILE_MIN_SAMPLES.items()},
        )

    # ── Issues ─────────────────────────────────────────────────────────────

    def _severities(self, include_info: bool) -> List[str]:
        return [SEVERITY_ERROR, SEVERITY_WARNING] + ([SEVERITY_INFO] if include_info else [])

    async def issues(self, window: str, *, include_info: bool) -> IssuesResponse:
        db = self._require()
        start = metrics.utc_now() - window_delta(window)
        events = await db[AI_OPS_EVENTS_COLLECTION].find(
            {
                "occurred_at_dt": {"$gte": start},
                "issue_code": {"$ne": None},
                "severity": {"$in": self._severities(include_info)},
            },
            {"_id": 0, "issue_code": 1, "room_id": 1, "occurred_at": 1, "occurred_at_dt": 1, "language_pair": 1},
        ).limit(METRICS_SAMPLE_LIMIT).to_list(length=METRICS_SAMPLE_LIMIT)
        failed = await db[SUMMARIES].find(
            {"status": "failed", "created_at_dt": {"$gte": start}},
            {"_id": 0, "room_id": 1, "created_at": 1, "updated_at": 1},
        ).limit(METRICS_SAMPLE_LIMIT).to_list(length=METRICS_SAMPLE_LIMIT)
        return IssuesResponse(
            window=window,
            history_available=True,
            truncated=len(events) >= METRICS_SAMPLE_LIMIT,
            items=aggregate_issues(events, failed),
        )

    async def issue_detail(self, code: str, window: str, page: int, page_size: int) -> IssueDetailResponse:
        db = self._require()
        start = metrics.utc_now() - window_delta(window)
        if code == "SUMMARY_FAILED":
            query = {"status": "failed", "created_at_dt": {"$gte": start}}
            total = await db[SUMMARIES].count_documents(query)
            docs = await db[SUMMARIES].find(query, {"_id": 0}).sort("created_at_dt", DESCENDING).skip(
                (page - 1) * page_size
            ).limit(page_size).to_list(length=page_size)
            all_docs = await db[SUMMARIES].find(query, {"_id": 0, "room_id": 1, "created_at": 1, "updated_at": 1}).limit(
                METRICS_SAMPLE_LIMIT
            ).to_list(length=METRICS_SAMPLE_LIMIT)
            aggregates = aggregate_issues([], all_docs)
            occurrences = [occurrence_from_summary(doc) for doc in docs]
        else:
            if code not in ISSUES:
                raise AdminApiError(404, "issue_not_found", f"Unknown issue code {code}.")
            query = {"issue_code": code, "occurred_at_dt": {"$gte": start}}
            total = await db[AI_OPS_EVENTS_COLLECTION].count_documents(query)
            docs = await db[AI_OPS_EVENTS_COLLECTION].find(query, {"_id": 0}).sort("occurred_at_dt", DESCENDING).skip(
                (page - 1) * page_size
            ).limit(page_size).to_list(length=page_size)
            all_docs = await db[AI_OPS_EVENTS_COLLECTION].find(
                query,
                {"_id": 0, "issue_code": 1, "room_id": 1, "occurred_at": 1, "occurred_at_dt": 1, "language_pair": 1},
            ).limit(METRICS_SAMPLE_LIMIT).to_list(length=METRICS_SAMPLE_LIMIT)
            aggregates = aggregate_issues(all_docs, [])
            occurrences = [occurrence_from_event(doc) for doc in docs]
        definition = issue_definition(code)
        aggregate = aggregates[0] if aggregates else IssueAggregate(
            code=code,
            title=definition.title,
            stage=definition.stage,
            severity=definition.severity,
            description=definition.description,
            occurrences=0,
            affected_rooms=0,
        )
        return IssueDetailResponse(
            window=window,
            issue=aggregate,
            occurrences=Page[IssueOccurrence](items=occurrences, page=page, page_size=page_size, total=total),
        )

    async def recent_issue_occurrences(self, limit: int = 8) -> List[IssueOccurrence]:
        db = self._require()
        docs = await db[AI_OPS_EVENTS_COLLECTION].find(
            {"severity": {"$in": [SEVERITY_ERROR, SEVERITY_WARNING]}},
            {"_id": 0},
        ).sort("occurred_at_dt", DESCENDING).limit(limit).to_list(length=limit)
        return [occurrence_from_event(doc) for doc in docs]

    # ── Overview KPIs ──────────────────────────────────────────────────────

    async def overview_kpis(self, today_start: datetime) -> Dict[str, Kpi]:
        db = self._require()
        now = metrics.utc_now()
        elapsed = now - today_start
        yesterday_start = today_start - timedelta(days=1)
        meetings_today = await db[ROOMS].count_documents({"created_at_dt": {"$gte": today_start, "$lt": now}})
        meetings_yesterday = await db[ROOMS].count_documents(
            {"created_at_dt": {"$gte": yesterday_start, "$lt": yesterday_start + elapsed}}
        )
        error_query = {"severity": {"$in": [SEVERITY_ERROR, SEVERITY_WARNING]}}
        errors_hour = await db[AI_OPS_EVENTS_COLLECTION].count_documents(
            {**error_query, "occurred_at_dt": {"$gte": now - timedelta(hours=1)}}
        )
        errors_prev_hour = await db[AI_OPS_EVENTS_COLLECTION].count_documents(
            {**error_query, "occurred_at_dt": {"$gte": now - timedelta(hours=2), "$lt": now - timedelta(hours=1)}}
        )
        summary_failures = await db[SUMMARIES].count_documents(
            {"status": "failed", "created_at_dt": {"$gte": today_start, "$lt": now}}
        )
        summary_failures_prev = await db[SUMMARIES].count_documents(
            {"status": "failed", "created_at_dt": {"$gte": yesterday_start, "$lt": yesterday_start + elapsed}}
        )
        return {
            "meetings_today": Kpi(value=meetings_today, previous=meetings_yesterday, note="Rooms created since start of day; previous = same time yesterday"),
            "relay_errors_1h": Kpi(value=errors_hour, previous=errors_prev_hour, note="Warning/error AI events in the last hour; previous = hour before"),
            "summary_failures_today": Kpi(value=summary_failures, previous=summary_failures_prev, note="Failed summaries since start of day"),
        }

    # ── Analytics ──────────────────────────────────────────────────────────

    async def analytics(self, start: datetime, end: datetime, tz_offset_minutes: int) -> AnalyticsResponse:
        db = self._require()
        rooms = await db[ROOMS].find(
            {"created_at_dt": {"$gte": start, "$lt": end}},
            {
                "_id": 0,
                "room_id": 1,
                "created_at": 1,
                "created_at_dt": 1,
                "duration_seconds": 1,
                "participant_count_total": 1,
                "room_languages": 1,
                "meeting_languages": 1,
                "brse_enabled": 1,
                "brse_mode": 1,
                "brse_output_mode": 1,
                "transcript_kind_counts": 1,
                "chat_message_count": 1,
                "meeting_summaries": 1,
            },
        ).limit(ANALYTICS_ROOM_LIMIT).to_list(length=ANALYTICS_ROOM_LIMIT)
        result = metrics.build_analytics(rooms, range_start=start, range_end=end, tz_offset_minutes=tz_offset_minutes)
        translated_chat = await db[MESSAGES].count_documents(
            {"kind": "chat", "translation_mode": "translate", "created_at_dt": {"$gte": start, "$lt": end}}
        )
        totals = result["totals"]
        return AnalyticsResponse(
            range_start=metrics.iso(start),
            range_end=metrics.iso(end),
            history_available=True,
            truncated=len(rooms) >= ANALYTICS_ROOM_LIMIT,
            totals=totals,
            meetings_over_time=result["meetings_over_time"],
            language_distribution=result["language_distribution"],
            ai_mode_usage=result["ai_mode_usage"],
            feature_usage={
                "translated_chat_messages": Kpi(value=translated_chat),
                "live_summaries": Kpi(value=totals["live_summaries"], note="Meetings with a completed live summary"),
                "final_summaries": Kpi(value=totals["final_summaries"], note="Meetings with a completed final summary"),
                "screen_share": Kpi(available=False, note="Screen share sessions are not persisted"),
            },
        )
