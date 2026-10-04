from fastapi import APIRouter, Depends

from server.config import Settings
from server.meeting_modes import SUPPORTED_MEETING_LANGUAGES
from server.service.gateway.app_state import app_state
from server.service.gateway.dependencies import get_settings

router = APIRouter()


@router.get("/api/config")
async def public_config(settings: Settings = Depends(get_settings)) -> dict:
    """Non-sensitive runtime configuration the user-facing app needs to display."""
    return {
        "room_meeting_duration_seconds": settings.room_meeting_duration_seconds,
        "supported_languages": list(SUPPORTED_MEETING_LANGUAGES),
        "recording_available": bool(getattr(app_state.recording_service, "available", False)),
        "meeting_history_available": bool(getattr(app_state.archive_repo, "enabled", False)),
    }
