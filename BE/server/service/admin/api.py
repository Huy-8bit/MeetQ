"""Admin portal API (/api/admin). Every route requires an admin cookie session (sign-in: /api/admin/auth)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request

from server.config import Settings
from server.service.admin import metrics
from server.service.admin.config_view import build_admin_config
from server.service.admin.dependencies import (
    AdminContext,
    get_admin_context,
    get_admin_settings,
    require_admin,
)
from server.service.admin.errors import AdminApiError
from server.service.admin.health import system_health
from server.service.admin.history_service import unavailable_ai_health
from server.service.admin.schemas import (
    AdminConfigResponse,
    AiMetricsResponse,
    AnalyticsResponse,
    IssueDetailResponse,
    IssuesResponse,
    Kpi,
    LiveRoomDetail,
    LiveRoomsResponse,
    MeetingDetail,
    MeetingParticipantRow,
    MeetingRow,
    OverviewResponse,
    Page,
    RegenerateSummaryRequest,
    RelayRow,
    SystemHealth,
    TimelineResponse,
    TranscriptLine,
    TranscriptResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])
protected = [Depends(require_admin)]

PAGE_SIZE_MAX = 100
ROOM_STATUS_PATTERN = "^(live|empty|error|expired)$"
AI_MODE_PATTERN = "^(voice_text|text_only|captions|summary_capture|off)$"
LANGUAGE_PATTERN = "^(vi|en|ja|zh|ko|fr|es)$"
WINDOW_PATTERN = "^(15m|1h|24h|7d|30d)$"
OVERVIEW_LIVE_ROOMS_LIMIT = 10


def _parse_query_dt(value: Optional[str], field: str) -> Optional[datetime]:
    if value is None or value == "":
        return None
    parsed = metrics.parse_dt(value)
    if parsed is None:
        raise AdminApiError(422, "invalid_request", f"{field} must be an ISO-8601 datetime.")
    return parsed


# ── Overview / health ──────────────────────────────────────────────────────

@router.get("/health", response_model=SystemHealth, dependencies=protected)
async def get_system_health(context: AdminContext = Depends(get_admin_context)) -> SystemHealth:
    return await system_health(
        redis=context.redis,
        live_service=context.live,
        history_service=context.history,
        inspector=context.inspector,
    )


@router.get("/overview", response_model=OverviewResponse, dependencies=protected)
async def get_overview(
    today_start: Optional[str] = Query(None, description="Start of the admin's local day (ISO-8601)."),
    context: AdminContext = Depends(get_admin_context),
) -> OverviewResponse:
    now = metrics.utc_now()
    day_start = _parse_query_dt(today_start, "today_start") or now.replace(hour=0, minute=0, second=0, microsecond=0)
    if day_start > now or now - day_start > timedelta(hours=26):
        raise AdminApiError(422, "invalid_request", "today_start must be within the last 26 hours.")

    rows, _heartbeat = await context.live.all_rows()
    health = await system_health(
        redis=context.redis,
        live_service=context.live,
        history_service=context.history,
        inspector=context.inspector,
    )
    open_rows = [row for row in rows if row.status != "expired"]
    kpis = {
        "active_rooms": Kpi(value=sum(1 for row in open_rows if row.participants_online > 0), note="Rooms with at least one person online"),
        "open_rooms": Kpi(value=len(open_rows), note="Rooms that have not expired"),
        "participants_online": Kpi(value=sum(row.participants_online for row in open_rows)),
        "ai_enabled_rooms": Kpi(value=sum(1 for row in open_rows if row.brse_enabled)),
        "rooms_with_errors": Kpi(value=sum(1 for row in open_rows if row.status == "error")),
    }
    history_ok = context.history.available and next(
        (component.status == "healthy" for component in health.components if component.key == "mongo"),
        False,
    )
    recent_issues = []
    if history_ok:
        kpis.update(await context.history.overview_kpis(day_start))
        recent_issues = await context.history.recent_issue_occurrences()
    else:
        for key in ("meetings_today", "relay_errors_1h", "summary_failures_today"):
            kpis[key] = Kpi(available=False, note="History storage unavailable")
    return OverviewResponse(
        generated_at=metrics.iso(now),
        history_available=history_ok,
        kpis=kpis,
        live_rooms=open_rows[:OVERVIEW_LIVE_ROOMS_LIMIT],
        system_health=health,
        ai_health=await context.history.ai_health() if history_ok else unavailable_ai_health(),
        recent_issues=recent_issues,
    )


# ── Live rooms ─────────────────────────────────────────────────────────────

@router.get("/rooms", response_model=LiveRoomsResponse, dependencies=protected)
async def list_live_rooms(
    q: Optional[str] = Query(None, max_length=64),
    status: Optional[str] = Query(None, pattern=ROOM_STATUS_PATTERN),
    ai_mode: Optional[str] = Query(None, pattern=AI_MODE_PATTERN),
    language: Optional[str] = Query(None, pattern=LANGUAGE_PATTERN),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=PAGE_SIZE_MAX),
    context: AdminContext = Depends(get_admin_context),
) -> LiveRoomsResponse:
    return await context.live.list_rooms(
        q=q, status=status, ai_mode=ai_mode, language=language, page=page, page_size=page_size
    )


@router.get("/rooms/{room_id}", response_model=LiveRoomDetail, dependencies=protected)
async def get_live_room(room_id: str, context: AdminContext = Depends(get_admin_context)) -> LiveRoomDetail:
    return await context.live.room_detail(room_id)


@router.get("/rooms/{room_id}/timeline", response_model=TimelineResponse, dependencies=protected)
async def get_room_timeline(
    room_id: str,
    limit: int = Query(50, ge=1, le=150),
    context: AdminContext = Depends(get_admin_context),
) -> TimelineResponse:
    live = await context.live.room_timeline(room_id, limit=limit)
    if live is not None:
        return live
    if context.history.available:
        return await context.history.timeline(room_id, limit=limit)
    raise AdminApiError(404, "room_not_found", f"Room {room_id} was not found.")


@router.get("/rooms/{room_id}/transcript", response_model=TranscriptResponse, dependencies=protected)
async def get_room_transcript(
    room_id: str,
    kind: str = Query("all", pattern="^(all|source|relay|chat|system)$"),
    limit: int = Query(100, ge=1, le=200),
    context: AdminContext = Depends(get_admin_context),
) -> TranscriptResponse:
    return await context.live.room_transcript(room_id, kind=kind, limit=limit)


# ── Meetings (history) ─────────────────────────────────────────────────────

@router.get("/meetings", response_model=Page[MeetingRow], dependencies=protected)
async def list_meetings(
    q: Optional[str] = Query(None, max_length=80),
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    language: Optional[str] = Query(None, pattern=LANGUAGE_PATTERN),
    ai_mode: Optional[str] = Query(None, pattern=AI_MODE_PATTERN),
    summary_status: Optional[str] = Query(None, pattern="^(completed|failed|skipped|pending|none)$"),
    status: Optional[str] = Query(None, pattern="^(live|ended)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=PAGE_SIZE_MAX),
    context: AdminContext = Depends(get_admin_context),
) -> Page[MeetingRow]:
    return await context.history.list_meetings(
        q=q,
        date_from=_parse_query_dt(date_from, "from"),
        date_to=_parse_query_dt(date_to, "to"),
        language=language,
        ai_mode=ai_mode,
        summary_status=summary_status,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/meetings/{room_id}", response_model=MeetingDetail, dependencies=protected)
async def get_meeting(room_id: str, context: AdminContext = Depends(get_admin_context)) -> MeetingDetail:
    live = await context.redis.get(f"room:{room_id}:meta") is not None
    return await context.history.meeting_detail(room_id, live_in_store=live)


@router.get("/meetings/{room_id}/transcripts", response_model=Page[TranscriptLine], dependencies=protected)
async def get_meeting_transcripts(
    room_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=PAGE_SIZE_MAX),
    context: AdminContext = Depends(get_admin_context),
) -> Page[TranscriptLine]:
    return await context.history.transcripts(room_id, page, page_size)


@router.get("/meetings/{room_id}/relays", response_model=Page[RelayRow], dependencies=protected)
async def get_meeting_relays(
    room_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=PAGE_SIZE_MAX),
    context: AdminContext = Depends(get_admin_context),
) -> Page[RelayRow]:
    return await context.history.relays(room_id, page, page_size)


@router.get("/meetings/{room_id}/chat", response_model=Page[TranscriptLine], dependencies=protected)
async def get_meeting_chat(
    room_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=PAGE_SIZE_MAX),
    context: AdminContext = Depends(get_admin_context),
) -> Page[TranscriptLine]:
    return await context.history.chat(room_id, page, page_size)


@router.get("/meetings/{room_id}/summaries", dependencies=protected)
async def get_meeting_summaries(room_id: str, context: AdminContext = Depends(get_admin_context)) -> dict:
    return await context.history.summaries(room_id)


@router.post("/meetings/{room_id}/summaries/final", dependencies=protected)
async def regenerate_final_summary(
    room_id: str,
    body: RegenerateSummaryRequest,
    context: AdminContext = Depends(get_admin_context),
) -> dict:
    logger.info("admin requested final summary regeneration room_id=%s language=%s", room_id, body.language)
    return await context.history.regenerate_final_summary(room_id, body.language)


@router.get("/meetings/{room_id}/participants", response_model=List[MeetingParticipantRow], dependencies=protected)
async def get_meeting_participants(
    room_id: str,
    context: AdminContext = Depends(get_admin_context),
) -> List[MeetingParticipantRow]:
    return await context.history.participants(room_id)


# ── AI / issues / analytics / config ─────────────────────────────────────

@router.get("/ai/metrics", response_model=AiMetricsResponse, dependencies=protected)
async def get_ai_metrics(
    window: str = Query("1h", pattern=WINDOW_PATTERN),
    context: AdminContext = Depends(get_admin_context),
) -> AiMetricsResponse:
    return await context.history.ai_metrics(window)


@router.get("/issues", response_model=IssuesResponse, dependencies=protected)
async def get_issues(
    window: str = Query("24h", pattern=WINDOW_PATTERN),
    include_info: bool = Query(False),
    context: AdminContext = Depends(get_admin_context),
) -> IssuesResponse:
    return await context.history.issues(window, include_info=include_info)


@router.get("/issues/{code}", response_model=IssueDetailResponse, dependencies=protected)
async def get_issue(
    code: str,
    window: str = Query("24h", pattern=WINDOW_PATTERN),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=PAGE_SIZE_MAX),
    context: AdminContext = Depends(get_admin_context),
) -> IssueDetailResponse:
    return await context.history.issue_detail(code.upper(), window, page, page_size)


@router.get("/analytics", response_model=AnalyticsResponse, dependencies=protected)
async def get_analytics(
    date_from: str = Query(..., alias="from"),
    date_to: str = Query(..., alias="to"),
    tz_offset_minutes: int = Query(0, ge=-840, le=840),
    context: AdminContext = Depends(get_admin_context),
) -> AnalyticsResponse:
    start = _parse_query_dt(date_from, "from")
    end = _parse_query_dt(date_to, "to")
    if start is None or end is None or end <= start:
        raise AdminApiError(422, "invalid_request", "from must be before to.")
    if end - start > timedelta(days=366):
        raise AdminApiError(422, "invalid_request", "Range cannot exceed 366 days.")
    return await context.history.analytics(start, end, tz_offset_minutes)


@router.get("/config", response_model=AdminConfigResponse, dependencies=protected)
async def get_config(context: AdminContext = Depends(get_admin_context)) -> AdminConfigResponse:
    return build_admin_config(context.settings)
