import json
import redis.asyncio as redis
from typing import Optional, Dict, Any, List
from server.models import RoomState, ParticipantState, TranscriptEvent, SnapshotData, ParticipantSnapshot, RoomSnapshotResponseRoom, RoomSnapshotResponse

class RoomStore:
    def __init__(self, client: redis.Redis, ttl_seconds: int = 86400, transcript_limit: int = 50):
        self.client = client
        self.ttl = ttl_seconds
        self.limit = transcript_limit

    def _meta_key(self, room_id: str) -> str:
        return f"room:{room_id}:meta"

    def _parts_key(self, room_id: str) -> str:
        return f"room:{room_id}:participants"

    def _trans_key(self, room_id: str) -> str:
        return f"room:{room_id}:transcripts"

    async def _refresh_ttl(self, room_id: str):
        pipe = self.client.pipeline()
        pipe.expire(self._meta_key(room_id), self.ttl)
        pipe.expire(self._parts_key(room_id), self.ttl)
        pipe.expire(self._trans_key(room_id), self.ttl)
        await pipe.execute()

    async def create_room(self, room: RoomState):
        await self.client.set(self._meta_key(room.room_id), room.model_dump_json(), ex=self.ttl)

    async def get_room_snapshot(self, room_id: str) -> Optional[RoomSnapshotResponse]:
        meta_json = await self.client.get(self._meta_key(room_id))
        if not meta_json:
            return None

        room_state = RoomState.model_validate_json(meta_json)
        
        parts_data = await self.client.hgetall(self._parts_key(room_id))
        participants = []
        participant_count = 0
        for p_json in parts_data.values():
            p_state = ParticipantState.model_validate_json(p_json)
            # count only connected/joining ? The contract says count of active? Let's just say count all non-left
            if p_state.left_at is None:
                participant_count += 1
            participants.append(ParticipantSnapshot(
                participant_id=p_state.participant_id,
                display_name=p_state.display_name,
                language=p_state.language,
                status=p_state.status,
                joined_at=p_state.joined_at
            ))

        trans_data = await self.client.lrange(self._trans_key(room_id), 0, -1)
        transcripts = [TranscriptEvent.model_validate_json(t) for t in trans_data]

        room_res = RoomSnapshotResponseRoom(
            room_id=room_state.room_id,
            state=room_state.state,
            created_at=room_state.created_at,
            expires_at=room_state.expires_at,
            participant_limit=room_state.participant_limit,
            supported_languages=room_state.supported_languages,
            audio_routing=room_state.audio_routing,
            participant_count=participant_count
        )

        return RoomSnapshotResponse(
            room=room_res,
            participants=participants,
            recent_transcripts=transcripts
        )

    async def add_participant(self, room_id: str, participant: ParticipantState):
        await self.client.hset(self._parts_key(room_id), participant.participant_id, participant.model_dump_json())
        await self._refresh_ttl(room_id)

    async def update_participant(self, room_id: str, participant_id: str, patch: Dict[str, Any]):
        p_json = await self.client.hget(self._parts_key(room_id), participant_id)
        if p_json:
            p_data = json.loads(p_json)
            p_data.update(patch)
            # Revalidate to ensure correctness
            updated_p = ParticipantState(**p_data)
            await self.client.hset(self._parts_key(room_id), participant_id, updated_p.model_dump_json())
            await self._refresh_ttl(room_id)

    async def mark_participant_left(self, room_id: str, participant_id: str, left_at: str):
        await self.update_participant(room_id, participant_id, {"status": "disconnected", "left_at": left_at})

    async def append_transcript(self, room_id: str, transcript: TranscriptEvent):
        key = self._trans_key(room_id)
        pipe = self.client.pipeline()
        pipe.rpush(key, transcript.model_dump_json())
        pipe.ltrim(key, -self.limit, -1)
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
            self._trans_key(room_id)
        )
