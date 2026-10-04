"""Optional meeting-room passwords.

The password is hashed with Argon2id when the room is created and the hash is kept
in its own Redis key (`room:{id}:access`) next to the room meta, with the same TTL.
It never goes into RoomState, room snapshots, events, MongoDB or logs; the rest of
the system only sees `password_required`.

Failed join attempts are counted per (room, client address) and per (room, user);
either counter over the limit blocks further attempts for the window.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

logger = logging.getLogger(__name__)

ROOM_PASSWORD_MIN_LENGTH = 6
ROOM_PASSWORD_MAX_LENGTH = 128
ROOM_PASSWORD_MAX_FAILURES = 10
ROOM_PASSWORD_FAILURE_WINDOW_SECONDS = 600

# OWASP baseline for Argon2id: m=19 MiB, t=2, p=1.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16)


class RoomPasswordRequiredError(Exception):
    pass


class InvalidRoomPasswordError(Exception):
    pass


class RoomPasswordRateLimitedError(Exception):
    def __init__(self, retry_after_seconds: int):
        super().__init__("too many incorrect room passwords")
        self.retry_after_seconds = retry_after_seconds


def validate_room_password(password: str) -> None:
    """Length only (6–128 characters); no composition rules."""
    if not isinstance(password, str):
        raise ValueError("password must be a string")
    if len(password) < ROOM_PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {ROOM_PASSWORD_MIN_LENGTH} characters.")
    if len(password) > ROOM_PASSWORD_MAX_LENGTH:
        raise ValueError(f"Password must be at most {ROOM_PASSWORD_MAX_LENGTH} characters.")


def hash_room_password(password: str) -> str:
    validate_room_password(password)
    return _hasher.hash(password)


def verify_room_password(password: str, encoded: str) -> bool:
    if not password or len(password) > ROOM_PASSWORD_MAX_LENGTH or not encoded:
        return False
    try:
        return _hasher.verify(encoded, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


class RoomAccessStore:
    """Redis storage for room password hashes and failed-attempt counters."""

    def __init__(
        self,
        client: Any,
        ttl_seconds: int,
        *,
        max_failures: int = ROOM_PASSWORD_MAX_FAILURES,
        failure_window_seconds: int = ROOM_PASSWORD_FAILURE_WINDOW_SECONDS,
    ) -> None:
        self.client = client
        self.ttl = ttl_seconds
        self.max_failures = max_failures
        self.failure_window_seconds = failure_window_seconds

    @staticmethod
    def access_key(room_id: str) -> str:
        return f"room:{room_id}:access"

    def _failure_keys(self, room_id: str, client_ip: Optional[str], user_id: Optional[str]) -> list:
        keys = [f"room:{room_id}:pwfail:ip:{client_ip or 'unknown'}"]
        if user_id:
            keys.append(f"room:{room_id}:pwfail:user:{user_id}")
        return keys

    async def set_password(self, room_id: str, password: str) -> None:
        # Hashing is deliberately slow; keep it off the event loop.
        encoded = await asyncio.to_thread(hash_room_password, password)
        await self.client.set(self.access_key(room_id), json.dumps({"password_hash": encoded}), ex=self.ttl)

    async def _password_hash(self, room_id: str) -> Optional[str]:
        raw = await self.client.get(self.access_key(room_id))
        if not raw:
            return None
        try:
            return json.loads(raw).get("password_hash")
        except (TypeError, ValueError):
            return None

    async def check_join(
        self,
        room_id: str,
        password: Optional[str],
        *,
        client_ip: Optional[str],
        user_id: Optional[str],
    ) -> None:
        """Raise unless the password matches. Call only for rooms with password_required."""
        keys = self._failure_keys(room_id, client_ip, user_id)
        for key in keys:
            raw = await self.client.get(key)
            if raw is not None and int(raw) >= self.max_failures:
                raise RoomPasswordRateLimitedError(self.failure_window_seconds)

        if not password:
            raise RoomPasswordRequiredError()

        encoded = await self._password_hash(room_id)
        ok = bool(encoded) and await asyncio.to_thread(verify_room_password, password, encoded)
        if ok:
            if user_id:
                await self.client.delete(keys[-1])
            return

        for key in keys:
            count = await self.client.incr(key)
            if int(count) == 1:
                await self.client.expire(key, self.failure_window_seconds)
        logger.info("room password rejected: room_id=%s", room_id)
        raise InvalidRoomPasswordError()

    async def delete(self, room_id: str) -> None:
        await self.client.delete(self.access_key(room_id))
