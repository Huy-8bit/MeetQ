import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi.encoders import jsonable_encoder
from redis.asyncio import Redis

from server.config import Settings
from server.events import EventType, build_envelope
from server.gateway.auth import issue_room_token
from server.gateway.livekit_tokens import generate_livekit_token
from server.gateway.room_store import RoomStore
from server.integrations.telegram import TelegramNotifier
from server.meeting_modes import (
    BRSE_PARTICIPANT_ID,
    DEFAULT_BRSE_ENABLED,
    DEFAULT_ROOM_MEETING_LANGUAGES,
    MEETING_MODE_BRSE_RELAY,
    INTERPRETER_MODE_BRSE_PARTICIPANT,
    SUPPORTED_MEETING_LANGUAGES,
    active_human_participant_count,
    build_brse_audio_routing,
    build_brse_virtual_participant,
)
from server.models import (
    ChatMessage,
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
    MeetingLanguage,
    ParticipantState,
    RoomSnapshotResponse,
    RoomState,
    ScreenShareTrackInfo,
    SnapshotData,
    TranscriptEvent,
)


logger = logging.getLogger(__name__)


class RoomFullError(Exception):
    pass


class InvalidLanguageError(Exception):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.details = details or {}


class InvalidMeetingLanguagesError(Exception):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.details = details or {}


class RoomNotFoundError(Exception):
    pass


class ParticipantNotFoundError(Exception):
    pass


class BrseToggleForbiddenError(Exception):
    def __init__(self, message: str, code: str = "brse_toggle_forbidden"):
        super().__init__(message)
        self.code = code


class RoomExpiredError(Exception):
    """Room meeting duration (30 min) has elapsed; no new joins or actions."""
    pass


class InvalidChatMessageError(Exception):
    def __init__(self, message: str, code: str = "invalid_chat_message"):
        super().__init__(message)
        self.code = code


class RoomService:
    MAX_CHAT_MESSAGE_LENGTH = 2000

    def __init__(self, store: RoomStore, settings: Settings, redis: Redis):
        self.store = store
        self.settings = settings
        self.redis = redis
        self.gateway_control_channel = settings.redis_channel_gateway_control
        self.telegram_notifier = TelegramNotifier(settings)
        self._notification_tasks: set[asyncio.Task] = set()

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _now_str(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _exp_str(self) -> str:
        """Room meeting expiry: 30-minute logical meeting duration from now."""
        exp = datetime.now(timezone.utc) + timedelta(seconds=self.settings.room_meeting_duration_seconds)
        return exp.isoformat().replace("+00:00", "Z")

    def _token_exp_str(self) -> str:
        """Room token expiry: longer TTL for JWT validity."""
        exp = datetime.now(timezone.utc) + timedelta(seconds=self.settings.room_token_ttl_seconds)
        return exp.isoformat().replace("+00:00", "Z")

    def _is_room_expired(self, room_state) -> bool:
        """Check if room meeting duration has elapsed."""
        expires_at_str = None
        if hasattr(room_state, 'expires_at'):
            expires_at_str = room_state.expires_at
        elif hasattr(room_state, 'room') and hasattr(room_state.room, 'expires_at'):
            expires_at_str = room_state.room.expires_at
        elif isinstance(room_state, dict):
            expires_at_str = room_state.get('expires_at')

        if not expires_at_str:
            return False

        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            return datetime.now(timezone.utc) >= expires_at
        except (ValueError, TypeError):
            return False

    async def _publish(self, event_type: str, room_id: str, payload: Any):
        envelope = build_envelope(event_type, room_id, jsonable_encoder(payload))
        await self.redis.publish(self.gateway_control_channel, json.dumps(envelope))

    def _schedule_room_created_notification(self, room: RoomState, share_url: str) -> None:
        if not self.telegram_notifier.is_room_created_enabled():
            return

        try:
            task = asyncio.create_task(
                self.telegram_notifier.send_room_created(
                    room,
                    share_url=share_url,
                )
            )
            self._notification_tasks.add(task)
            task.add_done_callback(
                lambda completed_task: self._on_notification_task_done(completed_task, room.room_id)
            )
        except Exception:
            logger.exception(
                "failed to schedule room-created notification: room_id=%s",
                room.room_id,
            )

    def _on_notification_task_done(self, task: asyncio.Task, room_id: str) -> None:
        self._notification_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception(
                "room-created notification task failed unexpectedly: room_id=%s",
                room_id,
            )

    def _normalize_meeting_languages(self, meeting_languages: List[str]) -> List[MeetingLanguage]:
        if not meeting_languages:
            return list(DEFAULT_ROOM_MEETING_LANGUAGES)

        if len(meeting_languages) != 2:
            raise InvalidMeetingLanguagesError(
                "meeting_languages must contain exactly 2 languages",
                details={"field": "meeting_languages", "expected": 2},
            )

        if meeting_languages[0] == meeting_languages[1]:
            raise InvalidMeetingLanguagesError(
                "meeting_languages must contain 2 distinct languages",
                details={"field": "meeting_languages", "unique": True},
            )

        supported = set(SUPPORTED_MEETING_LANGUAGES)
        invalid = [lang for lang in meeting_languages if lang not in supported]
        if invalid:
            raise InvalidMeetingLanguagesError(
                "meeting_languages contains unsupported language",
                details={
                    "field": "meeting_languages",
                    "unsupported": invalid,
                    "supported": list(SUPPORTED_MEETING_LANGUAGES),
                },
            )

        return [meeting_languages[0], meeting_languages[1]]

    def _build_brse_virtual_participants(
        self,
        room_id: str,
        timestamp: str,
        meeting_languages: List[MeetingLanguage],
    ) -> List[Dict[str, Any]]:
        return [build_brse_virtual_participant(room_id, timestamp, meeting_languages)]

    async def create_room(
        self,
        meeting_languages: List[str],
        brse_enabled: bool = DEFAULT_BRSE_ENABLED,
    ) -> CreateRoomResponse:
        room_id = self._generate_id("rm")
        now = self._now_str()
        exp = self._exp_str()
        normalized_meeting_languages = self._normalize_meeting_languages(meeting_languages)

        room = RoomState(
            room_id=room_id,
            state="created",
            created_at=now,
            expires_at=exp,
            brse_enabled=brse_enabled,
            participant_limit=None,  # No backend participant cap
            supported_languages=list(SUPPORTED_MEETING_LANGUAGES),
            meeting_languages=normalized_meeting_languages,
            meeting_mode=MEETING_MODE_BRSE_RELAY,
            interpreter_mode=INTERPRETER_MODE_BRSE_PARTICIPANT,
            audio_routing=build_brse_audio_routing(normalized_meeting_languages),
            virtual_participants=(
                self._build_brse_virtual_participants(room_id, now, normalized_meeting_languages)
                if brse_enabled
                else []
            ),
        )
        await self.store.create_room(room)

        await self._publish(EventType.ROOM_CREATED, room_id, room.model_dump())
        if room.virtual_participants:
            for participant in room.virtual_participants:
                await self._publish(EventType.PARTICIPANT_JOINED, room_id, participant)

        share_url = f"/rooms/{room_id}"
        self._schedule_room_created_notification(room, share_url)

        return CreateRoomResponse(
            room=self._room_response_from_state(room),
            join=CreateRoomResponseJoin(
                api_path=f"/api/rooms/{room_id}/join",
                share_url=share_url,
            ),
        )

    async def set_brse_enabled(
        self,
        room_id: str,
        brse_enabled: bool,
        *,
        actor_participant_id: Optional[str],
        session_id: Optional[str],
        reason: str,
    ) -> CreateRoomResponseRoom:
        snapshot = await self.store.get_room_snapshot(room_id)
        if not snapshot:
            raise RoomNotFoundError()

        if not actor_participant_id:
            raise BrseToggleForbiddenError("authenticated participant is required to change BRSE mode")

        actor = await self.store.get_participant(room_id, actor_participant_id)
        if actor is None or actor.status == "disconnected" or actor.is_virtual:
            raise BrseToggleForbiddenError("active human participant is required to change BRSE mode")
        if session_id and actor.session_id != session_id:
            raise BrseToggleForbiddenError("session is no longer valid", code="session_mismatch")

        if snapshot.room.brse_enabled == brse_enabled:
            if not brse_enabled:
                await self.store.update_room(room_id, {"virtual_participants": []})
                await self.store.clear_transcripts(room_id)
            fresh_snapshot = await self.store.get_room_snapshot(room_id)
            if not fresh_snapshot:
                raise RoomNotFoundError()
            return self._room_response_from_state(fresh_snapshot.room)

        now = self._now_str()
        meeting_languages = list(snapshot.room.meeting_languages)
        patch: Dict[str, Any] = {
            "brse_enabled": brse_enabled,
            "meeting_mode": MEETING_MODE_BRSE_RELAY,
            "interpreter_mode": INTERPRETER_MODE_BRSE_PARTICIPANT,
            "audio_routing": build_brse_audio_routing(meeting_languages),
            "virtual_participants": (
                self._build_brse_virtual_participants(room_id, now, meeting_languages)
                if brse_enabled
                else []
            ),
        }
        updated_room = await self.store.update_room(room_id, patch)
        if updated_room is None:
            raise RoomNotFoundError()

        if not brse_enabled:
            await self.store.clear_transcripts(room_id)

        await self._publish(
            EventType.ROOM_BRSE_UPDATED,
            room_id,
            {
                "room_id": room_id,
                "brse_enabled": brse_enabled,
                "timestamp": now,
                "changed_by": actor_participant_id,
                "reason": reason,
            },
        )

        if brse_enabled:
            for participant in updated_room.virtual_participants:
                await self._publish(EventType.PARTICIPANT_JOINED, room_id, participant)
        else:
            await self._publish(
                EventType.PARTICIPANT_LEFT,
                room_id,
                {
                    "participant_id": BRSE_PARTICIPANT_ID,
                    "left_at": now,
                    "reason": "brse_disabled",
                },
            )

        return self._room_response_from_state(updated_room)

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
            recent_messages=snapshot.recent_messages,
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

        # Participant limit check: only enforce if a positive cap is configured
        if (
            snapshot.room.participant_limit is not None
            and snapshot.room.participant_limit > 0
            and active_human_participant_count(snapshot.participants) >= snapshot.room.participant_limit
        ):
            raise RoomFullError()

        # Check room expiry: 30-minute meeting duration
        if self._is_room_expired(snapshot):
            raise RoomExpiredError()

        meeting_pair = list(snapshot.room.meeting_languages)
        if language == "auto" or language not in meeting_pair:
            raise InvalidLanguageError(
                f"language must be one of room meeting_languages: {', '.join(meeting_pair)}",
                details={"field": "language", "meeting_languages": meeting_pair},
            )

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
                expires_at=self._token_exp_str(),
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
                recent_messages=personalized_snapshot.recent_messages,
            ),
        )

    async def send_chat_message(
        self,
        room_id: str,
        participant_id: str,
        session_id: Optional[str],
        text: Any,
        client_event_id: Optional[str] = None,
    ) -> ChatMessage:
        if not isinstance(text, str):
            raise InvalidChatMessageError("text must be a string")

        normalized_text = text.strip()
        if not normalized_text:
            raise InvalidChatMessageError("message text must not be empty", code="empty_chat_message")

        if len(normalized_text) > self.MAX_CHAT_MESSAGE_LENGTH:
            raise InvalidChatMessageError(
                f"message text must be at most {self.MAX_CHAT_MESSAGE_LENGTH} characters",
                code="chat_message_too_long",
            )

        snapshot = await self.store.get_room_snapshot(room_id)
        if not snapshot:
            raise RoomNotFoundError()

        if client_event_id:
            existing_message = next(
                (
                    message
                    for message in snapshot.recent_messages
                    if message.client_event_id == client_event_id
                ),
                None,
            )
            if existing_message is not None:
                return existing_message

        participant = await self.store.get_participant(room_id, participant_id)
        if participant is None:
            raise ParticipantNotFoundError()

        if session_id and participant.session_id != session_id:
            raise InvalidChatMessageError("session is no longer valid", code="session_mismatch")

        if participant.status == "disconnected":
            raise ParticipantNotFoundError()

        if participant.is_virtual:
            raise InvalidChatMessageError("virtual participants cannot send chat", code="chat_not_allowed")

        now = self._now_str()
        message = ChatMessage(
            message_id=self._generate_id("msg"),
            room_id=room_id,
            participant_id=participant.participant_id,
            display_name=participant.display_name,
            language=participant.language,
            text=normalized_text,
            created_at=now,
            client_event_id=client_event_id,
            sender_id=participant.participant_id,
            sender_display_name=participant.display_name,
            sender_language=participant.language,
            sent_at=now,
        )

        await self.store.append_chat_message(room_id, message)
        await self.store.update_participant(
            room_id,
            participant_id,
            {"last_seen_at": now},
        )
        await self._publish(EventType.CHAT_MESSAGE, room_id, message.model_dump())
        return message

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

        meeting_pair = list(snapshot.room.meeting_languages)
        if language == "auto" or language not in meeting_pair:
            raise InvalidLanguageError(
                f"language must be one of room meeting_languages: {', '.join(meeting_pair)}",
                details={"field": "language", "meeting_languages": meeting_pair},
            )

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
            brse_enabled=payload.get("brse_enabled", DEFAULT_BRSE_ENABLED),
            participant_limit=payload.get("participant_limit"),  # None = no cap
            supported_languages=payload["supported_languages"],
            meeting_languages=payload.get("meeting_languages", list(DEFAULT_ROOM_MEETING_LANGUAGES)),
            meeting_mode=payload.get("meeting_mode", MEETING_MODE_BRSE_RELAY),
            interpreter_mode=payload.get("interpreter_mode", INTERPRETER_MODE_BRSE_PARTICIPANT),
            audio_routing=payload["audio_routing"],
        )
