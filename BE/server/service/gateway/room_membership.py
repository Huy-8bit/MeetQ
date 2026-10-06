"""Live room membership: who (stable user ID) holds which role in a running room.

Redis keys (same lifetime as the room):
  room:{room_id}:members   hash  user_id -> {"role", "joined_at", "removed_at", "removed_by_user_id"}
  room:{room_id}:pusers    hash  participant_id -> user_id

A participant ID is one realtime session (a new one on every join/reconnect); the user
ID is the person. Roles and bans belong to the user, so a host who reconnects is still
the host and a removed user stays removed. The durable copy lives in MongoDB
`room_memberships` (see MongoRoomHistoryRepository) for meeting history.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from server.service.gateway.room_permissions import ROLE_HOST, ROLE_PARTICIPANT, normalize_role


class RoomMembershipStore:
    def __init__(self, client: Any, ttl_seconds: int) -> None:
        self.client = client
        self.ttl = ttl_seconds

    @staticmethod
    def members_key(room_id: str) -> str:
        return f"room:{room_id}:members"

    @staticmethod
    def participants_key(room_id: str) -> str:
        return f"room:{room_id}:pusers"

    async def _touch(self, room_id: str) -> None:
        await self.client.expire(self.members_key(room_id), self.ttl)
        await self.client.expire(self.participants_key(room_id), self.ttl)

    async def get(self, room_id: str, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not user_id:
            return None
        raw = await self.client.hget(self.members_key(room_id), user_id)
        if not raw:
            return None
        try:
            member = json.loads(raw)
        except (TypeError, ValueError):
            return None
        member["user_id"] = user_id
        member["role"] = normalize_role(member.get("role"))
        return member

    async def put(self, room_id: str, user_id: str, member: Dict[str, Any]) -> Dict[str, Any]:
        stored = {key: value for key, value in member.items() if key != "user_id"}
        stored["role"] = normalize_role(stored.get("role"))
        await self.client.hset(self.members_key(room_id), user_id, json.dumps(stored))
        await self._touch(room_id)
        return {**stored, "user_id": user_id}

    async def set_host(self, room_id: str, user_id: str, *, created_at: str) -> Dict[str, Any]:
        return await self.put(room_id, user_id, {"role": ROLE_HOST, "created_at": created_at, "joined_at": None})

    async def ensure_member(self, room_id: str, user_id: str, *, joined_at: str) -> Dict[str, Any]:
        """Existing membership (keeps its role) or a new PARTICIPANT one; records the first join."""
        member = await self.get(room_id, user_id)
        if member is None:
            return await self.put(room_id, user_id, {"role": ROLE_PARTICIPANT, "joined_at": joined_at})
        if not member.get("joined_at"):
            member["joined_at"] = joined_at
            member = await self.put(room_id, user_id, member)
        return member

    async def update(self, room_id: str, user_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        member = await self.get(room_id, user_id)
        if member is None:
            return None
        member.update(patch)
        return await self.put(room_id, user_id, member)

    async def host_user_id(self, room_id: str) -> Optional[str]:
        for user_id, raw in (await self.client.hgetall(self.members_key(room_id))).items():
            try:
                if json.loads(raw).get("role") == ROLE_HOST:
                    return user_id
            except (TypeError, ValueError):
                continue
        return None

    async def link_participant(self, room_id: str, participant_id: str, user_id: str) -> None:
        await self.client.hset(self.participants_key(room_id), participant_id, user_id)
        await self._touch(room_id)

    async def user_for_participant(self, room_id: str, participant_id: Optional[str]) -> Optional[str]:
        if not participant_id:
            return None
        user_id = await self.client.hget(self.participants_key(room_id), participant_id)
        return user_id or None

    async def participants_for_user(self, room_id: str, user_id: str) -> List[str]:
        mapping = await self.client.hgetall(self.participants_key(room_id))
        return [participant_id for participant_id, owner in mapping.items() if owner == user_id]

    async def delete(self, room_id: str) -> None:
        await self.client.delete(self.members_key(room_id), self.participants_key(room_id))
