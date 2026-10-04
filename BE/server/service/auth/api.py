"""Sign-in endpoints (docs/auth-backend-contract.md).

User realm  — /api/auth/*        Google ID token → meetq_session cookie
Admin realm — /api/admin/auth/*  username + password → meetq_admin_session cookie
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from server.config import Settings
from server.service.admin.auth import LoginRateLimiter
from server.service.auth.cookies import (
    ADMIN_COOKIE,
    USER_COOKIE,
    clear_admin_cookie,
    clear_user_cookie,
    set_admin_cookie,
    set_user_cookie,
)
from server.service.auth.dependencies import (
    admin_enabled,
    current_admin,
    current_user,
    get_auth_settings,
    get_session_store,
)
from server.service.auth.errors import AuthApiError
from server.service.auth.google import (
    GoogleAccountNotAllowedError,
    GoogleIdentity,
    GoogleIdTokenVerifier,
    GoogleTokenError,
)
from server.service.auth.passwords import verify_password
from server.service.auth.sessions import ADMIN_REALM, USER_REALM
from server.service.gateway.app_state import app_state

logger = logging.getLogger(__name__)

user_router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_auth_router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])

google_failures = LoginRateLimiter(max_failures=20, window_seconds=600)
admin_failures = LoginRateLimiter(max_failures=10, window_seconds=600)
_FAILED_LOGIN_DELAY_SECONDS = 0.4


class GoogleSignInRequest(BaseModel):
    credential: str = Field(..., min_length=1, max_length=8192)


class AdminSignInRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=512)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _user_id(subject: str) -> str:
    # Stable per Google account (`sub` never changes; email can).
    return "usr_" + hashlib.sha256(f"google:{subject}".encode()).hexdigest()[:20]


def _user_payload(identity: GoogleIdentity) -> Dict[str, Any]:
    return {
        "id": _user_id(identity.subject),
        "email": identity.email,
        "name": identity.name,
        "avatar_url": identity.picture,
    }


@lru_cache(maxsize=4)
def _verifier(client_id: str, allowed_domains: str) -> GoogleIdTokenVerifier:
    return GoogleIdTokenVerifier(client_id, allowed_domains=allowed_domains.split(","))


def get_google_verifier(settings: Settings = Depends(get_auth_settings)) -> GoogleIdTokenVerifier:
    client_id = (settings.google_client_id or "").strip()
    if not client_id:
        raise AuthApiError(503, "auth_unavailable", "Google sign-in is not configured on this server (GOOGLE_CLIENT_ID).")
    return _verifier(client_id, settings.google_allowed_domains or "")


async def _remember_user(identity: GoogleIdentity, user: Dict[str, Any]) -> None:
    """Upsert the account in MongoDB when history storage is available (best effort)."""
    db = getattr(app_state.room_history, "db", None) if app_state.room_history else None
    if db is None:
        return
    now = datetime.now(timezone.utc)
    try:
        await db["users"].update_one(
            {"_id": user["id"]},
            {
                "$set": {
                    "google_sub": identity.subject,
                    "email": identity.email,
                    "name": identity.name,
                    "avatar_url": identity.picture,
                    "hosted_domain": identity.hosted_domain,
                    "last_login_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
    except Exception:
        logger.warning("could not store user profile user=%s", user["id"], exc_info=True)


# ── User realm ──────────────────────────────────────────────────────────────


@user_router.post("/google")
async def sign_in_with_google(
    body: GoogleSignInRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_auth_settings),
    verifier: GoogleIdTokenVerifier = Depends(get_google_verifier),
) -> Dict[str, Any]:
    client_key = _client_key(request)
    if google_failures.is_blocked(client_key):
        raise AuthApiError(429, "too_many_attempts", "Too many sign-in attempts. Try again later.")
    try:
        identity = await verifier.verify(body.credential)
    except GoogleTokenError as exc:
        google_failures.record_failure(client_key)
        # Never log the credential itself.
        logger.warning("google sign-in rejected client=%s reason=%s", client_key, exc.reason)
        raise AuthApiError(401, "invalid_google_credential", "Google sign-in could not be verified.")
    except GoogleAccountNotAllowedError:
        raise AuthApiError(403, "account_not_allowed", "This Google account isn't allowed to use MeetQ.")
    except Exception:
        logger.exception("google sign-in verification failed client=%s", client_key)
        raise AuthApiError(503, "auth_unavailable", "Google sign-in is temporarily unavailable.")

    user = _user_payload(identity)
    store = get_session_store()
    # A fresh session ID on every sign-in (no session fixation).
    await store.delete(USER_REALM, request.cookies.get(USER_COOKIE))
    token, _session = await store.create(USER_REALM, {"user": user}, settings.user_session_ttl_seconds)
    set_user_cookie(response, settings, token)
    await _remember_user(identity, user)
    logger.info("user signed in user=%s", user["id"])
    return {"user": user}


@user_router.get("/me")
async def get_me(session: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    return {"user": session["user"]}


@user_router.post("/logout", status_code=204)
async def sign_out(request: Request, settings: Settings = Depends(get_auth_settings)) -> Response:
    await get_session_store().delete(USER_REALM, request.cookies.get(USER_COOKIE))
    response = Response(status_code=204)
    clear_user_cookie(response, settings)
    return response


# ── Admin realm ─────────────────────────────────────────────────────────────


def _admin_identity(settings: Settings) -> Dict[str, Any]:
    username = (settings.admin_username or "").strip()
    return {
        "id": "adm_" + hashlib.sha256(f"admin:{username}".encode()).hexdigest()[:12],
        "username": username,
        "display_name": username,
    }


def _check_admin_credentials(settings: Settings, username: str, password: str) -> bool:
    expected_user = (settings.admin_username or "").strip()
    user_ok = hmac.compare_digest(expected_user.encode(), username.strip().encode())
    if settings.admin_password_hash:
        password_ok = verify_password(password, settings.admin_password_hash)
    else:
        password_ok = hmac.compare_digest((settings.admin_password or "").strip().encode(), password.encode())
    return user_ok and password_ok


def _admin_response(session: Dict[str, Any]) -> Dict[str, Any]:
    return {"admin": session["admin"], "expires_at": session.get("expires_at")}


@admin_auth_router.post("/login")
async def admin_sign_in(
    body: AdminSignInRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_auth_settings),
) -> Dict[str, Any]:
    if not admin_enabled(settings):
        raise AuthApiError(503, "admin_disabled", "Admin portal is disabled.")
    keys = [f"ip:{_client_key(request)}", f"user:{body.username.strip().lower()}"]
    if any(admin_failures.is_blocked(key) for key in keys):
        raise AuthApiError(429, "too_many_attempts", "Too many failed sign-in attempts. Try again later.")
    if not _check_admin_credentials(settings, body.username, body.password):
        for key in keys:
            admin_failures.record_failure(key)
        # Never log the password or the submitted username.
        logger.warning("admin sign-in failed client=%s", _client_key(request))
        await asyncio.sleep(_FAILED_LOGIN_DELAY_SECONDS)
        raise AuthApiError(401, "invalid_credentials", "Incorrect username or password.")
    for key in keys:
        admin_failures.reset(key)

    store = get_session_store()
    await store.delete(ADMIN_REALM, request.cookies.get(ADMIN_COOKIE))
    token, session = await store.create(
        ADMIN_REALM,
        {"admin": _admin_identity(settings)},
        settings.admin_session_ttl_seconds,
    )
    set_admin_cookie(response, settings, token)
    logger.info("admin signed in client=%s", _client_key(request))
    return _admin_response(session)


@admin_auth_router.get("/me")
async def admin_me(session: Dict[str, Any] = Depends(current_admin)) -> Dict[str, Any]:
    return _admin_response(session)


@admin_auth_router.post("/logout", status_code=204)
async def admin_sign_out(request: Request, settings: Settings = Depends(get_auth_settings)) -> Response:
    await get_session_store().delete(ADMIN_REALM, request.cookies.get(ADMIN_COOKIE))
    response = Response(status_code=204)
    clear_admin_cookie(response, settings)
    return response
