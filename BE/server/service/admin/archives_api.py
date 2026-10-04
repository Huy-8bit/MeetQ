"""Admin: meeting archives, recordings and retention (/api/admin, admin cookie session).

  GET    /api/admin/recordings                      archive list (filters: ready, processing,
                                                    failed, expiring_soon, expired)
  GET    /api/admin/archives/{archive_id}           detail: segments, files, retention
  GET    /api/admin/settings/retention              system default retention
  PATCH  /api/admin/settings/retention              {default_retention_days}
  PATCH  /api/admin/archives/{archive_id}/retention {retention_days | use_default, confirm_expire}
  DELETE /api/admin/archives/{archive_id}           {confirm: "DELETE"}

Admins can view and delete archives and change retention; they cannot start a
recording (recording is only started from inside a meeting, visibly).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from server.service.admin.dependencies import require_admin
from server.service.admin.errors import AdminApiError
from server.service.archive.archive_service import ArchiveError, recording_summary
from server.service.archive.recording_service import public_recording
from server.service.archive.repository import (
    ARCHIVE_DELETED,
    ARCHIVE_FAILED,
    ARCHIVE_FINALIZING,
    ARCHIVE_OPEN,
    ARCHIVE_PROCESSING_RECORDING,
)
from server.service.archive.retention import (
    InvalidRetentionError,
    as_utc,
    compute_expires_at,
    effective_retention_days,
    iso,
    utcnow,
    validate_retention_days,
)
from server.service.gateway.app_state import app_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-archives"], dependencies=[Depends(require_admin)])

EXPIRING_SOON = timedelta(hours=48)
FILTERS = "^(all|ready|processing|failed|expiring_soon|expired)$"


class RetentionSettingsUpdate(BaseModel):
    default_retention_days: int


class ArchiveRetentionUpdate(BaseModel):
    retention_days: Optional[int] = None
    use_default: bool = False
    confirm_expire: bool = False


class ArchiveDeleteRequest(BaseModel):
    confirm: str = Field(..., description='Must be "DELETE".')


def _repo():
    repo = app_state.archive_repo
    if repo is None or not repo.enabled:
        raise AdminApiError(503, "history_unavailable", "Meeting history storage (MongoDB) is not configured or not reachable.")
    return repo


def _admin_name(session: Dict[str, Any]) -> str:
    return ((session.get("admin") or {}).get("username")) or "admin"


def _row(archive: Dict[str, Any]) -> Dict[str, Any]:
    summary = archive.get("recording_summary") or recording_summary([])
    return {
        "archive_id": archive["_id"],
        "room_id": archive["room_id"],
        "status": archive["status"],
        "storage": archive.get("storage"),
        "room_languages": archive.get("room_languages") or [],
        "meeting_started_at": iso(archive.get("meeting_started_at")),
        "ended_at": iso(archive.get("ended_at")),
        "participant_count": archive.get("participant_count"),
        "recording": summary,
        "retention_days": effective_retention_days(archive),
        "retention_source": "custom" if archive.get("retention_override_days") else "default",
        "default_retention_days_snapshot": archive.get("default_retention_days_snapshot"),
        "retention_override_days": archive.get("retention_override_days"),
        "expires_at": iso(archive.get("expires_at")),
        "created_at": iso(archive.get("created_at")),
        "finalized_at": iso(archive.get("finalized_at")),
        "deleted_at": iso(archive.get("deleted_at")),
        "deletion_reason": archive.get("deletion_reason"),
        "error_code": archive.get("error_code"),
    }


def _filter_query(name: str) -> Dict[str, Any]:
    now = utcnow()
    if name == "ready":
        return {"status": {"$ne": ARCHIVE_DELETED}, "recording_summary.status": "ready"}
    if name == "processing":
        return {
            "$or": [
                {"status": {"$in": [ARCHIVE_FINALIZING, ARCHIVE_PROCESSING_RECORDING]}},
                {"status": {"$ne": ARCHIVE_DELETED}, "recording_summary.status": "processing"},
            ]
        }
    if name == "failed":
        return {
            "$or": [
                {"status": ARCHIVE_FAILED},
                {"status": {"$ne": ARCHIVE_DELETED}, "recording_summary.status": {"$in": ["failed", "partial"]}},
            ]
        }
    if name == "expiring_soon":
        return {"status": {"$nin": [ARCHIVE_DELETED, ARCHIVE_OPEN]}, "expires_at": {"$gt": now, "$lte": now + EXPIRING_SOON}}
    if name == "expired":
        return {"$or": [{"status": ARCHIVE_DELETED}, {"expires_at": {"$lte": now}}]}
    return {"status": {"$ne": ARCHIVE_DELETED}}


@router.get("/recordings")
async def list_archives(
    filter: str = Query("all", pattern=FILTERS),
    q: Optional[str] = Query(None, max_length=80),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> Dict[str, Any]:
    repo = _repo()
    query = _filter_query(filter)
    if q:
        query = {"$and": [query, {"room_id": {"$regex": q.strip(), "$options": "i"}}]}
    total = await repo.count_archives(query)
    archives = await repo.list_archives(query, sort="created_at", skip=(page - 1) * page_size, limit=page_size)
    settings = await repo.get_retention_settings()
    return {
        "items": [_row(a) for a in archives],
        "total": total,
        "page": page,
        "page_size": page_size,
        "default_retention_days": settings["default_retention_days"],
        "storage_configured": app_state.archive_storage is not None,
        "recording_available": bool(getattr(app_state.recording_service, "available", False)),
    }


async def _archive_or_404(archive_id: str) -> Dict[str, Any]:
    archive = await _repo().get_archive(archive_id)
    if archive is None:
        raise AdminApiError(404, "archive_not_found", f"Archive {archive_id} was not found.")
    return archive


@router.get("/archives/{archive_id}")
async def get_archive(archive_id: str) -> Dict[str, Any]:
    repo = _repo()
    archive = await _archive_or_404(archive_id)
    recordings = await repo.list_recordings(archive["room_id"])
    settings = await repo.get_retention_settings()
    files = archive.get("files") or {}
    return {
        "archive": _row(archive),
        "recordings": [
            {
                **(public_recording(r) or {}),
                "s3_key": r.get("s3_key"),
                "provider_recording_id": r.get("provider_recording_id"),
                "stop_reason": r.get("stop_reason"),
                "error_code": r.get("error_code"),
            }
            for r in recordings
        ],
        "files": [{"name": name, "key": info.get("key"), "size": info.get("size")} for name, info in files.items()],
        "s3_bucket": archive.get("s3_bucket"),
        "s3_prefix": archive.get("s3_prefix"),
        "system_default_retention_days": settings["default_retention_days"],
        "storage_bytes": sum(int(f.get("size") or 0) for f in files.values())
        + int((archive.get("recording_summary") or {}).get("total_bytes") or 0),
    }


@router.get("/settings/retention")
async def get_retention_settings() -> Dict[str, Any]:
    settings = await _repo().get_retention_settings()
    return {**settings, "updated_at": iso(settings.get("updated_at"))}


@router.patch("/settings/retention")
async def update_retention_settings(
    body: RetentionSettingsUpdate,
    session: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    try:
        settings = await _repo().set_default_retention_days(body.default_retention_days, updated_by=_admin_name(session))
    except InvalidRetentionError as exc:
        raise AdminApiError(422, "invalid_retention", str(exc))
    logger.info("default meeting retention changed days=%s by=%s", settings["default_retention_days"], _admin_name(session))
    return {**settings, "updated_at": iso(settings.get("updated_at"))}


@router.patch("/archives/{archive_id}/retention")
async def update_archive_retention(
    archive_id: str,
    body: ArchiveRetentionUpdate,
    session: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    repo = _repo()
    archive = await _archive_or_404(archive_id)
    if archive["status"] == ARCHIVE_DELETED:
        raise AdminApiError(410, "archive_deleted", "This archive has already been deleted.")
    override: Optional[int]
    if body.use_default:
        # "Use default" = the system default captured when this archive was created,
        # so changing the global setting later never moves this archive's expiry.
        override = None
    else:
        if body.retention_days is None:
            raise AdminApiError(422, "invalid_retention", "retention_days is required unless use_default is true.")
        try:
            override = validate_retention_days(body.retention_days)
        except InvalidRetentionError as exc:
            raise AdminApiError(422, "invalid_retention", str(exc))
    candidate = {**archive, "retention_override_days": override}
    new_expiry = compute_expires_at(candidate) if archive.get("ended_at") else None
    if new_expiry is not None and new_expiry <= utcnow() and not body.confirm_expire:
        raise AdminApiError(
            409,
            "retention_expires_immediately",
            "This meeting is already older than the new retention period. Applying it deletes the archive.",
            {"expires_at": iso(new_expiry)},
        )
    updated = await repo.set_retention(archive, override)
    logger.info(
        "archive retention changed archive_id=%s room_id=%s days=%s by=%s",
        archive_id,
        archive["room_id"],
        effective_retention_days(updated),
        _admin_name(session),
    )
    if new_expiry is not None and new_expiry <= utcnow() and app_state.archive_service is not None:
        asyncio.create_task(app_state.archive_service.cleanup_expired())
    return {"archive": _row(updated)}


@router.delete("/archives/{archive_id}")
async def delete_archive(
    archive_id: str,
    body: ArchiveDeleteRequest,
    session: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    if body.confirm != "DELETE":
        raise AdminApiError(422, "confirmation_required", 'Type DELETE to confirm.')
    archive = await _archive_or_404(archive_id)
    if archive["status"] == ARCHIVE_OPEN:
        raise AdminApiError(409, "meeting_in_progress", "The meeting has not ended yet.")
    try:
        deleted = await app_state.archive_service.delete_archive(archive, reason="admin_deleted", actor=_admin_name(session))
    except ArchiveError as exc:
        raise AdminApiError(exc.status_code, exc.code, exc.message, exc.details)
    return {"archive": _row(deleted)}
