"""Opaque server-side sessions in Redis.

The browser holds a random token in an HttpOnly cookie; Redis stores only its
SHA-256, so a Redis dump cannot be replayed as a session. Each realm (user,
admin) has its own key space and cookie, so they never authorize each other.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

USER_REALM = "user"
ADMIN_REALM = "admin"
_KEY_PREFIX = "brseai:v1:auth"


def _key(realm: str, token: str) -> str:
    digest = hashlib.sha256(token.encode()).hexdigest()
    return f"{_KEY_PREFIX}:{realm}:session:{digest}"


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class SessionStore:
    def __init__(self, redis: Any) -> None:
        self.redis = redis

    async def create(self, realm: str, data: Dict[str, Any], ttl_seconds: int) -> tuple[str, Dict[str, Any]]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        session = {
            **data,
            "realm": realm,
            "created_at": iso(now),
            "expires_at": iso(now + timedelta(seconds=ttl_seconds)),
        }
        await self.redis.set(_key(realm, token), json.dumps(session), ex=ttl_seconds)
        return token, session

    async def get(self, realm: str, token: Optional[str]) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        raw = await self.redis.get(_key(realm, token))
        if not raw:
            return None
        try:
            session = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if session.get("realm") != realm:
            return None
        return session

    async def delete(self, realm: str, token: Optional[str]) -> None:
        if token:
            await self.redis.delete(_key(realm, token))
