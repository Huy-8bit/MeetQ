"""User-facing recording and meeting-history endpoints.

In-room (room token + signed-in user):
  POST /api/rooms/{room_id}/recordings                       start (idempotent)
  POST /api/rooms/{room_id}/recordings/{recording_id}/stop   stop  (idempotent)
  GET  /api/rooms/{room_id}/recordings/current               current room-level state

History (signed-in user who took part in the meeting, during retention):
  GET  /api/meetings
  GET  /api/meetings/{room_id}
  GET  /api/meetings/{room_id}/messages?kind=transcript|relay|chat
  GET  /api/recordings/{recording_id}
  POST /api/recordings/{recording_id}/playback-url | download-url   (short-lived presigned URL)

Access is decided by the stable user ID recorded at join time (`room_participants.user_id`
and the archive's `participant_user_ids`), never by display name.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from server.config import Settings
from server.service.admin.errors import AdminApiError
from server.service.archive.archive_service import recording_summary
from server.service.archive.recording_service import RecordingError, public_recording
from server.service.archive.repository import ARCHIVE_DELETED, ARCHIVE_LIVE_STATUSES, ARCHIVE_OPEN, REC_READY
from server.service.archive.retention import as_utc, effective_retention_days, iso, utcnow
from server.service.auth.dependencies import current_user, get_auth_settings, require_user
from server.service.gateway.app_state import app_state
from server.service.gateway.dependencies import verify_token_dependency

logger = logging.getLogger(__name__)

recordings_router = APIRouter(tags=["recordings"])
meetings_router = APIRouter(tags=["meetings"])

MESSAGE_KINDS = {"transcript": ["source", "translated"], "relay": ["relay"], "chat": ["chat"]}
MESSAGE_PAGE_SIZE = 200


def _error(status: int, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> AdminApiError:
    return AdminApiError(status, code, message, details)


def _services():
    if app_state.recording_service is None or app_state.archive_repo is None:
        raise _error(503, "service_unavailable", "Gateway is not initialized.")
    return app_state.recording_service, app_state.archive_service, app_state.archive_repo


def _user_id(session: Optional[Dict[str, Any]]) -> Optional[str]:
    return ((session or {}).get("user") or {}).get("id")


# ── In-room recording ───────────────────────────────────────────────────────


async def _room_participant(room_id: str, claims: Dict[str, Any]):
    participant_id = claims.get("participant_id")
    participant = await app_state.room_store.get_participant(room_id, participant_id) if participant_id else None
    if participant is None or participant.is_virtual or participant.kind != "human":
        raise _error(403, "not_in_room", "Join the meeting to control recording.")
    return participant


@recordings_router.post("/api/rooms/{room_id}/recordings")
async def start_recording(
    room_id: str,
    claims: Dict[str, Any] = Depends(verify_token_dependency),
    session: Optional[Dict[str, Any]] = Depends(require_user),
) -> Dict[str, Any]:
    recordings, _archives, _repo = _services()
    participant = await _room_participant(room_id, claims)
    snapshot = await app_state.room_store.get_room_snapshot(room_id)
    if snapshot is None:
        raise _error(404, "room_not_found", "Room not found.")
    try:
        state = await recordings.start(
            room_id,
            participant_id=participant.participant_id,
            display_name=participant.display_name,
            user_id=_user_id(session),
            room_languages=list(getattr(snapshot.room, "room_languages", []) or []),
        )
    except RecordingError as exc:
        raise _error(exc.status_code, exc.code, exc.message)
    return {"recording": state}


@recordings_router.post("/api/rooms/{room_id}/recordings/{recording_id}/stop")
async def stop_recording(
    room_id: str,
    recording_id: str,
    claims: Dict[str, Any] = Depends(verify_token_dependency),
    session: Optional[Dict[str, Any]] = Depends(require_user),
) -> Dict[str, Any]:
    recordings, _archives, _repo = _services()
    participant = await _room_participant(room_id, claims)
    try:
        state = await recordings.stop(
            room_id,
            recording_id,
            reason="user_stopped",
            stopped_by_name=participant.display_name,
        )
    except RecordingError as exc:
        raise _error(exc.status_code, exc.code, exc.message)
    return {"recording": state}


@recordings_router.get("/api/rooms/{room_id}/recordings/current")
async def current_recording(
    room_id: str,
    claims: Dict[str, Any] = Depends(verify_token_dependency),
    session: Optional[Dict[str, Any]] = Depends(require_user),
) -> Dict[str, Any]:
    recordings, _archives, _repo = _services()
    return {"recording": await recordings.current(room_id), "available": recordings.available}


# ── History ────────────────────────────────────────────────────────────────


async def _can_access(room_id: str, user_id: str, archive: Optional[Dict[str, Any]]) -> bool:
    if archive and user_id in (archive.get("participant_user_ids") or []):
        return True
    db = app_state.archive_repo.db
    return bool(await db["room_participants"].find_one({"room_id": room_id, "user_id": user_id}))


async def _meeting_for_user(room_id: str, session: Dict[str, Any]) -> Dict[str, Any]:
    _recordings, _archives, repo = _services()
    if not repo.enabled:
        raise _error(503, "history_unavailable", "Meeting history is not available on this server.")
    archive = await repo.get_archive_by_room(room_id)
    if archive and archive["status"] == ARCHIVE_DELETED:
        raise _error(410, "meeting_archive_deleted", "This meeting's recording and content have been deleted.")
    if not await _can_access(room_id, _user_id(session), archive):
        raise _error(404, "meeting_not_found", "Meeting not found.")
    expires_at = as_utc((archive or {}).get("expires_at"))
    if expires_at and expires_at <= utcnow():
        raise _error(410, "meeting_archive_expired", "This meeting's retention period has ended.")
    return archive or {"room_id": room_id, "status": ARCHIVE_OPEN}


def _meeting_row(archive: Dict[str, Any]) -> Dict[str, Any]:
    started = as_utc(archive.get("meeting_started_at"))
    ended = as_utc(archive.get("ended_at"))
    return {
        "room_id": archive["room_id"],
        "archive_id": archive.get("_id"),
        "status": archive.get("status"),
        "room_languages": archive.get("room_languages") or [],
        "meeting_started_at": iso(started),
        "ended_at": iso(ended),
        "duration_seconds": round((ended - started).total_seconds()) if started and ended else None,
        "participant_count": archive.get("participant_count"),
        "recording": archive.get("recording_summary") or recording_summary([]),
        "expires_at": iso(archive.get("expires_at")),
        "retention_days": effective_retention_days(archive) if archive.get("_id") else None,
    }


def _user_recording(doc: Dict[str, Any]) -> Dict[str, Any]:
    state = public_recording(doc) or {}
    state["playable"] = doc["status"] == REC_READY
    return state


@meetings_router.get("/api/meetings")
async def list_my_meetings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    _recordings, _archives, repo = _services()
    if not repo.enabled:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    query = {
        "participant_user_ids": _user_id(session),
        "status": {"$in": list(ARCHIVE_LIVE_STATUSES)},
        "$or": [{"expires_at": None}, {"expires_at": {"$gt": utcnow()}}],
    }
    total = await repo.count_archives(query)
    archives = await repo.list_archives(query, sort="ended_at", skip=(page - 1) * page_size, limit=page_size)
    return {"items": [_meeting_row(a) for a in archives], "total": total, "page": page, "page_size": page_size}


@meetings_router.get("/api/meetings/{room_id}")
async def get_my_meeting(room_id: str, session: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    archive = await _meeting_for_user(room_id, session)
    repo = app_state.archive_repo
    db = repo.db
    recordings = await repo.list_recordings(room_id)
    participants = await db["room_participants"].find({"room_id": room_id}).to_list(length=500)
    counts = {
        name: await db["room_messages"].count_documents({"room_id": room_id, "kind": {"$in": kinds}})
        for name, kinds in MESSAGE_KINDS.items()
    }
    summary = None
    if app_state.room_history is not None:
        summary = await app_state.room_history.get_meeting_summary(room_id, summary_type="final")
    user_id = _user_id(session)
    return {
        "meeting": _meeting_row(archive),
        "recordings": [_user_recording(r) for r in recordings],
        "participants": [
            {
                "participant_id": p.get("participant_id"),
                "display_name": p.get("display_name"),
                "language": p.get("language"),
                "kind": p.get("kind", "human"),
                "joined_at": p.get("joined_at") or p.get("first_joined_at"),
                "left_at": p.get("left_at"),
                "is_you": bool(user_id and p.get("user_id") == user_id),
            }
            for p in participants
        ],
        "counts": counts,
        "summary": _jsonable(summary),
    }


@meetings_router.get("/api/meetings/{room_id}/messages")
async def get_my_meeting_messages(
    room_id: str,
    kind: str = Query("transcript", pattern="^(transcript|relay|chat)$"),
    page: int = Query(1, ge=1),
    session: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    await _meeting_for_user(room_id, session)
    db = app_state.archive_repo.db
    query = {"room_id": room_id, "kind": {"$in": MESSAGE_KINDS[kind]}}
    total = await db["room_messages"].count_documents(query)
    docs = (
        await db["room_messages"]
        .find(query)
        .sort("created_at", 1)
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


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items() if k != "_id" and not k.endswith("_dt")}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return iso(value)
    return value


async def _recording_for_user(recording_id: str, session: Dict[str, Any]) -> Dict[str, Any]:
    repo = app_state.archive_repo
    if repo is None or not repo.enabled:
        raise _error(503, "history_unavailable", "Meeting history is not available on this server.")
    doc = await repo.get_recording(recording_id)
    if doc is None:
        raise _error(404, "recording_not_found", "Recording not found.")
    await _meeting_for_user(doc["room_id"], session)
    return doc


@meetings_router.get("/api/recordings/{recording_id}")
async def get_recording(recording_id: str, session: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    return {"recording": _user_recording(await _recording_for_user(recording_id, session))}


async def _signed_url(recording_id: str, session: Dict[str, Any], *, download: bool, settings: Settings) -> Dict[str, Any]:
    doc = await _recording_for_user(recording_id, session)
    if doc["status"] != REC_READY:
        raise _error(409, "recording_not_ready", "The recording is still being prepared.")
    storage = app_state.archive_storage
    if storage is None:
        raise _error(503, "recording_unavailable", "Recording storage is not configured.")
    ttl = max(60, min(settings.recording_url_ttl_seconds, 3600))
    name = f"meetq-{doc['room_id']}-{doc['_id']}.mp4" if download else None
    url = storage.presigned_get_url(doc["s3_key"], expires_in=ttl, download_name=name)
    # The URL itself is a bearer credential: never logged, never stored.
    logger.info(
        "recording url issued room_id=%s recording_id=%s kind=%s ttl=%s",
        doc["room_id"],
        doc["_id"],
        "download" if download else "playback",
        ttl,
    )
    return {"url": url, "expires_in": ttl}


@meetings_router.post("/api/recordings/{recording_id}/playback-url")
async def recording_playback_url(
    recording_id: str,
    session: Dict[str, Any] = Depends(current_user),
    settings: Settings = Depends(get_auth_settings),
) -> Dict[str, Any]:
    return await _signed_url(recording_id, session, download=False, settings=settings)


@meetings_router.post("/api/recordings/{recording_id}/download-url")
async def recording_download_url(
    recording_id: str,
    session: Dict[str, Any] = Depends(current_user),
    settings: Settings = Depends(get_auth_settings),
) -> Dict[str, Any]:
    return await _signed_url(recording_id, session, download=True, settings=settings)
