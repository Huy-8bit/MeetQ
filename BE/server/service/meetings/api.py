"""My meetings: history, full content and keyword search for the signed-in user.

  GET /api/meetings                         my meetings (created or joined), newest first
        ?page&page_size&q&filter=all|created|recorded|summary&range=all|today|7d|30d
  GET /api/meetings/search?q&page           keyword search across my meetings' content
  GET /api/meetings/{room_id}               overview (+ recordings, participants, counts, summary)
  GET /api/meetings/{room_id}/transcript    full transcript, cursor-paginated (oldest first)
  GET /api/meetings/{room_id}/relay         AI relay history
  GET /api/meetings/{room_id}/chat          chat history with stored translations
  GET /api/meetings/{room_id}/summary       final summary
  GET /api/meetings/{room_id}/participants  people with their historical roles
  GET /api/meetings/{room_id}/recordings    recording segments (URLs via /api/recordings/*)
  GET /api/meetings/{room_id}/search?q      search inside one meeting
  GET /api/meetings/{room_id}/messages      (older clients) page-numbered transcript/relay/chat

Every endpoint needs the user session; access is checked per meeting from the user ID
(404 for meetings that aren't yours, 410 once retention has ended).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from server.service.admin.errors import AdminApiError
from server.service.archive.recording_service import public_recording
from server.service.archive.repository import REC_READY
from server.service.auth.dependencies import current_user
from server.service.gateway.app_state import app_state
from server.service.meetings.search import SearchQueryError, normalize_query
from server.service.meetings.service import (
    CONTENT_PAGE_SIZE,
    LIST_FILTERS,
    LIST_RANGES,
    MeetingAccess,
    MeetingHistoryError,
    MeetingHistoryService,
    jsonable,
)

meetings_router = APIRouter(tags=["meetings"])

MESSAGE_KINDS = {"transcript": ["source", "translated"], "relay": ["relay"], "chat": ["chat"]}
MESSAGE_PAGE_SIZE = 200


def _user_id(session: Optional[Dict[str, Any]]) -> Optional[str]:
    return ((session or {}).get("user") or {}).get("id")


def history_service() -> MeetingHistoryService:
    repo = app_state.archive_repo
    db = getattr(repo, "db", None) if repo is not None else None
    if db is None and app_state.room_history is not None:
        db = getattr(app_state.room_history, "db", None)
    if db is None:
        raise AdminApiError(503, "history_unavailable", "Meeting history is not available on this server.")
    return MeetingHistoryService(db, repo)


async def meeting_access(room_id: str, session: Dict[str, Any]) -> MeetingAccess:
    try:
        return await history_service().access(room_id, _user_id(session))
    except MeetingHistoryError as exc:
        raise AdminApiError(exc.status_code, exc.code, exc.message)


def user_recording(doc: Dict[str, Any]) -> Dict[str, Any]:
    state = public_recording(doc) or {}
    state["playable"] = doc["status"] == REC_READY
    return state


def _query(q: Optional[str]) -> str:
    try:
        return normalize_query(q)
    except SearchQueryError as exc:
        raise AdminApiError(422, "invalid_search_query", str(exc))


@meetings_router.get("/api/meetings")
async def list_my_meetings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    q: Optional[str] = Query(None, max_length=200),
    filter: str = Query("all"),
    range: str = Query("all"),
    session: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    if filter not in LIST_FILTERS or range not in LIST_RANGES:
        raise AdminApiError(422, "invalid_filter", "Unknown filter.")
    repo = app_state.archive_repo
    if (repo is None or not repo.enabled) and app_state.room_history is None:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    query = _query(q) if q and q.strip() else None
    return await history_service().list_meetings(
        _user_id(session), page=page, page_size=page_size, query=query, filter=filter, range=range
    )


@meetings_router.get("/api/meetings/search")
async def search_my_meetings(
    q: str = Query(..., max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    session: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    # Scope first (the user's own meetings), then match: never filter after searching.
    return await history_service().search_all(_user_id(session), _query(q), page=page, page_size=page_size)


@meetings_router.get("/api/meetings/{room_id}")
async def get_my_meeting(room_id: str, session: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    access = await meeting_access(room_id, session)
    detail = await history_service().detail(access)
    return {
        "meeting": detail["meeting"],
        "recordings": [user_recording(r) for r in detail["recordings"]],
        "participants": detail["participants"],
        "counts": detail["counts"],
        "summary": jsonable(detail["summary"]),
    }


def _content_params(
    cursor: Optional[str] = Query(None, max_length=512),
    before: Optional[str] = Query(None, max_length=512),
    start: Optional[str] = Query(None, max_length=512),
    limit: int = Query(CONTENT_PAGE_SIZE, ge=1, le=200),
) -> Dict[str, Any]:
    return {"cursor": cursor, "before": before, "start": start, "limit": limit}


async def _content(kind: str, room_id: str, session: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    access = await meeting_access(room_id, session)
    service = history_service()
    try:
        return await getattr(service, kind)(access, **params)
    except MeetingHistoryError as exc:
        raise AdminApiError(exc.status_code, exc.code, exc.message)


@meetings_router.get("/api/meetings/{room_id}/transcript")
async def get_meeting_transcript(
    room_id: str, params: Dict[str, Any] = Depends(_content_params), session: Dict[str, Any] = Depends(current_user)
) -> Dict[str, Any]:
    return await _content("transcript", room_id, session, params)


@meetings_router.get("/api/meetings/{room_id}/relay")
async def get_meeting_relay(
    room_id: str, params: Dict[str, Any] = Depends(_content_params), session: Dict[str, Any] = Depends(current_user)
) -> Dict[str, Any]:
    return await _content("relay", room_id, session, params)


@meetings_router.get("/api/meetings/{room_id}/chat")
async def get_meeting_chat(
    room_id: str, params: Dict[str, Any] = Depends(_content_params), session: Dict[str, Any] = Depends(current_user)
) -> Dict[str, Any]:
    return await _content("chat", room_id, session, params)


@meetings_router.get("/api/meetings/{room_id}/summary")
async def get_meeting_summary(room_id: str, session: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    await meeting_access(room_id, session)
    summary = await history_service().db["meeting_summaries"].find_one({"room_id": room_id, "summary_type": "final"})
    return {"summary": jsonable(summary)}


@meetings_router.get("/api/meetings/{room_id}/participants")
async def get_meeting_participants(room_id: str, session: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    access = await meeting_access(room_id, session)
    return {"items": await history_service().participants(access)}


@meetings_router.get("/api/meetings/{room_id}/recordings")
async def get_meeting_recordings(room_id: str, session: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    await meeting_access(room_id, session)
    repo = app_state.archive_repo
    recordings = await repo.list_recordings(room_id) if repo is not None and repo.enabled else []
    return {"items": [user_recording(r) for r in recordings]}


@meetings_router.get("/api/meetings/{room_id}/search")
async def search_meeting(
    room_id: str,
    q: str = Query(..., max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    session: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    access = await meeting_access(room_id, session)
    return await history_service().search_meeting(access, _query(q), page=page, page_size=page_size)


@meetings_router.get("/api/meetings/{room_id}/messages")
async def get_my_meeting_messages(
    room_id: str,
    kind: str = Query("transcript", pattern="^(transcript|relay|chat)$"),
    page: int = Query(1, ge=1),
    session: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    await meeting_access(room_id, session)
    db = history_service().db
    query = {"room_id": room_id, "kind": {"$in": MESSAGE_KINDS[kind]}}
    total = await db["room_messages"].count_documents(query)
    docs = (
        await db["room_messages"]
        .find(query)
        .sort([("created_at", 1), ("message_id", 1)])
        .skip((page - 1) * MESSAGE_PAGE_SIZE)
        .limit(MESSAGE_PAGE_SIZE)
        .to_list(length=MESSAGE_PAGE_SIZE)
    )
    return {"items": [_message(d) for d in docs], "total": total, "page": page, "page_size": MESSAGE_PAGE_SIZE}


def _message(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "message_id": doc.get("message_id"),
        "kind": doc.get("kind"),
        "created_at": doc.get("created_at"),
        "speaker_name": doc.get("speaker_display_name") or doc.get("display_name"),
        "language": doc.get("language") or doc.get("src_lang"),
        "target_language": doc.get("target_lang"),
        "text": doc.get("text"),
        "source_text": doc.get("source_text"),
        "translated_text": doc.get("translated_text"),
        "translations": doc.get("translations") or [],
    }
