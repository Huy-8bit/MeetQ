from __future__ import annotations

from server.service.admin.errors import AdminApiError


class AuthApiError(AdminApiError):
    """Auth failures, rendered with the standard ``{"error": {...}}`` envelope."""


def auth_required() -> AuthApiError:
    return AuthApiError(401, "auth_required", "Sign in required.")


def session_expired() -> AuthApiError:
    return AuthApiError(401, "session_expired", "Your session has ended. Sign in again.")


def admin_auth_required() -> AuthApiError:
    return AuthApiError(401, "admin_auth_required", "Admin sign-in required.")


def admin_session_expired() -> AuthApiError:
    return AuthApiError(401, "admin_session_expired", "Admin session expired.")
