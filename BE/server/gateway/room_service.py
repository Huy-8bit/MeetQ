import uuid
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from redis.asyncio import Redis

from server.config import Settings
from server.models import (
    RoomState, ParticipantState, RoomSnapshotResponse, CreateRoomResponse,
    CreateRoomResponseRoom, CreateRoomResponseJoin, JoinRoomRequestClient,
    JoinRoomResponse, JoinRoomResponseParticipant, JoinRoomResponseRoomToken,
    JoinRoomResponseWebsocket, JoinRoomResponseLivekit, SnapshotData, TranscriptEvent,
    Language
)
from server.gateway.room_store import RoomStore
from server.gateway.auth import issue_room_token
from server.gateway.livekit_tokens import generate_livekit_token
from server.events import GATEWAY_CONTROL_CHANNEL, EventType, build_envelope

class RoomFullError(Exception):
    pass

class InvalidLanguageError(Exception):
    pass

class RoomNotFoundError(Exception):
    pass

class ParticipantNotFoundError(Exception):
    pass

class RoomService:
    def __init__(self, store: RoomStore, settings: Settings, redis: Redis):
        self.store = store
        self.settings = settings
        self.redis = redis

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _now_str(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
    def _exp_str(self) -> str:
        exp = datetime.now(timezone.utc) + timedelta(seconds=self.settings.room_token_ttl_seconds)
        return exp.isoformat().replace("+00:00", "Z")

    async def _publish(self, event_type: str, room_id: str, payload: Dict[str, Any]):
        envelope = build_envelope(event_type, room_id, payload)
        await self.redis.publish(GATEWAY_CONTROL_CHANNEL, json.dumps(envelope))

    async def create_room(self) -> CreateRoomResponse:
        room_id = self._generate_id("rm")
        now = self._now_str()
        exp = self._exp_str()
        
        room = RoomState(
            room_id=room_id,
            state="created",
            created_at=now,
            expires_at=exp,
            participant_limit=8,
            supported_languages=["vi", "en", "ja"],
        )
        await self.store.create_room(room)
        
        # Publish event
        await self._publish(EventType.ROOM_CREATED, room_id, room.model_dump())
        
        return CreateRoomResponse(
            room=CreateRoomResponseRoom(
                room_id=room.room_id,
                state=room.state,
                created_at=room.created_at,
                expires_at=room.expires_at,
                participant_limit=room.participant_limit,
                supported_languages=room.supported_languages,
                audio_routing=room.audio_routing,
            ),
            join=CreateRoomResponseJoin(
                api_path=f"/api/rooms/{room_id}/join",
                share_url=f"/rooms/{room_id}" # Simplified for now, FE will use window.location
            )
        )

    async def get_room(self, room_id: str) -> RoomSnapshotResponse:
        snapshot = await self.store.get_room_snapshot(room_id)
        if not snapshot:
            raise RoomNotFoundError()
        return snapshot

    def build_snapshot_data_for_participant(
        self,
        snapshot: RoomSnapshotResponse,
        participant_id: str,
    ) -> SnapshotData:
        return SnapshotData(
            participants=snapshot.participants,
            recent_transcripts=[
                transcript
                for transcript in snapshot.recent_transcripts
                if self._transcript_visible_to_participant(transcript, participant_id)
            ],
        )

    def _transcript_visible_to_participant(
        self,
        transcript: TranscriptEvent,
        participant_id: str,
    ) -> bool:
        if transcript.kind == "source":
            return True
        return transcript.listener_id == participant_id

    async def join_room(self, room_id: str, display_name: str, language: Language, client_meta: Optional[JoinRoomRequestClient]) -> JoinRoomResponse:
        snapshot = await self.store.get_room_snapshot(room_id)
        if not snapshot:
            raise RoomNotFoundError()
            
        if snapshot.room.participant_count >= snapshot.room.participant_limit:
            raise RoomFullError()
            
        if language not in snapshot.room.supported_languages and language != "auto":
            raise InvalidLanguageError()

        # Update room state to active if it was created
        if snapshot.room.state == "created":
            meta_json = await self.store.client.get(self.store._meta_key(room_id))
            if meta_json:
                room_data = json.loads(meta_json)
                room_data["state"] = "active"
                await self.store.create_room(RoomState(**room_data))

        participant_id = self._generate_id("pt")
        session_id = self._generate_id("ses")
        now = self._now_str()
        
        participant = ParticipantState(
            participant_id=participant_id,
            session_id=session_id,
            display_name=display_name,
            language=language,
            status="joining",
            joined_at=now
        )
        
        await self.store.add_participant(room_id, participant)
        
        # Publish event
        await self._publish(EventType.PARTICIPANT_JOINED, room_id, participant.model_dump())
        
        room_token = issue_room_token(
            room_id=room_id,
            participant_id=participant_id,
            session_id=session_id,
            display_name=display_name,
            language=language,
            secret=self.settings.room_jwt_secret,
            ttl_seconds=self.settings.room_token_ttl_seconds
        )
        
        lk_token = generate_livekit_token(
            room_name=room_id,
            participant_id=participant_id,
            participant_name=display_name,
            language=language,
            api_key=self.settings.livekit_api_key,
            api_secret=self.settings.livekit_api_secret,
            ttl_seconds=self.settings.room_token_ttl_seconds
        )
        
        # We need a fresh snapshot after joining to return
        fresh_snapshot = await self.store.get_room_snapshot(room_id)
        personalized_snapshot = self.build_snapshot_data_for_participant(
            fresh_snapshot,
            participant_id,
        )
        
        return JoinRoomResponse(
            room=CreateRoomResponseRoom(
                room_id=fresh_snapshot.room.room_id,
                state=fresh_snapshot.room.state,
                created_at=fresh_snapshot.room.created_at,
                expires_at=fresh_snapshot.room.expires_at,
                participant_limit=fresh_snapshot.room.participant_limit,
                supported_languages=fresh_snapshot.room.supported_languages,
                audio_routing=fresh_snapshot.room.audio_routing,
            ),
            participant=JoinRoomResponseParticipant(
                participant_id=participant_id,
                session_id=session_id,
                display_name=display_name,
                language=language
            ),
            room_token=JoinRoomResponseRoomToken(
                token=room_token,
                expires_at=self._exp_str()
            ),
            websocket=JoinRoomResponseWebsocket(
                url=f"/ws/rooms/{room_id}?token={room_token}"
            ),
            livekit=JoinRoomResponseLivekit(
                url=self.settings.livekit_ws_url_public,
                room_name=room_id,
                participant_identity=participant_id,
                participant_name=display_name,
                token=lk_token
            ),
            snapshot=SnapshotData(
                participants=personalized_snapshot.participants,
                recent_transcripts=personalized_snapshot.recent_transcripts
            )
        )

    async def leave_room(self, room_id: str, participant_id: str) -> None:
        snapshot = await self.store.get_room_snapshot(room_id)
        if not snapshot:
            return
            
        now = self._now_str()
        await self.store.mark_participant_left(room_id, participant_id, now)
        
        # Publish event
        await self._publish(EventType.PARTICIPANT_LEFT, room_id, {
            "participant_id": participant_id,
            "left_at": now
        })
        
        # Check if empty
        fresh_snapshot = await self.store.get_room_snapshot(room_id)
        if fresh_snapshot and fresh_snapshot.room.participant_count == 0:
            await self.store.mark_room_empty(room_id)

    async def set_language(self, room_id: str, participant_id: str, language: Language) -> ParticipantState:
        snapshot = await self.store.get_room_snapshot(room_id)
        if not snapshot:
            raise RoomNotFoundError()
            
        if language not in snapshot.room.supported_languages and language != "auto":
            raise InvalidLanguageError()
            
        p_json = await self.store.client.hget(self.store._parts_key(room_id), participant_id)
        if not p_json:
            raise ParticipantNotFoundError()
            
        await self.store.update_participant(room_id, participant_id, {"language": language})
        
        p_json = await self.store.client.hget(self.store._parts_key(room_id), participant_id)
        updated_p = ParticipantState.model_validate_json(p_json)
        
        await self._publish(EventType.PARTICIPANT_UPDATED, room_id, updated_p.model_dump())
        return updated_p
