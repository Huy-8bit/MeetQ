"""User-facing recording and meeting-history endpoints.

In-room (room token + signed-in user):
  POST /api/rooms/{room_id}/recordings                       start (idempotent)
  POST /api/rooms/{room_id}/recordings/{recording_id}/stop   stop  (idempotent)
  GET  /api/rooms/{room_id}/recordings/current               current room-level state

Recordings of a meeting in the user's history (rules in server/service/meetings):
  GET  /api/recordings/{recording_id}
  POST /api/recordings/{recording_id}/playback-url | download-url   (short-lived presigned URL)

Access is decided by the stable user ID recorded at join time (`room_participants.user_id`
and the archive's `participant_user_ids`), never by display name.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends

from server.config import Settings
from server.service.admin.errors import AdminApiError
from server.service.archive.recording_service import RecordingError
from server.service.archive.repository import REC_READY
from server.service.auth.dependencies import current_user, get_auth_settings, require_user
from server.service.gateway.app_state import app_state
from server.service.gateway.dependencies import verify_token_dependency
from server.service.gateway.room_permissions import Permission, RoomPermissionError
from server.service.meetings.api import meeting_access, user_recording

logger = logging.getLogger(__name__)

recordings_router = APIRouter(tags=["recordings"])


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


async def _require_recording_control(room_id: str, participant_id: str) -> None:
    """Start/stop recording: host and co-hosts only (resolved from the user's membership)."""
    try:
        await app_state.room_service.require_room_permission(room_id, participant_id, Permission.MANAGE_RECORDING)
    except RoomPermissionError as exc:
        raise _error(403, exc.code, str(exc))


@recordings_router.post("/api/rooms/{room_id}/recordings")
async def start_recording(
    room_id: str,
    claims: Dict[str, Any] = Depends(verify_token_dependency),
    session: Optional[Dict[str, Any]] = Depends(require_user),
) -> Dict[str, Any]:
    recordings, _archives, _repo = _services()
    participant = await _room_participant(room_id, claims)
    await _require_recording_control(room_id, participant.participant_id)
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
    app_state.room_service._audit("recording_started", room_id, actor=participant.participant_id)
    if _repo.enabled:
        # Lets My meetings filter "Recorded" without joining collections per row.
        await _repo.db["rooms"].update_one({"room_id": room_id}, {"$set": {"has_recording": True}})
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
    await _require_recording_control(room_id, participant.participant_id)
    try:
        state = await recordings.stop(
            room_id,
            recording_id,
            reason="user_stopped",
            stopped_by_name=participant.display_name,
        )
    except RecordingError as exc:
        raise _error(exc.status_code, exc.code, exc.message)
    app_state.room_service._audit("recording_stopped", room_id, actor=participant.participant_id)
    return {"recording": state}


@recordings_router.get("/api/rooms/{room_id}/recordings/current")
async def current_recording(
    room_id: str,
    claims: Dict[str, Any] = Depends(verify_token_dependency),
    session: Optional[Dict[str, Any]] = Depends(require_user),
) -> Dict[str, Any]:
    recordings, _archives, _repo = _services()
    return {"recording": await recordings.current(room_id), "available": recordings.available}


# ── Recording playback (access via meeting history rules) ───────────────────


async def _recording_for_user(recording_id: str, session: Dict[str, Any]) -> Dict[str, Any]:
    repo = app_state.archive_repo
    if repo is None or not repo.enabled:
        raise _error(503, "history_unavailable", "Meeting history is not available on this server.")
    doc = await repo.get_recording(recording_id)
    if doc is None:
        raise _error(404, "recording_not_found", "Recording not found.")
    # Same rules as the meeting itself: a member (by user ID), within retention.
    await meeting_access(doc["room_id"], session)
    return doc


@recordings_router.get("/api/recordings/{recording_id}")
async def get_recording(recording_id: str, session: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    return {"recording": user_recording(await _recording_for_user(recording_id, session))}


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


@recordings_router.post("/api/recordings/{recording_id}/playback-url")
async def recording_playback_url(
    recording_id: str,
    session: Dict[str, Any] = Depends(current_user),
    settings: Settings = Depends(get_auth_settings),
) -> Dict[str, Any]:
    return await _signed_url(recording_id, session, download=False, settings=settings)


@recordings_router.post("/api/recordings/{recording_id}/download-url")
async def recording_download_url(
    recording_id: str,
    session: Dict[str, Any] = Depends(current_user),
    settings: Settings = Depends(get_auth_settings),
) -> Dict[str, Any]:
    return await _signed_url(recording_id, session, download=True, settings=settings)
