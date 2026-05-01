import json
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

from server.models import (
    ChatMessage,
    ParticipantSnapshot,
    ParticipantState,
    RoomSnapshotResponse,
    RoomSnapshotResponseRoom,
    RoomState,
    TranscriptEvent,
)


class RoomStore:
    def __init__(
        self,
        client: redis.Redis,
        ttl_seconds: int = 2100,  # 30-min meeting + 5-min cleanup grace
        transcript_limit: int = 50,
        chat_limit: int = 100,
    ):
        self.client = client
        self.ttl = ttl_seconds
        self.limit = transcript_limit
        self.chat_limit = chat_limit

    def _meta_key(self, room_id: str) -> str:
        return f"room:{room_id}:meta"

    def _parts_key(self, room_id: str) -> str:
        return f"room:{room_id}:participants"

    def _trans_key(self, room_id: str) -> str:
        return f"room:{room_id}:transcripts"

    def _chat_key(self, room_id: str) -> str:
        return f"room:{room_id}:chat"

    async def _refresh_ttl(self, room_id: str):
        pipe = self.client.pipeline()
        pipe.expire(self._meta_key(room_id), self.ttl)
        pipe.expire(self._parts_key(room_id), self.ttl)
        pipe.expire(self._trans_key(room_id), self.ttl)
        pipe.expire(self._chat_key(room_id), self.ttl)
        await pipe.execute()

    async def create_room(self, room: RoomState):
        await self.client.set(self._meta_key(room.room_id), room.model_dump_json(), ex=self.ttl)

    async def update_room(self, room_id: str, patch: Dict[str, Any]) -> Optional[RoomState]:
        meta_json = await self.client.get(self._meta_key(room_id))
        if not meta_json:
            return None

        room_data = json.loads(meta_json)
        room_data.update(patch)
        updated = RoomState(**room_data)
        await self.client.set(self._meta_key(room_id), updated.model_dump_json(), ex=self.ttl)
        await self._refresh_ttl(room_id)
        return updated

    async def get_room_snapshot(self, room_id: str) -> Optional[RoomSnapshotResponse]:
        meta_json = await self.client.get(self._meta_key(room_id))
        if not meta_json:
            return None

        room_state = RoomState.model_validate_json(meta_json)
        participants: List[ParticipantSnapshot] = []

        parts_data = await self.client.hgetall(self._parts_key(room_id))
        for p_json in parts_data.values():
            p_state = ParticipantState.model_validate_json(p_json)
            if p_state.status == "disconnected":
                continue
            participants.append(self._participant_state_to_snapshot(p_state))

        if room_state.brse_enabled:
            participants.extend(
                payload if isinstance(payload, ParticipantSnapshot) else ParticipantSnapshot.model_validate(payload)
                for payload in room_state.virtual_participants
            )

        participant_count = sum(1 for participant in participants if participant.status != "disconnected")

        trans_data = await self.client.lrange(self._trans_key(room_id), 0, -1)
        transcripts = [TranscriptEvent.model_validate_json(t) for t in trans_data]
        if not room_state.brse_enabled:
            transcripts = []
        chat_data = await self.client.lrange(self._chat_key(room_id), 0, -1)
        messages = [ChatMessage.model_validate_json(t) for t in chat_data]

        room_res = RoomSnapshotResponseRoom(
            room_id=room_state.room_id,
            state=room_state.state,
            created_at=room_state.created_at,
            expires_at=room_state.expires_at,
            brse_enabled=room_state.brse_enabled,
            participant_limit=room_state.participant_limit,
            supported_languages=room_state.supported_languages,
            meeting_languages=room_state.meeting_languages,
            meeting_mode=room_state.meeting_mode,
            interpreter_mode=room_state.interpreter_mode,
            audio_routing=room_state.audio_routing,
            participant_count=participant_count,
        )

        return RoomSnapshotResponse(
            room=room_res,
            participants=participants,
            recent_transcripts=transcripts,
            recent_messages=messages,
        )

    async def add_participant(self, room_id: str, participant: ParticipantState):
        await self.client.hset(self._parts_key(room_id), participant.participant_id, participant.model_dump_json())
        await self._refresh_ttl(room_id)

    async def get_participant(self, room_id: str, participant_id: str) -> Optional[ParticipantState]:
        p_json = await self.client.hget(self._parts_key(room_id), participant_id)
        if not p_json:
            return None
        return ParticipantState.model_validate_json(p_json)

    async def update_participant(self, room_id: str, participant_id: str, patch: Dict[str, Any]):
        p_json = await self.client.hget(self._parts_key(room_id), participant_id)
        if p_json:
            p_data = json.loads(p_json)
            p_data.update(patch)
            updated_p = ParticipantState(**p_data)
            await self.client.hset(self._parts_key(room_id), participant_id, updated_p.model_dump_json())
            await self._refresh_ttl(room_id)

    async def mark_participant_left(self, room_id: str, participant_id: str, left_at: str):
        await self.update_participant(
            room_id,
            participant_id,
            {
                "status": "disconnected",
                "ws_connected": False,
                "left_at": left_at,
                "last_seen_at": left_at,
            },
        )

    async def remove_participant(self, room_id: str, participant_id: str):
        await self.client.hdel(self._parts_key(room_id), participant_id)
        await self._refresh_ttl(room_id)

    async def append_transcript(self, room_id: str, transcript: TranscriptEvent):
        key = self._trans_key(room_id)
        pipe = self.client.pipeline()
        pipe.rpush(key, transcript.model_dump_json())
        pipe.ltrim(key, -self.limit, -1)
        await pipe.execute()
        await self._refresh_ttl(room_id)

    async def clear_transcripts(self, room_id: str):
        await self.client.delete(self._trans_key(room_id))
        await self._refresh_ttl(room_id)

    async def append_chat_message(self, room_id: str, message: ChatMessage):
        key = self._chat_key(room_id)
        pipe = self.client.pipeline()
        pipe.rpush(key, message.model_dump_json())
        pipe.ltrim(key, -self.chat_limit, -1)
        await pipe.execute()
        await self._refresh_ttl(room_id)

    async def mark_room_empty(self, room_id: str):
        meta_json = await self.client.get(self._meta_key(room_id))
        if meta_json:
            room_data = json.loads(meta_json)
            room_data["state"] = "empty"
            updated_r = RoomState(**room_data)
            await self.client.set(self._meta_key(room_id), updated_r.model_dump_json(), ex=self.ttl)

    async def delete_room(self, room_id: str):
        await self.client.delete(
            self._meta_key(room_id),
            self._parts_key(room_id),
            self._trans_key(room_id),
            self._chat_key(room_id),
        )

    def _participant_state_to_snapshot(self, participant: ParticipantState) -> ParticipantSnapshot:
        return ParticipantSnapshot(
            participant_id=participant.participant_id,
            display_name=participant.display_name,
            language=participant.language,
            status=participant.status,
            joined_at=participant.joined_at,
            last_seen_at=participant.last_seen_at,
            ws_connected=participant.ws_connected,
            kind=participant.kind,
            is_virtual=participant.is_virtual,
            livekit_identity=participant.livekit_identity,
            metadata=participant.metadata,
            is_screen_sharing=participant.is_screen_sharing,
            screen_share=participant.screen_share,
        )
