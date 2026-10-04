from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import Depends, Request

from server.config import Settings
from server.service.auth.dependencies import admin_enabled, current_admin
from server.service.admin.errors import AdminApiError
from server.service.admin.history_service import AdminHistoryService
from server.service.admin.live_service import AdminLiveService
from server.service.admin.livekit_inspector import LiveKitInspector
from server.service.gateway.app_state import app_state

@dataclass
class AdminContext:
    settings: Settings
    redis: Any
    live: AdminLiveService
    history: AdminHistoryService
    inspector: Optional[LiveKitInspector]


def build_admin_context(*, inspector: Optional[LiveKitInspector] = None) -> AdminContext:
    settings = app_state.settings
    if settings is None or app_state.redis is None:
        raise AdminApiError(503, "service_unavailable", "Gateway is not initialized.")
    db = getattr(app_state.room_history, "db", None) if app_state.room_history else None
    return AdminContext(
        settings=settings,
        redis=app_state.redis,
        live=AdminLiveService(app_state.redis, settings, inspector),
        history=AdminHistoryService(db, room_service=app_state.room_service),
        inspector=inspector,
    )


def get_admin_context() -> AdminContext:
    context = getattr(app_state, "admin_context", None)
    if context is None:
        context = build_admin_context()
        app_state.admin_context = context
    return context


def get_admin_settings() -> Settings:
    if app_state.settings is None:
        raise AdminApiError(503, "service_unavailable", "Gateway is not initialized.")
    if not admin_enabled(app_state.settings):
        raise AdminApiError(
            503,
            "admin_disabled",
            "Admin portal is disabled. Set ADMIN_USERNAME and ADMIN_PASSWORD_HASH to enable it.",
        )
    return app_state.settings


async def require_admin(
    request: Request,
    settings: Settings = Depends(get_admin_settings),
) -> Dict[str, Any]:
    """Admin cookie session (see server/service/auth); independent from user sign-in."""
    return await current_admin(request, settings)
