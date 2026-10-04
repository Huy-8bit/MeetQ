from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, Request

from server.config import Settings
from server.service.auth.cookies import ADMIN_COOKIE, USER_COOKIE
from server.service.auth.errors import (
    AuthApiError,
    admin_auth_required,
    admin_session_expired,
    auth_required,
    session_expired,
)
from server.service.auth.sessions import ADMIN_REALM, USER_REALM, SessionStore
from server.service.gateway.app_state import app_state


def get_auth_settings() -> Settings:
    if app_state.settings is None or app_state.redis is None:
        raise AuthApiError(503, "service_unavailable", "Gateway is not initialized.")
    return app_state.settings


def get_session_store() -> SessionStore:
    return SessionStore(app_state.redis)


def admin_enabled(settings: Settings) -> bool:
    username = (settings.admin_username or "").strip()
    secret = (settings.admin_password_hash or settings.admin_password or "").strip()
    return bool(username and secret)


async def current_user(
    request: Request,
    settings: Settings = Depends(get_auth_settings),
) -> Dict[str, Any]:
    """The signed-in user (from the meetq_session cookie) or 401."""
    token = request.cookies.get(USER_COOKIE)
    if not token:
        raise auth_required()
    session = await get_session_store().get(USER_REALM, token)
    if session is None:
        raise session_expired()
    return session


async def require_user(
    request: Request,
    settings: Settings = Depends(get_auth_settings),
) -> Optional[Dict[str, Any]]:
    """Guards user-realm endpoints (rooms, device tests) when USER_AUTH_REQUIRED is on."""
    if not settings.user_auth_required:
        return None
    return await current_user(request, settings)


async def current_admin(
    request: Request,
    settings: Settings = Depends(get_auth_settings),
) -> Dict[str, Any]:
    """The signed-in operator (from the meetq_admin_session cookie) or 401/503."""
    if not admin_enabled(settings):
        raise AuthApiError(503, "admin_disabled", "Admin portal is disabled. Set ADMIN_USERNAME and ADMIN_PASSWORD_HASH.")
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        raise admin_auth_required()
    session = await get_session_store().get(ADMIN_REALM, token)
    if session is None:
        raise admin_session_expired()
    return session
