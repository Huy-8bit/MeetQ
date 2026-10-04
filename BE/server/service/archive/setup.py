"""Builds the recording/archive services for the gateway (see gateway/main.py lifespan)."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from server.config import Settings
from server.events import build_envelope
from server.service.archive.archive_service import ArchiveService
from server.service.archive.egress import LiveKitEgressProvider
from server.service.archive.recording_service import RecordingService
from server.service.archive.repository import ArchiveRepository
from server.service.archive.storage import ArchiveStorage, storage_configured
from server.service.archive.worker import ArchiveWorker
from server.service.gateway.app_state import app_state
from server.service.gateway.room_store import RoomStore
from server.meeting_modes import active_human_participant_count

logger = logging.getLogger(__name__)


def _snapshot_expired(snapshot: Any) -> bool:
    from datetime import datetime, timezone

    expires_at = getattr(snapshot.room, "expires_at", None)
    if not expires_at:
        return False
    try:
        return datetime.now(timezone.utc) >= datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return False


def room_checks(store: RoomStore):
    async def room_ended(room_id: str) -> bool:
        """The meeting is over: room gone, expired, or no real participant left."""
        snapshot = await store.get_room_snapshot(room_id)
        if snapshot is None or _snapshot_expired(snapshot):
            return True
        return getattr(snapshot.room, "state", None) == "empty" and active_human_participant_count(snapshot.participants) == 0

    async def room_is_live(room_id: str) -> bool:
        snapshot = await store.get_room_snapshot(room_id)
        if snapshot is None or _snapshot_expired(snapshot):
            return False
        return active_human_participant_count(snapshot.participants) > 0

    return room_ended, room_is_live


def build_archive_services(
    settings: Settings,
    *,
    redis: Any,
    mongo_db: Any,
    store: RoomStore,
    ops_recorder: Optional[Any] = None,
    storage: Optional[ArchiveStorage] = None,
    provider: Optional[Any] = None,
) -> Dict[str, Any]:
    repo = ArchiveRepository(mongo_db, default_retention_days=settings.default_meeting_retention_days)
    if storage is None and storage_configured(settings):
        storage = ArchiveStorage(settings)
    if provider is None and storage is not None and settings.meeting_recording_enabled:
        provider = LiveKitEgressProvider(settings)
    room_ended, room_is_live = room_checks(store)

    async def publish(event_type: str, room_id: str, payload: Dict[str, Any]) -> None:
        envelope = build_envelope(event_type, room_id, payload)
        await redis.publish(settings.redis_channel_gateway_control, json.dumps(envelope, default=str))

    async def report_error(room_id: str, code: str, detail: str, details: Dict[str, Any]) -> None:
        if ops_recorder is not None:
            await ops_recorder.record_ai_error(
                room_id,
                {"code": code, "message": detail, "details": details},
                source="gateway",
            )

    archives = ArchiveService(settings, repo, storage, room_is_live=room_is_live, report_error=report_error)
    recordings = RecordingService(
        settings,
        repo,
        storage,
        provider,
        redis,
        publish=publish,
        room_ended=room_ended,
        on_recording_changed=archives.refresh_recordings,
        report_error=report_error,
    )
    worker = ArchiveWorker(
        redis,
        recordings,
        archives,
        recording_interval=settings.recording_poll_interval_seconds,
        archive_interval=settings.archive_poll_interval_seconds,
        cleanup_interval=settings.archive_cleanup_interval_seconds,
    )
    if not repo.enabled:
        logger.warning("meeting archive disabled: MongoDB is not configured")
    elif storage is None:
        logger.warning("meeting archive bucket not configured: archives stay in MongoDB, recording is off")
    return {"repo": repo, "storage": storage, "recordings": recordings, "archives": archives, "worker": worker}


def install(services: Dict[str, Any]) -> None:
    app_state.archive_repo = services["repo"]
    app_state.archive_storage = services["storage"]
    app_state.recording_service = services["recordings"]
    app_state.archive_service = services["archives"]
    app_state.archive_worker = services["worker"]
