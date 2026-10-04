"""Frontend origins trusted for credentialed requests (CORS + CSRF origin check)."""
from __future__ import annotations

import os

_DEFAULT_CORS_ALLOWED_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def cors_allowed_origins() -> list[str]:
    """Exact frontend origins allowed to call the API with cookies.

    Credentialed requests (session cookies) cannot use "*": browsers reject it.
    Set CORS_ALLOWED_ORIGINS to a comma-separated list, e.g.
    "https://meetq.example.com,https://dev.meetq.example.com".
    """
    raw = os.getenv("CORS_ALLOWED_ORIGINS") or _DEFAULT_CORS_ALLOWED_ORIGINS
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    return [origin for origin in origins if origin != "*"]


def origin_is_trusted(origin: str | None, allowed: list[str]) -> bool:
    """CSRF check for unsafe methods. Browsers send Origin on every cross-origin
    POST/PATCH/DELETE, so a request without one is not a cross-site browser
    request (curl, server-to-server) and is allowed; SameSite cookies add a
    second layer."""
    if origin is None:
        return True
    return origin.rstrip("/") in allowed
