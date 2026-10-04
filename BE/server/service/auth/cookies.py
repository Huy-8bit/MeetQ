"""Session cookies. Both are HttpOnly and host-only on the API origin."""
from __future__ import annotations

from fastapi import Response

from server.config import Settings

USER_COOKIE = "meetq_session"
ADMIN_COOKIE = "meetq_admin_session"
# The admin cookie is only sent to admin endpoints.
ADMIN_COOKIE_PATH = "/api/admin"


def set_user_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        USER_COOKIE,
        token,
        max_age=settings.user_session_ttl_seconds,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_user_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(USER_COOKIE, path="/", secure=settings.auth_cookie_secure, httponly=True, samesite="lax")


def set_admin_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        ADMIN_COOKIE,
        token,
        max_age=settings.admin_session_ttl_seconds,
        path=ADMIN_COOKIE_PATH,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_admin_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        ADMIN_COOKIE,
        path=ADMIN_COOKIE_PATH,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="strict",
    )
