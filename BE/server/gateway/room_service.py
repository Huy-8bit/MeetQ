import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi.encoders import jsonable_encoder
from redis.asyncio import Redis

from server.config import Settings
from server.events import EventType, build_envelope
from server.gateway.auth import issue_room_token
from server.gateway.livekit_tokens import generate_livekit_token
from server.gateway.room_store import RoomStore
from server.meeting_modes import (
    MEETING_MODE_BRSE_RELAY,
    INTERPRETER_MODE_BRSE_PARTICIPANT,
    active_human_participant_count,
    build_brse_audio_routing,
    build_brse_virtual_participant,
)
from server.models import (
    CreateRoomResponse,
    CreateRoomResponseJoin,
    CreateRoomResponseRoom,
    JoinRoomRequestClient,
    JoinRoomResponse,
    JoinRoomResponseLivekit,
    JoinRoomResponseParticipant,
    JoinRoomResponseRoomToken,
    JoinRoomResponseWebsocket,
    Language,
    ParticipantState,
    RoomSnapshotResponse,
    RoomState,
    ScreenShareTrackInfo,
    SnapshotData,
    TranscriptEvent,
)


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
        self.gateway_control_channel = settings.redis_channel_gateway_control

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _now_str(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _exp_str(self) -> str:
        exp = datetime.now(timezone.utc) + timedelta(seconds=self.settings.room_token_ttl_seconds)
        return exp.isoformat().replace("+00:00", "Z")

    async def _publish(self, event_type: str, room_id: str, payload: Any):
        envelope = build_envelope(event_type, room_id, jsonable_encoder(payload))
        await self.redis.publish(self.gateway_control_channel, json.dumps(envelope))

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
            meeting_mode=MEETING_MODE_BRSE_RELAY,
            interpreter_mode=INTERPRETER_MODE_BRSE_PARTICIPANT,
            audio_routing=build_brse_audio_routing(),
            virtual_participants=[build_brse_virtual_participant(room_id, now)],
        )
        await self.store.create_room(room)

        await self._publish(EventType.ROOM_CREATED, room_id, room.model_dump())
        if room.virtual_participants:
            for participant in room.virtual_participants:
                await self._publish(EventType.PARTICIPANT_JOINED, room_id, participant)

        return CreateRoomResponse(
            room=self._room_response_from_state(room),
            join=CreateRoomResponseJoin(
                api_path=f"/api/rooms/{room_id}/join",
                share_url=f"/rooms/{room_id}",
            ),
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
        if transcript.kind in {"source", "relay"}:
            return True
        return transcript.listener_id == participant_id

    async def join_room(
        self,
        room_id: str,
        display_name: str,
        language: Language,
        client_meta: Optional[JoinRoomRequestClient],
    ) -> JoinRoomResponse:
        snapshot = await self.store.get_room_snapshot(room_id)
        if not snapshot:
            raise RoomNotFoundError()

        if active_human_participant_count(snapshot.participants) >= snapshot.room.participant_limit:
            raise RoomFullError()

        if language not in snapshot.room.supported_languages and language != "auto":
            raise InvalidLanguageError()

        if snapshot.room.state in {"created", "empty"}:
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
            joined_at=now,
            last_seen_at=now,
            ws_connected=False,
            livekit_identity=participant_id,
        )

        await self.store.add_participant(room_id, participant)
        await self._publish(EventType.PARTICIPANT_JOINED, room_id, participant.model_dump())

        room_token = issue_room_token(
            room_id=room_id,
            participant_id=participant_id,
            session_id=session_id,
            display_name=display_name,
            language=language,
            secret=self.settings.room_jwt_secret,
            ttl_seconds=self.settings.room_token_ttl_seconds,
        )

        lk_token = generate_livekit_token(
            room_name=room_id,
            participant_id=participant_id,
            participant_name=display_name,
            language=language,
            api_key=self.settings.livekit_api_key,
            api_secret=self.settings.livekit_api_secret,
            ttl_seconds=self.settings.room_token_ttl_seconds,
            kind="human",
            livekit_identity=participant_id,
        )

        fresh_snapshot = await self.store.get_room_snapshot(room_id)
        personalized_snapshot = self.build_snapshot_data_for_participant(
            fresh_snapshot,
            participant_id,
        )

        return JoinRoomResponse(
            room=self._room_response_from_state(fresh_snapshot.room),
            participant=JoinRoomResponseParticipant(
                participant_id=participant_id,
                session_id=session_id,
                display_name=display_name,
                language=language,
            ),
            room_token=JoinRoomResponseRoomToken(
                token=room_token,
                expires_at=self._exp_str(),
            ),
            websocket=JoinRoomResponseWebsocket(
                url=f"/ws/rooms/{room_id}?token={room_token}",
            ),
            livekit=JoinRoomResponseLivekit(
                url=self.settings.livekit_ws_url_public,
                room_name=room_id,
                participant_identity=participant_id,
                participant_name=display_name,
                token=lk_token,
            ),
            snapshot=SnapshotData(
                participants=personalized_snapshot.participants,
                recent_transcripts=personalized_snapshot.recent_transcripts,
            ),
        )

    async def leave_room(self, room_id: str, participant_id: str, session_id: Optional[str] = None) -> None:
        await self.cleanup_participant(
            room_id=room_id,
            participant_id=participant_id,
            session_id=session_id,
            reason="rest_leave",
        )

    async def cleanup_participant(
        self,
        room_id: str,
        participant_id: str,
        session_id: Optional[str],
        reason: str,
    ) -> bool:
        participant = await self.store.get_participant(room_id, participant_id)
        if participant is None:
            return False

        if session_id and participant.session_id != session_id:
            return False

        if participant.status == "disconnected":
            await self.store.remove_participant(room_id, participant_id)
            return True

        if participant.is_screen_sharing:
            await self.stop_screen_share(
                room_id=room_id,
                participant_id=participant_id,
                session_id=participant.session_id,
                reason=f"{reason}_participant_cleanup",
            )

        now = self._now_str()
        await self.store.remove_participant(room_id, participant_id)

        await self._publish(
            EventType.PARTICIPANT_LEFT,
            room_id,
            {
                "participant_id": participant_id,
                "session_id": participant.session_id,
                "left_at": now,
                "reason": reason,
            },
        )

        fresh_snapshot = await self.store.get_room_snapshot(room_id)
        if fresh_snapshot and active_human_participant_count(fresh_snapshot.participants) == 0:
            await self.store.mark_room_empty(room_id)

        return True

    async def start_screen_share(
        self,
        room_id: str,
        participant_id: str,
        session_id: Optional[str],
        *,
        track_sid: Optional[str],
        track_name: Optional[str],
        source: str = "screen_share",
    ) -> bool:
        participant = await self.store.get_participant(room_id, participant_id)
        if participant is None:
            raise ParticipantNotFoundError()

        if session_id and participant.session_id != session_id:
            return False

        if participant.status == "disconnected":
            return False

        if source != "screen_share":
            source = "screen_share"

        current_track = participant.screen_share
        if (
            participant.is_screen_sharing
            and current_track is not None
            and current_track.track_sid == track_sid
            and current_track.track_name == track_name
        ):
            return True

        now = self._now_str()
        next_track = ScreenShareTrackInfo(
            active=True,
            source=source,
            track_sid=track_sid,
            track_name=track_name,
            started_at=now,
        )

        await self.store.update_participant(
            room_id,
            participant_id,
            {
                "is_screen_sharing": True,
                "screen_share": next_track.model_dump(),
                "last_seen_at": now,
            },
        )

        updated = await self.store.get_participant(room_id, participant_id)
        if updated is None:
            return False

        await self._publish(EventType.PARTICIPANT_UPDATED, room_id, updated.model_dump())
        await self._publish(
            EventType.SCREEN_SHARE_STARTED,
            room_id,
            {
                "participant_id": updated.participant_id,
                "display_name": updated.display_name,
                "track_sid": track_sid,
                "track_name": track_name,
                "active": True,
                "timestamp": now,
                "source": source,
            },
        )

        return True

    async def stop_screen_share(
        self,
        room_id: str,
        participant_id: str,
        session_id: Optional[str],
        *,
        reason: str,
    ) -> bool:
        participant = await self.store.get_participant(room_id, participant_id)
        if participant is None:
            raise ParticipantNotFoundError()

        if session_id and participant.session_id != session_id:
            return False

        if not participant.is_screen_sharing:
            return True

        previous_track = participant.screen_share
        now = self._now_str()
        await self.store.update_participant(
            room_id,
            participant_id,
            {
                "is_screen_sharing": False,
                "screen_share": None,
                "last_seen_at": now,
            },
        )

        updated = await self.store.get_participant(room_id, participant_id)
        if updated is None:
            return False

        await self._publish(EventType.PARTICIPANT_UPDATED, room_id, updated.model_dump())
        await self._publish(
            EventType.SCREEN_SHARE_STOPPED,
            room_id,
            {
                "participant_id": participant.participant_id,
                "display_name": participant.display_name,
                "track_sid": previous_track.track_sid if previous_track else None,
                "track_name": previous_track.track_name if previous_track else None,
                "active": False,
                "timestamp": now,
                "reason": reason,
                "source": previous_track.source if previous_track else "screen_share",
            },
        )

        return True

    async def touch_participant_presence(
        self,
        room_id: str,
        participant_id: str,
        session_id: Optional[str],
        *,
        ws_connected: Optional[bool] = None,
        status: Optional[str] = None,
    ) -> bool:
        participant = await self.store.get_participant(room_id, participant_id)
        if participant is None:
            return False

        if session_id and participant.session_id != session_id:
            return False

        patch: Dict[str, Any] = {"last_seen_at": self._now_str()}
        if ws_connected is not None:
            patch["ws_connected"] = ws_connected
        if status is not None:
            patch["status"] = status

        await self.store.update_participant(room_id, participant_id, patch)
        return True

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

    def _room_response_from_state(self, room: Any) -> CreateRoomResponseRoom:
        if hasattr(room, "model_dump"):
            payload = room.model_dump()
        else:
            payload = dict(room)

        return CreateRoomResponseRoom(
            room_id=payload["room_id"],
            state=payload["state"],
            created_at=payload["created_at"],
            expires_at=payload["expires_at"],
            participant_limit=payload["participant_limit"],
            supported_languages=payload["supported_languages"],
            meeting_mode=payload.get("meeting_mode", MEETING_MODE_BRSE_RELAY),
            interpreter_mode=payload.get("interpreter_mode", INTERPRETER_MODE_BRSE_PARTICIPANT),
            audio_routing=payload["audio_routing"],
        )
