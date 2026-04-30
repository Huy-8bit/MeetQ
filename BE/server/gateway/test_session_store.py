from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from redis.asyncio import Redis

from server.models import MicTestSession, TranslationTestSession

_TEST_SESSION_TTL = 900  # 15 minutes


def _now_str() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _exp_str(ttl: int = _TEST_SESSION_TTL) -> str:
    exp = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return exp.isoformat().replace("+00:00", "Z")


def _new_session_id() -> str:
    return f"ts_{uuid.uuid4().hex[:14]}"


class TestSessionStore:
    """
    Redis store for ephemeral mic-test and translation-test sessions.

    Key namespaces:
      test:mic:{session_id}    -> JSON MicTestSession
      test:trans:{session_id}  -> JSON TranslationTestSession

    Both expire automatically after _TEST_SESSION_TTL seconds.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    # ------------------------------------------------------------------
    # Mic test sessions
    # ------------------------------------------------------------------

    def _mic_key(self, session_id: str) -> str:
        return f"test:mic:{session_id}"

    async def create_mic_session(self) -> MicTestSession:
        session_id = _new_session_id()
        session = MicTestSession(
            session_id=session_id,
            status="created",
            created_at=_now_str(),
            expires_at=_exp_str(),
        )
        await self._redis.set(
            self._mic_key(session_id),
            session.model_dump_json(),
            ex=_TEST_SESSION_TTL,
        )
        return session

    async def get_mic_session(self, session_id: str) -> Optional[MicTestSession]:
        raw = await self._redis.get(self._mic_key(session_id))
        if raw is None:
            return None
        return MicTestSession.model_validate_json(raw)

    async def update_mic_session_status(self, session_id: str, status: str) -> None:
        raw = await self._redis.get(self._mic_key(session_id))
        if raw is None:
            return
        data = json.loads(raw)
        data["status"] = status
        ttl = await self._redis.ttl(self._mic_key(session_id))
        await self._redis.set(
            self._mic_key(session_id),
            json.dumps(data),
            ex=max(ttl, 1),
        )

    async def delete_mic_session(self, session_id: str) -> None:
        await self._redis.delete(self._mic_key(session_id))

    # ------------------------------------------------------------------
    # Translation test sessions
    # ------------------------------------------------------------------

    def _trans_key(self, session_id: str) -> str:
        return f"test:trans:{session_id}"

    async def create_translation_session(
        self, src_lang: str, tgt_lang: str
    ) -> TranslationTestSession:
        session_id = _new_session_id()
        session = TranslationTestSession(
            session_id=session_id,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            status="created",
            created_at=_now_str(),
            expires_at=_exp_str(),
        )
        await self._redis.set(
            self._trans_key(session_id),
            session.model_dump_json(),
            ex=_TEST_SESSION_TTL,
        )
        return session

    async def get_translation_session(
        self, session_id: str
    ) -> Optional[TranslationTestSession]:
        raw = await self._redis.get(self._trans_key(session_id))
        if raw is None:
            return None
        return TranslationTestSession.model_validate_json(raw)

    async def update_translation_session_status(
        self, session_id: str, status: str
    ) -> None:
        raw = await self._redis.get(self._trans_key(session_id))
        if raw is None:
            return
        data = json.loads(raw)
        data["status"] = status
        ttl = await self._redis.ttl(self._trans_key(session_id))
        await self._redis.set(
            self._trans_key(session_id),
            json.dumps(data),
            ex=max(ttl, 1),
        )

    async def delete_translation_session(self, session_id: str) -> None:
        await self._redis.delete(self._trans_key(session_id))
