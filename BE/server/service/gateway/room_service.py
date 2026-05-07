import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

from fastapi.encoders import jsonable_encoder
from redis.asyncio import Redis

from server.config import Settings
from server.events import EventType, build_envelope
from server.service.gateway.auth import issue_room_token
from server.service.gateway.livekit_tokens import generate_livekit_token
from server.service.gateway.room_store import RoomStore
from server.integrations.telegram import TelegramNotifier
from server.meeting_modes import (
    BRSE_PARTICIPANT_ID,
    DEFAULT_BRSE_MODE,
    DEFAULT_BRSE_ENABLED,
    DEFAULT_ROOM_MEETING_LANGUAGES,
    INTERPRETER_MODE_BRSE_PARTICIPANT,
    SUPPORTED_MEETING_LANGUAGES,
    active_human_participant_count,
    build_brse_audio_routing,
    build_brse_virtual_participant,
    meeting_mode_for_brse_mode,
    normalize_brse_mode,
)
from server.models import (
    ChatMessage,
    ChatTranslation,
    ChatTranslationMode,
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
    MeetingSummaryResponse,
    MeetingSummaryType,
    MeetingLanguage,
    ParticipantState,
    RoomSnapshotResponse,
    RoomState,
    ScreenShareTrackInfo,
    SnapshotData,
    TranscriptEvent,
)
from server.service.gateway.chat_translator import (
    resolve_chat_target_language,
    translate_chat_message,
)
from server.service.gateway.meeting_summary_service import (
    SUMMARY_TYPE_FINAL,
    SUMMARY_TYPE_INTERIM,
    MeetingSummaryService,
)
from server.service.persistence.room_history import MongoRoomHistoryRepository


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


class MeetingSummaryNotFoundError(Exception):
    pass


class MeetingSummaryUnavailableError(Exception):
    pass


class MeetingSummaryNotReadyError(Exception):
    pass


class InvalidMeetingSummaryTypeError(Exception):
    pass


class InvalidChatMessageError(Exception):
    def __init__(self, message: str, code: str = "invalid_chat_message"):
        super().__init__(message)
        self.code = code


class RoomService:
    MAX_CHAT_MESSAGE_LENGTH = 2000

    def __init__(
        self,
        store: RoomStore,
        settings: Settings,
        redis: Redis,
        room_history: Optional[MongoRoomHistoryRepository] = None,
    ):
        self.store = store
        self.settings = settings
        self.redis = redis
        self.room_history = room_history
        self.gateway_control_channel = settings.redis_channel_gateway_control
        self.telegram_notifier = TelegramNotifier(settings)
        self.meeting_summary_service = MeetingSummaryService(
            settings=settings,
            room_history=room_history,
        )
        self._notification_tasks: set[asyncio.Task] = set()
        self._expiry_summary_tasks: set[asyncio.Task] = set()

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

    def _parse_time(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    def _build_public_app_url(self, path: str) -> str:
        return self._join_url(self.settings.public_app_url, path)

    def _build_public_gateway_ws_url(self, path: str) -> str:
        base_url = self.settings.public_gateway_ws_url
        if not base_url:
            gateway_url = urlsplit(self.settings.public_gateway_url)
            scheme = "wss" if gateway_url.scheme == "https" else "ws"
            base_url = urlunsplit((scheme, gateway_url.netloc, gateway_url.path, "", ""))
        return self._join_url(base_url, path)

    @staticmethod
    def _join_url(base_url: str, path: str) -> str:
        return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))

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

    def _schedule_history(
        self,
        action: str,
        room_id: str,
        operation,
    ) -> None:
        if not self.room_history:
            return
        self.room_history.schedule(operation, action=action, room_id=room_id)

    def _schedule_room_expiry_summary(self, room: RoomState) -> None:
        if not self.room_history:
            return
        expires_at = self._parse_time(room.expires_at)
        if expires_at is None:
            return

        delay_seconds = max((expires_at - datetime.now(timezone.utc)).total_seconds(), 0)
        try:
            task = asyncio.create_task(
                self._persist_room_expiry_after_delay(
                    room.room_id,
                    room.expires_at,
                    delay_seconds,
                )
            )
        except Exception:
            logger.exception("failed to schedule Mongo room expiry summary: room_id=%s", room.room_id)
            return

        self._expiry_summary_tasks.add(task)
        task.add_done_callback(self._on_expiry_summary_task_done)

    async def _persist_room_expiry_after_delay(
        self,
        room_id: str,
        expires_at: str,
        delay_seconds: float,
    ) -> None:
        await asyncio.sleep(delay_seconds)
        if not self.room_history:
            return
        snapshot = await self.store.get_room_snapshot(room_id)
        room = snapshot.room if snapshot else {"room_id": room_id, "expires_at": expires_at, "state": "expired"}
        current_human_count = active_human_participant_count(snapshot.participants) if snapshot else 0
        await self._persist_room_expired_and_summary(
            room,
            expired_at=expires_at,
            current_human_count=current_human_count,
            reason="scheduled_expiry",
        )

    def _on_expiry_summary_task_done(self, task: asyncio.Task) -> None:
        self._expiry_summary_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Mongo room expiry summary task failed unexpectedly")

    def schedule_room_expired_archival(
        self,
        room: Any,
        *,
        expired_at: Optional[str],
        current_human_count: int,
        reason: str,
    ) -> None:
        room_id = self._room_id_from_any(room)
        if room_id == "unknown":
            return

        self._schedule_history(
            "room_expired",
            room_id,
            lambda: self._persist_room_expired_and_summary(
                room,
                expired_at=expired_at,
                current_human_count=current_human_count,
                reason=reason,
            ),
        )

    async def _persist_room_expired_and_summary(
        self,
        room: Any,
        *,
        expired_at: Optional[str],
        current_human_count: int,
        reason: str,
    ) -> None:
        if not self.room_history:
            return
        room_id = self._room_id_from_any(room)
        await self.room_history.persist_room_expired(
            room,
            expired_at=expired_at,
            current_human_count=current_human_count,
            reason=reason,
        )
        await self.meeting_summary_service.generate_for_room_end(
            room_id=room_id,
            trigger_reason=reason,
            ended_at=expired_at,
        )

    async def shutdown_side_effects(self) -> None:
        pending_tasks = list(self._notification_tasks | self._expiry_summary_tasks)
        if not pending_tasks:
            await self.meeting_summary_service.shutdown()
            return
        for task in pending_tasks:
            task.cancel()
        await asyncio.gather(*pending_tasks, return_exceptions=True)
        self._notification_tasks.clear()
        self._expiry_summary_tasks.clear()
        await self.meeting_summary_service.shutdown()

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
                lambda completed_task: self._on_notification_task_done(
                    completed_task,
                    room.room_id,
                    "room-created",
                )
            )
        except Exception:
            logger.exception(
                "failed to schedule room-created notification: room_id=%s",
                room.room_id,
            )

    def _schedule_participant_joined_notification(
        self,
        room: Any,
        participant: ParticipantState,
        *,
        participant_count: int,
    ) -> None:
        if not self.telegram_notifier.is_participant_joined_enabled():
            return

        try:
            task = asyncio.create_task(
                self.telegram_notifier.send_participant_joined(
                    room,
                    participant,
                    participant_count=participant_count,
                )
            )
            self._notification_tasks.add(task)
            task.add_done_callback(
                lambda completed_task: self._on_notification_task_done(
                    completed_task,
                    self._room_id_from_any(room),
                    "participant-joined",
                )
            )
        except Exception:
            logger.exception(
                "failed to schedule participant-joined notification: room_id=%s participant_id=%s",
                self._room_id_from_any(room),
                participant.participant_id,
            )

    def _room_id_from_any(self, room: Any) -> str:
        if hasattr(room, "room_id"):
            return getattr(room, "room_id")
        if isinstance(room, dict):
            return room.get("room_id", "unknown")
        return "unknown"

    def _on_notification_task_done(self, task: asyncio.Task, room_id: str, action: str) -> None:
        self._notification_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception(
                "%s notification task failed unexpectedly: room_id=%s",
                action,
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
        brse_mode: str,
    ) -> List[Dict[str, Any]]:
        return [build_brse_virtual_participant(room_id, timestamp, meeting_languages, brse_mode)]

    async def create_room(
        self,
        meeting_languages: List[str],
        brse_enabled: bool = DEFAULT_BRSE_ENABLED,
        brse_mode: str = DEFAULT_BRSE_MODE,
    ) -> CreateRoomResponse:
        room_id = self._generate_id("rm")
        now = self._now_str()
        exp = self._exp_str()
        normalized_meeting_languages = self._normalize_meeting_languages(meeting_languages)
        normalized_brse_mode = normalize_brse_mode(brse_mode)

        room = RoomState(
            room_id=room_id,
            state="created",
            created_at=now,
            expires_at=exp,
            brse_enabled=brse_enabled,
            brse_mode=normalized_brse_mode,
            participant_limit=None,  # No backend participant cap
            supported_languages=list(SUPPORTED_MEETING_LANGUAGES),
            meeting_languages=normalized_meeting_languages,
            meeting_mode=meeting_mode_for_brse_mode(normalized_brse_mode),
            interpreter_mode=INTERPRETER_MODE_BRSE_PARTICIPANT,
            audio_routing=build_brse_audio_routing(normalized_meeting_languages, normalized_brse_mode),
            virtual_participants=(
                self._build_brse_virtual_participants(
                    room_id,
                    now,
                    normalized_meeting_languages,
                    normalized_brse_mode,
                )
                if brse_enabled
                else []
            ),
        )
        await self.store.create_room(room)

        await self._publish(EventType.ROOM_CREATED, room_id, room.model_dump())
        if room.virtual_participants:
            for participant in room.virtual_participants:
                await self._publish(EventType.PARTICIPANT_JOINED, room_id, participant)

        share_url = self._build_public_app_url(f"/rooms/{room_id}")
        self._schedule_history(
            "room_created",
            room_id,
            lambda: self.room_history.persist_room_created(room, share_url=share_url),
        )
        self._schedule_room_expiry_summary(room)
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
        brse_mode = normalize_brse_mode(getattr(snapshot.room, "brse_mode", DEFAULT_BRSE_MODE))
        patch: Dict[str, Any] = {
            "brse_enabled": brse_enabled,
            "brse_mode": brse_mode,
            "meeting_mode": meeting_mode_for_brse_mode(brse_mode),
            "interpreter_mode": INTERPRETER_MODE_BRSE_PARTICIPANT,
            "audio_routing": build_brse_audio_routing(meeting_languages, brse_mode),
            "virtual_participants": (
                self._build_brse_virtual_participants(room_id, now, meeting_languages, brse_mode)
                if brse_enabled
                else []
            ),
        }
        updated_room = await self.store.update_room(room_id, patch)
        if updated_room is None:
            raise RoomNotFoundError()

        if not brse_enabled:
            await self.store.clear_transcripts(room_id)

        self._schedule_history(
            "room_mode_updated",
            room_id,
            lambda: self.room_history.persist_room_mode_updated(updated_room, changed_at=now),
        )

        await self._publish(
            EventType.ROOM_BRSE_UPDATED,
            room_id,
            {
                "room_id": room_id,
                "brse_enabled": brse_enabled,
                "brse_mode": brse_mode,
                "timestamp": now,
                "changed_by": actor_participant_id,
                "reason": reason,
            },
        )

        if brse_enabled:
            current_human_count = active_human_participant_count(snapshot.participants)
            for participant in updated_room.virtual_participants:
                self._schedule_history(
                    "virtual_participant_joined",
                    room_id,
                    lambda participant=participant: self.room_history.persist_participant_join(
                        updated_room,
                        participant,
                        current_human_count=current_human_count,
                        client_meta=None,
                    ),
                )
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

    async def get_meeting_summary(
        self,
        room_id: str,
        summary_type: MeetingSummaryType = SUMMARY_TYPE_FINAL,
    ) -> MeetingSummaryResponse:
        if not self.room_history or not self.room_history.enabled:
            raise MeetingSummaryNotFoundError()
        normalized_type = self._normalize_summary_type(summary_type)
        logger.info(
            "meeting summary fetch requested: room_id=%s type=%s",
            room_id,
            normalized_type,
        )
        summary = await self.room_history.get_meeting_summary(room_id, summary_type=normalized_type)
        if not summary:
            logger.info(
                "meeting summary fetch miss: room_id=%s type=%s",
                room_id,
                normalized_type,
            )
            raise MeetingSummaryNotFoundError()
        logger.info(
            "meeting summary fetch hit: room_id=%s type=%s status=%s",
            room_id,
            normalized_type,
            summary.get("status"),
        )
        return MeetingSummaryResponse.model_validate(summary)

    async def generate_meeting_summary(
        self,
        room_id: str,
        summary_type: Optional[str] = None,
    ) -> MeetingSummaryResponse:
        if not self.room_history or not self.room_history.enabled:
            raise MeetingSummaryUnavailableError()

        snapshot = await self.store.get_room_snapshot(
            room_id,
            include_silent_transcripts=True,
        )
        raw_room = await self.store.get_room_state(room_id) if snapshot is not None else None
        normalized_type = self._resolve_summary_type(summary_type, snapshot)
        if snapshot is None and not await self.room_history.room_exists(room_id):
            raise RoomNotFoundError()
        logger.info(
            "meeting summary generate requested: room_id=%s type=%s snapshot_state=%s expired=%s",
            room_id,
            normalized_type,
            snapshot.room.state if snapshot is not None else None,
            self._is_room_expired(snapshot) if snapshot is not None else None,
        )
        if normalized_type == SUMMARY_TYPE_INTERIM:
            if snapshot is None:
                raise RoomNotFoundError()
            source = self._build_interim_summary_source(snapshot)
            summary = await self.meeting_summary_service.generate_interim_from_source(
                room_id=room_id,
                source=source,
                trigger_reason="on_demand_interim_refresh",
            )
        else:
            existing_final = await self.room_history.get_meeting_summary(
                room_id,
                summary_type=SUMMARY_TYPE_FINAL,
            )
            if existing_final is not None:
                logger.info(
                    "meeting final summary generate reused existing: room_id=%s status=%s",
                    room_id,
                    existing_final.get("status"),
                )
                return MeetingSummaryResponse.model_validate(existing_final)

            lifecycle_room = raw_room or (snapshot.room if snapshot is not None else None)
            room_state = self._room_value(lifecycle_room, "state")
            is_expired = snapshot is not None and self._is_room_expired(snapshot)
            is_empty = room_state == "empty"
            if snapshot is not None and not is_expired and not is_empty:
                raise MeetingSummaryNotReadyError()

            current_human_count = active_human_participant_count(snapshot.participants) if snapshot is not None else 0
            if snapshot is not None and is_empty:
                emptied_at = (
                    self._room_value(lifecycle_room, "emptied_at")
                    or self._room_value(lifecycle_room, "ended_at")
                )
                await self.room_history.persist_room_emptied(
                    lifecycle_room,
                    emptied_at=emptied_at,
                    current_human_count=current_human_count,
                    reason="on_demand_final_empty",
                )
            if snapshot is not None and is_expired:
                expired_at = (
                    self._room_value(lifecycle_room, "ended_at")
                    or self._room_value(lifecycle_room, "expires_at")
                    or self._room_value(snapshot.room, "expires_at")
                )
                await self.room_history.persist_room_expired(
                    lifecycle_room,
                    expired_at=expired_at,
                    current_human_count=current_human_count,
                    reason="on_demand_final_expired",
                )
            ended_at = self._final_summary_ended_at(
                lifecycle_room,
                is_empty=is_empty,
                is_expired=is_expired,
            )
            summary = await self.meeting_summary_service.generate_for_room_end(
                room_id=room_id,
                trigger_reason="on_demand_final",
                ended_at=ended_at,
            )
        if not summary:
            raise MeetingSummaryNotFoundError()
        return MeetingSummaryResponse.model_validate(summary)

    def _normalize_summary_type(self, summary_type: Optional[str]) -> MeetingSummaryType:
        if summary_type in (None, "", SUMMARY_TYPE_FINAL):
            return SUMMARY_TYPE_FINAL
        if summary_type == SUMMARY_TYPE_INTERIM:
            return SUMMARY_TYPE_INTERIM
        raise InvalidMeetingSummaryTypeError()

    def _resolve_summary_type(
        self,
        summary_type: Optional[str],
        snapshot: Optional[RoomSnapshotResponse],
    ) -> MeetingSummaryType:
        if summary_type:
            return self._normalize_summary_type(summary_type)
        if snapshot is not None and not self._is_room_expired(snapshot) and snapshot.room.state != "empty":
            return SUMMARY_TYPE_INTERIM
        return SUMMARY_TYPE_FINAL

    def _build_interim_summary_source(self, snapshot: RoomSnapshotResponse) -> Dict[str, Any]:
        room = snapshot.room
        max_messages = max(self.settings.meeting_summary_max_source_items, 1)
        transcript_messages = [
            self._summary_source_from_transcript(transcript)
            for transcript in snapshot.recent_transcripts
            if transcript.is_final
        ]
        chat_messages = [
            self._summary_source_from_chat(message)
            for message in snapshot.recent_messages
        ]
        messages = [
            message
            for message in transcript_messages + chat_messages
            if message is not None
        ]
        messages.sort(key=lambda item: item.get("created_at") or "")
        total_count = len(messages)
        messages = messages[-max_messages:]
        first_at = messages[0].get("created_at") if messages else None
        last_at = messages[-1].get("created_at") if messages else None
        duration_seconds = self._duration_seconds(room.created_at, self._now_str())
        source_count = sum(1 for item in messages if item.get("kind") == "source")
        translated_count = sum(1 for item in messages if item.get("kind") == "translated")
        relay_count = sum(1 for item in messages if item.get("kind") == "relay")
        chat_count = sum(1 for item in messages if item.get("kind") == "chat")
        source_stats = {
            "message_count": total_count,
            "transcript_count": source_count + translated_count + relay_count,
            "source_transcript_count": source_count,
            "translated_transcript_count": translated_count,
            "relay_count": relay_count,
            "chat_count": chat_count,
            "included_message_count": len(messages),
            "max_source_items": max_messages,
            "truncated": total_count > len(messages),
        }
        return {
            "room": {
                "room_id": room.room_id,
                "state": room.state,
                "created_at": room.created_at,
                "activated_at": getattr(room, "activated_at", None),
                "ended_at": None,
                "expires_at": room.expires_at,
                "duration_seconds": duration_seconds,
                "meeting_languages": list(room.meeting_languages),
                "brse_enabled": room.brse_enabled,
                "brse_mode": room.brse_mode,
                "meeting_mode": room.meeting_mode,
                "interpreter_mode": room.interpreter_mode,
                "participant_count_total": len([p for p in snapshot.participants if not p.is_virtual]),
                "status_summary": {
                    "state": room.state,
                    "terminal": False,
                    "reason": "live_checkpoint",
                },
            },
            "participants": [
                {
                    "participant_id": participant.participant_id,
                    "display_name": participant.display_name,
                    "language": participant.language,
                    "kind": participant.kind,
                    "is_virtual": participant.is_virtual,
                    "first_joined_at": participant.joined_at,
                    "last_joined_at": participant.joined_at,
                    "last_left_at": None,
                    "join_count": 1,
                }
                for participant in snapshot.participants
                if not participant.is_virtual
            ],
            "messages": messages,
            "source_window": {
                "source": "redis_snapshot",
                "from": first_at,
                "to": last_at,
                "message_count": len(messages),
                "max_messages": max_messages,
            },
            "source_stats": source_stats,
            "duration_seconds": duration_seconds,
        }

    def _summary_source_from_transcript(self, transcript: TranscriptEvent) -> Optional[Dict[str, Any]]:
        text = ""
        if transcript.kind == "source":
            text = transcript.source_text or transcript.text or ""
        elif transcript.kind == "relay":
            text = transcript.brse_text or transcript.text or transcript.translated_text or ""
        elif transcript.kind == "translated":
            text = transcript.translated_text or transcript.text or ""
        else:
            return None
        text = text.strip()
        source_text = (transcript.source_text or "").strip() or None
        if not text and not source_text:
            return None
        return {
            "kind": transcript.kind,
            "conversation_type": "transcript",
            "created_at": transcript.created_at,
            "message_id": transcript.transcript_id,
            "utterance_id": transcript.utterance_id,
            "participant_id": transcript.speaker_id,
            "display_name": transcript.speaker_display_name,
            "language": transcript.speaker_language,
            "src_lang": transcript.src_lang,
            "target_lang": transcript.target_lang,
            "text": text,
            "source_text": source_text,
            "translation_mode": None,
            "translations": [],
        }

    def _summary_source_from_chat(self, message: ChatMessage) -> Optional[Dict[str, Any]]:
        text = (message.text or "").strip()
        if not text:
            return None
        return {
            "kind": "chat",
            "conversation_type": "chat",
            "created_at": message.created_at,
            "message_id": message.message_id,
            "utterance_id": None,
            "participant_id": message.participant_id,
            "display_name": message.display_name,
            "language": message.language,
            "src_lang": message.language,
            "target_lang": None,
            "text": text,
            "source_text": None,
            "translation_mode": message.translation_mode,
            "translations": [translation.model_dump() for translation in message.translations],
        }

    def _duration_seconds(self, start: Optional[str], end: Optional[str]) -> Optional[int]:
        start_dt = self._parse_time(start)
        end_dt = self._parse_time(end)
        if start_dt is None or end_dt is None:
            return None
        return max(int((end_dt - start_dt).total_seconds()), 0)

    def _room_value(self, room: Any, field: str, default: Any = None) -> Any:
        if room is None:
            return default
        if hasattr(room, field):
            return getattr(room, field)
        if isinstance(room, dict):
            return room.get(field, default)
        return default

    def _final_summary_ended_at(
        self,
        room: Any,
        *,
        is_empty: bool,
        is_expired: bool,
    ) -> Optional[str]:
        if is_empty:
            return (
                self._room_value(room, "emptied_at")
                or self._room_value(room, "ended_at")
            )
        if is_expired:
            return (
                self._room_value(room, "ended_at")
                or self._room_value(room, "expires_at")
            )
        return self._room_value(room, "ended_at")

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
            self.schedule_room_expired_archival(
                snapshot.room,
                expired_at=snapshot.room.expires_at,
                current_human_count=active_human_participant_count(snapshot.participants),
                reason="join_rejected_expired",
            )
            raise RoomExpiredError()

        meeting_pair = list(snapshot.room.meeting_languages)
        if language == "auto" or language not in meeting_pair:
            raise InvalidLanguageError(
                f"language must be one of room meeting_languages: {', '.join(meeting_pair)}",
                details={"field": "language", "meeting_languages": meeting_pair},
            )

        now = self._now_str()
        if snapshot.room.state in {"created", "empty"}:
            meta_json = await self.store.client.get(self.store._meta_key(room_id))
            if meta_json:
                room_data = json.loads(meta_json)
                room_data["state"] = "active"
                if not room_data.get("activated_at"):
                    room_data["activated_at"] = now
                room_data["emptied_at"] = None
                await self.store.create_room(RoomState(**room_data))

        participant_id = self._generate_id("pt")
        session_id = self._generate_id("ses")

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
        current_participant_count = active_human_participant_count(fresh_snapshot.participants)
        self._schedule_history(
            "participant_joined",
            room_id,
            lambda: self.room_history.persist_participant_join(
                fresh_snapshot.room,
                participant,
                current_human_count=current_participant_count,
                client_meta=client_meta,
            ),
        )
        self._schedule_participant_joined_notification(
            fresh_snapshot.room,
            participant,
            participant_count=current_participant_count,
        )
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
                url=self._build_public_gateway_ws_url(f"/ws/rooms/{room_id}?token={room_token}"),
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
        translation_mode: ChatTranslationMode = "original_only",
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
        src_lang = participant.language
        meeting_languages = list(snapshot.room.meeting_languages)
        translations: List[Any] = []

        if translation_mode == "translate":
            tgt_lang = resolve_chat_target_language(src_lang, meeting_languages)
            if tgt_lang:
                logger.info(
                    "chat translation: room=%s src=%s tgt=%s mode=translate",
                    room_id,
                    src_lang,
                    tgt_lang,
                )
                translated_text = await translate_chat_message(
                    text=normalized_text,
                    src_lang=src_lang,
                    tgt_lang=tgt_lang,
                    api_key=self.settings.openai_api_key,
                )
                if translated_text is not None:
                    translations = [ChatTranslation(language=tgt_lang, text=translated_text)]
                    logger.info(
                        "chat translation success: room=%s src=%s tgt=%s",
                        room_id,
                        src_lang,
                        tgt_lang,
                    )
                else:
                    logger.warning(
                        "chat translation failed (graceful degradation): room=%s src=%s tgt=%s",
                        room_id,
                        src_lang,
                        tgt_lang,
                    )
            else:
                logger.warning(
                    "chat translation: could not resolve target language: room=%s src=%s meeting_languages=%s",
                    room_id,
                    src_lang,
                    meeting_languages,
                )

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
            translation_mode=translation_mode,
            translations=translations,
        )

        await self.store.append_chat_message(room_id, message)
        await self.store.update_participant(
            room_id,
            participant_id,
            {"last_seen_at": now},
        )
        self._schedule_history(
            "chat_message",
            room_id,
            lambda: self.room_history.persist_chat_message(message, room=snapshot.room),
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
        current_human_count = active_human_participant_count(fresh_snapshot.participants) if fresh_snapshot else 0
        terminal_state = "empty" if fresh_snapshot and current_human_count == 0 else None
        if terminal_state:
            await self.store.mark_room_empty(room_id, emptied_at=now)

        async def persist_left_and_summary() -> None:
            await self.room_history.persist_participant_left(
                room_id,
                participant,
                left_at=now,
                reason=reason,
                current_human_count=current_human_count,
                terminal_state=terminal_state,
            )
            if terminal_state:
                await self.meeting_summary_service.generate_for_room_end(
                    room_id=room_id,
                    trigger_reason=f"{terminal_state}:{reason}",
                    ended_at=now,
                )

        self._schedule_history(
            "participant_left",
            room_id,
            persist_left_and_summary,
        )

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
            brse_mode=payload.get("brse_mode", DEFAULT_BRSE_MODE),
            participant_limit=payload.get("participant_limit"),  # None = no cap
            supported_languages=payload["supported_languages"],
            meeting_languages=payload.get("meeting_languages", list(DEFAULT_ROOM_MEETING_LANGUAGES)),
            meeting_mode=payload.get(
                "meeting_mode",
                meeting_mode_for_brse_mode(payload.get("brse_mode", DEFAULT_BRSE_MODE)),
            ),
            interpreter_mode=payload.get("interpreter_mode", INTERPRETER_MODE_BRSE_PARTICIPANT),
            audio_routing=payload["audio_routing"],
        )
