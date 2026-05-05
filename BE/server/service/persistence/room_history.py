from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

try:
    from pymongo import ReturnDocument
except ImportError:  # pragma: no cover - motor/pymongo may be absent when Mongo is disabled.
    class ReturnDocument:
        AFTER = True

from server.models import ChatMessage, ParticipantSnapshot, ParticipantState, RoomState, TranscriptEvent


logger = logging.getLogger(__name__)
ASCENDING = 1
DESCENDING = -1


class MongoRoomHistoryRepository:
    """MongoDB sidecar archive for room history.

    Redis remains the source of truth for active room runtime state. This
    repository only records durable historical copies and never feeds hot room
    decisions.
    """

    rooms_collection = "rooms"
    participants_collection = "room_participants"
    messages_collection = "room_messages"
    summaries_collection = "meeting_summaries"

    def __init__(self, db: Optional[Any]):
        self.db = db
        self._tasks: set[asyncio.Task] = set()

    @property
    def enabled(self) -> bool:
        return self.db is not None

    def schedule(
        self,
        operation: Callable[[], Awaitable[Any]],
        *,
        action: str,
        room_id: str,
    ) -> None:
        if not self.enabled:
            return

        try:
            task = asyncio.create_task(self._run(operation, action=action, room_id=room_id))
        except RuntimeError:
            logger.warning(
                "mongodb persistence skipped: no running event loop; action=%s room_id=%s",
                action,
                room_id,
            )
            return

        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(
        self,
        operation: Callable[[], Awaitable[Any]],
        *,
        action: str,
        room_id: str,
    ) -> None:
        try:
            await operation()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "mongodb persistence failed: action=%s room_id=%s",
                action,
                room_id,
            )

    async def shutdown(self) -> None:
        if not self._tasks:
            return
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def ensure_indexes(self) -> None:
        if not self.enabled:
            return

        await self.db[self.rooms_collection].create_index(
            [("room_id", ASCENDING)],
            unique=True,
            name="uniq_room_id",
        )
        await self.db[self.participants_collection].create_index(
            [("room_id", ASCENDING), ("participant_id", ASCENDING)],
            unique=True,
            name="uniq_room_participant",
        )
        await self.db[self.participants_collection].create_index(
            [("room_id", ASCENDING), ("is_virtual", ASCENDING)],
            name="room_participants_by_kind",
        )
        await self.db[self.messages_collection].create_index(
            [("room_id", ASCENDING), ("created_at", ASCENDING)],
            name="room_messages_chronological",
        )
        await self.db[self.messages_collection].create_index(
            [("room_id", ASCENDING), ("kind", ASCENDING), ("created_at", DESCENDING)],
            name="room_messages_by_kind",
        )
        await self.db[self.messages_collection].create_index(
            [("room_id", ASCENDING), ("message_id", ASCENDING), ("kind", ASCENDING)],
            unique=True,
            name="uniq_room_message_kind",
        )
        await self.db[self.summaries_collection].create_index(
            [("room_id", ASCENDING)],
            unique=True,
            name="uniq_meeting_summary_room_id",
        )
        await self.db[self.summaries_collection].create_index(
            [("status", ASCENDING), ("generated_at", DESCENDING)],
            name="meeting_summaries_by_status",
        )

    async def persist_room_created(self, room: RoomState, *, share_url: Optional[str] = None) -> None:
        now = self._now_str()
        room_doc = self._room_doc_from_state(room, updated_at=now)
        room_doc.update(
            {
                "activated_at": getattr(room, "activated_at", None),
                "emptied_at": getattr(room, "emptied_at", None),
                "ended_at": None,
                "duration_seconds": None,
                "participant_count_current": 0,
                "participant_count_total": 0,
                "participant_ids": [],
                "participant_summaries": [],
                "status_summary": {
                    "state": room.state,
                    "terminal": False,
                    "reason": None,
                },
                "share_url": share_url,
            }
        )

        await self.db[self.rooms_collection].update_one(
            {"room_id": room.room_id},
            {
                "$setOnInsert": {
                    "room_id": room.room_id,
                    "created_at": room.created_at,
                    "created_at_dt": self._parse_dt(room.created_at),
                    "created_by": "gateway",
                },
                "$set": room_doc,
            },
            upsert=True,
        )

        for virtual_participant in room.virtual_participants:
            participant = (
                virtual_participant
                if isinstance(virtual_participant, ParticipantSnapshot)
                else ParticipantSnapshot.model_validate(virtual_participant)
            )
            await self.persist_participant_join(
                room,
                participant,
                current_human_count=0,
                client_meta=None,
            )

    async def persist_room_mode_updated(self, room: Any, *, changed_at: str) -> None:
        room_id = self._value(room, "room_id")
        if not room_id:
            return

        room_doc = self._room_doc_from_state(room, updated_at=self._now_str())
        room_doc["status_summary"] = {
            "state": self._value(room, "state", "active"),
            "terminal": False,
            "reason": "brse_updated",
        }

        await self.db[self.rooms_collection].update_one(
            {"room_id": room_id},
            {
                "$setOnInsert": {
                    "room_id": room_id,
                    "created_at": self._value(room, "created_at"),
                    "created_at_dt": self._parse_dt(self._value(room, "created_at")),
                    "created_by": "gateway",
                },
                "$set": room_doc | {"last_event_at": changed_at},
            },
            upsert=True,
        )

    async def persist_participant_join(
        self,
        room: Any,
        participant: Any,
        *,
        current_human_count: int,
        client_meta: Optional[Any],
    ) -> None:
        room_id = self._value(room, "room_id")
        participant_id = self._value(participant, "participant_id")
        if not room_id or not participant_id:
            return

        joined_at = self._value(participant, "joined_at") or self._now_str()
        is_virtual = bool(self._value(participant, "is_virtual", False))
        kind = self._value(participant, "kind", "virtual_brse" if is_virtual else "human")
        session_id = self._value(participant, "session_id")
        now = self._now_str()
        participant_doc = {
            "room_id": room_id,
            "participant_id": participant_id,
            "display_name": self._value(participant, "display_name"),
            "language": self._value(participant, "language"),
            "kind": kind,
            "is_virtual": is_virtual,
            "livekit_identity": self._value(participant, "livekit_identity"),
            "metadata": self._value(participant, "metadata", {}) or {},
            "last_joined_at": joined_at,
            "last_joined_at_dt": self._parse_dt(joined_at),
            "last_seen_at": self._value(participant, "last_seen_at") or joined_at,
            "updated_at": now,
            "updated_at_dt": self._parse_dt(now),
        }
        session_doc = {
            "session_id": session_id,
            "joined_at": joined_at,
            "joined_at_dt": self._parse_dt(joined_at),
            "left_at": None,
            "left_at_dt": None,
            "status": self._value(participant, "status", "connected"),
            "client": self._model_dump(client_meta),
        }

        await self.db[self.participants_collection].update_one(
            {"room_id": room_id, "participant_id": participant_id},
            {
                "$setOnInsert": {
                    "first_joined_at": joined_at,
                    "first_joined_at_dt": self._parse_dt(joined_at),
                    "created_at": now,
                    "created_at_dt": self._parse_dt(now),
                },
                "$set": participant_doc,
                "$inc": {"join_count": 1},
                "$push": {"sessions": session_doc},
            },
            upsert=True,
        )

        await self._refresh_room_participant_summary(
            room,
            current_human_count=current_human_count,
            clear_terminal=not is_virtual,
        )

    async def persist_participant_left(
        self,
        room_id: str,
        participant: ParticipantState,
        *,
        left_at: str,
        reason: str,
        current_human_count: int,
        terminal_state: Optional[str],
    ) -> None:
        now = self._now_str()
        update: Dict[str, Any] = {
            "$set": {
                "last_left_at": left_at,
                "last_left_at_dt": self._parse_dt(left_at),
                "last_seen_at": left_at,
                "updated_at": now,
                "updated_at_dt": self._parse_dt(now),
            }
        }
        array_filters = None
        if participant.session_id:
            update["$set"].update(
                {
                    "sessions.$[session].left_at": left_at,
                    "sessions.$[session].left_at_dt": self._parse_dt(left_at),
                    "sessions.$[session].status": "disconnected",
                    "sessions.$[session].reason": reason,
                }
            )
            array_filters = [{"session.session_id": participant.session_id, "session.left_at": None}]

        kwargs: Dict[str, Any] = {}
        if array_filters:
            kwargs["array_filters"] = array_filters

        await self.db[self.participants_collection].update_one(
            {"room_id": room_id, "participant_id": participant.participant_id},
            update,
            **kwargs,
        )

        await self._update_room_lifecycle_summary(
            room_id,
            state=terminal_state or "active",
            ended_at=left_at if terminal_state else None,
            reason=reason if terminal_state else None,
            current_human_count=current_human_count,
            terminal=bool(terminal_state),
        )

    async def persist_room_expired(
        self,
        room: Any,
        *,
        expired_at: Optional[str] = None,
        current_human_count: int = 0,
        reason: str = "expired",
    ) -> None:
        room_id = self._value(room, "room_id")
        if not room_id:
            return
        existing = await self.db[self.rooms_collection].find_one(
            {"room_id": room_id},
            {"_id": 0, "ended_at": 1, "status_summary": 1},
        )
        if existing and existing.get("ended_at") and (existing.get("status_summary") or {}).get("terminal"):
            return

        timestamp = expired_at or self._value(room, "expires_at") or self._now_str()
        await self._update_room_lifecycle_summary(
            room_id,
            state="expired",
            ended_at=timestamp,
            reason=reason,
            current_human_count=current_human_count,
            terminal=True,
        )

    async def persist_chat_message(self, message: ChatMessage, *, room: Optional[Any] = None) -> None:
        created_at = message.created_at or self._now_str()
        doc = {
            "room_id": message.room_id,
            "message_id": message.message_id,
            "conversation_type": "chat",
            "kind": "chat",
            "participant_id": message.participant_id,
            "display_name": message.display_name,
            "language": message.language,
            "text": message.text,
            "created_at": created_at,
            "created_at_dt": self._parse_dt(created_at),
            "client_event_id": message.client_event_id,
            "translation_mode": message.translation_mode,
            "translations": [translation.model_dump() for translation in message.translations],
            "metadata": {
                "sender_id": message.sender_id,
                "sender_display_name": message.sender_display_name,
                "sender_language": message.sender_language,
                "sent_at": message.sent_at,
            },
        }
        result = await self.db[self.messages_collection].update_one(
            {"room_id": message.room_id, "message_id": message.message_id, "kind": "chat"},
            {"$setOnInsert": doc},
            upsert=True,
        )
        if room is not None and result.upserted_id is not None:
            await self.db[self.rooms_collection].update_one(
                {"room_id": message.room_id},
                {
                    "$setOnInsert": {
                        "room_id": message.room_id,
                        "created_by": "gateway",
                    },
                    "$set": {
                        "last_message_at": created_at,
                        "last_event_at": created_at,
                        "updated_at": self._now_str(),
                    },
                    "$inc": {"message_count": 1, "chat_message_count": 1},
                },
                upsert=True,
            )

    async def persist_transcript(self, room_id: str, transcript: TranscriptEvent, *, room: Optional[Any] = None) -> None:
        created_at = transcript.created_at or self._now_str()
        message_id = transcript.transcript_id or f"transcript_{uuid.uuid4().hex[:12]}"
        doc = {
            "room_id": room_id,
            "message_id": message_id,
            "transcript_id": transcript.transcript_id,
            "utterance_id": transcript.utterance_id,
            "conversation_type": "transcript",
            "kind": transcript.kind,
            "participant_id": transcript.speaker_id,
            "display_name": transcript.speaker_display_name,
            "language": transcript.speaker_language,
            "text": transcript.text,
            "created_at": created_at,
            "created_at_dt": self._parse_dt(created_at),
            "source_text": transcript.source_text,
            "translated_text": transcript.translated_text,
            "brse_text": transcript.brse_text,
            "src_lang": transcript.src_lang,
            "target_lang": transcript.target_lang,
            "listener_id": transcript.listener_id,
            "is_final": transcript.is_final,
            "fallback_used": transcript.fallback_used,
            "audio_track_name": transcript.audio_track_name,
            "audio_output": transcript.audio_output,
            "relay_mode": transcript.relay_mode,
            "relay_style": transcript.relay_style,
            "metadata": {
                "speaker": self._model_dump(transcript.speaker),
                "original_speaker": self._model_dump(transcript.original_speaker),
                "listener": transcript.listener,
                "brse_participant": self._model_dump(transcript.brse_participant),
                "relay_target": self._model_dump(transcript.relay_target),
            },
        }
        result = await self.db[self.messages_collection].update_one(
            {"room_id": room_id, "message_id": message_id, "kind": transcript.kind},
            {"$setOnInsert": doc},
            upsert=True,
        )
        if result.upserted_id is not None:
            await self.db[self.rooms_collection].update_one(
                {"room_id": room_id},
                {
                    "$setOnInsert": {
                        "room_id": room_id,
                        "created_by": "gateway",
                    },
                    "$set": {
                        "last_message_at": created_at,
                        "last_event_at": created_at,
                        "updated_at": self._now_str(),
                    },
                    "$inc": {
                        "message_count": 1,
                        "transcript_message_count": 1,
                        f"transcript_kind_counts.{transcript.kind}": 1,
                    },
                },
                upsert=True,
            )

    async def create_meeting_summary_pending(
        self,
        *,
        room_id: str,
        requested_at: str,
        trigger_reason: str,
        summary_language: str,
    ) -> bool:
        summary_id = f"sum_{uuid.uuid4().hex[:12]}"
        doc = {
            "summary_id": summary_id,
            "room_id": room_id,
            "status": "pending",
            "created_at": requested_at,
            "created_at_dt": self._parse_dt(requested_at),
            "generated_at": None,
            "generated_at_dt": None,
            "summary_language": summary_language,
            "summary_text": None,
            "highlights": [],
            "decisions": [],
            "action_items": [],
            "participant_summary": [],
            "duration_seconds": None,
            "source_stats": {},
            "trigger_reason": trigger_reason,
            "error": None,
            "updated_at": requested_at,
            "updated_at_dt": self._parse_dt(requested_at),
        }
        result = await self.db[self.summaries_collection].update_one(
            {"room_id": room_id},
            {"$setOnInsert": doc},
            upsert=True,
        )
        if result.upserted_id is None:
            return False

        await self.db[self.rooms_collection].update_one(
            {"room_id": room_id},
            {
                "$setOnInsert": {
                    "room_id": room_id,
                    "created_by": "gateway",
                },
                "$set": {
                    "meeting_summary": {
                        "summary_id": summary_id,
                        "status": "pending",
                        "created_at": requested_at,
                        "generated_at": None,
                        "summary_language": summary_language,
                        "trigger_reason": trigger_reason,
                    },
                    "updated_at": requested_at,
                    "updated_at_dt": self._parse_dt(requested_at),
                },
            },
            upsert=True,
        )
        return True

    async def collect_meeting_summary_source(
        self,
        room_id: str,
        *,
        max_messages: int,
    ) -> Dict[str, Any]:
        room_doc = await self.db[self.rooms_collection].find_one(
            {"room_id": room_id},
            {"_id": 0},
        ) or {"room_id": room_id}
        participant_docs = await self.db[self.participants_collection].find(
            {"room_id": room_id, "is_virtual": {"$ne": True}},
            {
                "_id": 0,
                "participant_id": 1,
                "display_name": 1,
                "language": 1,
                "kind": 1,
                "is_virtual": 1,
                "first_joined_at": 1,
                "last_joined_at": 1,
                "last_left_at": 1,
                "join_count": 1,
            },
        ).sort("first_joined_at_dt", ASCENDING).to_list(length=None)

        kind_filter = {"$in": ["source", "translated", "relay", "chat"]}
        total_count = await self.db[self.messages_collection].count_documents(
            {"room_id": room_id, "kind": kind_filter}
        )
        source_count = await self.db[self.messages_collection].count_documents(
            {"room_id": room_id, "kind": "source"}
        )
        translated_count = await self.db[self.messages_collection].count_documents(
            {"room_id": room_id, "kind": "translated"}
        )
        relay_count = await self.db[self.messages_collection].count_documents(
            {"room_id": room_id, "kind": "relay"}
        )
        chat_count = await self.db[self.messages_collection].count_documents(
            {"room_id": room_id, "kind": "chat"}
        )
        message_docs = await self.db[self.messages_collection].find(
            {"room_id": room_id, "kind": kind_filter},
            {"_id": 0},
        ).sort("created_at_dt", ASCENDING).limit(max(max_messages, 1)).to_list(length=max(max_messages, 1))
        messages = [
            summary_message
            for message in message_docs
            if (summary_message := self._summary_source_message(message)) is not None
        ]
        duration_seconds = room_doc.get("duration_seconds")
        if duration_seconds is None:
            duration_seconds = self._duration_seconds(
                room_doc.get("activated_at") or room_doc.get("created_at"),
                room_doc.get("ended_at") or room_doc.get("expires_at"),
            )

        source_stats = {
            "message_count": total_count,
            "transcript_count": source_count + translated_count + relay_count,
            "source_transcript_count": source_count,
            "translated_transcript_count": translated_count,
            "relay_count": relay_count,
            "chat_count": chat_count,
            "included_message_count": len(messages),
            "max_source_items": max_messages,
            "truncated": total_count > len(message_docs),
        }
        return {
            "room": self._summary_room_doc(room_doc, duration_seconds=duration_seconds),
            "participants": participant_docs,
            "messages": messages,
            "source_stats": source_stats,
            "duration_seconds": duration_seconds,
        }

    async def persist_meeting_summary_completed(
        self,
        *,
        room_id: str,
        generated_at: str,
        summary: Dict[str, Any],
        source: Dict[str, Any],
    ) -> None:
        source_stats = source.get("source_stats") or {}
        duration_seconds = source.get("duration_seconds")
        update_doc = {
            "status": "completed",
            "generated_at": generated_at,
            "generated_at_dt": self._parse_dt(generated_at),
            "summary_text": summary.get("summary_text") or "",
            "highlights": summary.get("highlights") or [],
            "decisions": summary.get("decisions") or [],
            "action_items": summary.get("action_items") or [],
            "participant_summary": summary.get("participant_summary") or [],
            "duration_seconds": duration_seconds,
            "source_stats": source_stats,
            "error": None,
            "updated_at": generated_at,
            "updated_at_dt": self._parse_dt(generated_at),
        }
        result = await self.db[self.summaries_collection].find_one_and_update(
            {"room_id": room_id},
            {"$set": update_doc},
            return_document=ReturnDocument.AFTER,
        )
        summary_id = (result or {}).get("summary_id")
        await self._update_room_meeting_summary_status(
            room_id,
            summary_id=summary_id,
            status="completed",
            timestamp=generated_at,
            summary_language=(result or {}).get("summary_language"),
            source_stats=source_stats,
        )

    async def persist_meeting_summary_skipped(
        self,
        *,
        room_id: str,
        generated_at: str,
        source: Dict[str, Any],
        reason: str,
    ) -> None:
        source_stats = source.get("source_stats") or {}
        duration_seconds = source.get("duration_seconds")
        update_doc = {
            "status": "skipped",
            "generated_at": generated_at,
            "generated_at_dt": self._parse_dt(generated_at),
            "summary_text": "Not enough meeting content was available to generate a grounded summary.",
            "highlights": [],
            "decisions": [],
            "action_items": [],
            "participant_summary": [],
            "duration_seconds": duration_seconds,
            "source_stats": source_stats,
            "error": reason,
            "updated_at": generated_at,
            "updated_at_dt": self._parse_dt(generated_at),
        }
        result = await self.db[self.summaries_collection].find_one_and_update(
            {"room_id": room_id},
            {"$set": update_doc},
            return_document=ReturnDocument.AFTER,
        )
        summary_id = (result or {}).get("summary_id")
        await self._update_room_meeting_summary_status(
            room_id,
            summary_id=summary_id,
            status="skipped",
            timestamp=generated_at,
            summary_language=(result or {}).get("summary_language"),
            source_stats=source_stats,
            error=reason,
        )

    async def persist_meeting_summary_failed(
        self,
        *,
        room_id: str,
        failed_at: str,
        error: str,
    ) -> None:
        update_doc = {
            "status": "failed",
            "generated_at": failed_at,
            "generated_at_dt": self._parse_dt(failed_at),
            "error": error[:1000],
            "updated_at": failed_at,
            "updated_at_dt": self._parse_dt(failed_at),
        }
        result = await self.db[self.summaries_collection].find_one_and_update(
            {"room_id": room_id},
            {"$set": update_doc},
            return_document=ReturnDocument.AFTER,
        )
        summary_id = (result or {}).get("summary_id")
        await self._update_room_meeting_summary_status(
            room_id,
            summary_id=summary_id,
            status="failed",
            timestamp=failed_at,
            summary_language=(result or {}).get("summary_language"),
            source_stats=(result or {}).get("source_stats") or {},
            error=error[:1000],
        )

    async def get_meeting_summary(self, room_id: str) -> Optional[Dict[str, Any]]:
        doc = await self.db[self.summaries_collection].find_one(
            {"room_id": room_id},
            {"_id": 0},
        )
        return doc

    async def _refresh_room_participant_summary(
        self,
        room: Any,
        *,
        current_human_count: int,
        clear_terminal: bool,
    ) -> None:
        room_id = self._value(room, "room_id")
        if not room_id:
            return

        participant_docs = await self.db[self.participants_collection].find(
            {"room_id": room_id, "is_virtual": {"$ne": True}},
            {
                "_id": 0,
                "participant_id": 1,
                "display_name": 1,
                "language": 1,
                "kind": 1,
                "is_virtual": 1,
                "first_joined_at": 1,
                "last_joined_at": 1,
                "last_left_at": 1,
                "join_count": 1,
            },
        ).to_list(length=None)
        participant_ids = [doc["participant_id"] for doc in participant_docs if doc.get("participant_id")]
        update_doc = self._room_doc_from_state(room, updated_at=self._now_str())
        update_doc.update(
            {
                "participant_count_current": current_human_count,
                "participant_count_total": len(participant_ids),
                "participant_ids": participant_ids,
                "participant_summaries": participant_docs,
                "last_event_at": self._now_str(),
            }
        )
        if clear_terminal:
            update_doc.update(
                {
                    "state": "active",
                    "ended_at": None,
                    "duration_seconds": None,
                    "status_summary": {
                        "state": "active",
                        "terminal": False,
                        "reason": None,
                    },
                }
            )
            if not self._value(room, "activated_at"):
                activated_at = self._now_str()
                update_doc["activated_at"] = activated_at
                update_doc["activated_at_dt"] = self._parse_dt(activated_at)

        await self.db[self.rooms_collection].update_one(
            {"room_id": room_id},
            {
                "$setOnInsert": {
                    "room_id": room_id,
                    "created_at": self._value(room, "created_at"),
                    "created_at_dt": self._parse_dt(self._value(room, "created_at")),
                    "created_by": "gateway",
                },
                "$set": update_doc,
            },
            upsert=True,
        )

    async def _update_room_lifecycle_summary(
        self,
        room_id: str,
        *,
        state: str,
        ended_at: Optional[str],
        reason: Optional[str],
        current_human_count: int,
        terminal: bool,
    ) -> None:
        if terminal and ended_at:
            current = await self.db[self.rooms_collection].find_one(
                {"room_id": room_id},
                {"_id": 0, "last_event_at": 1},
            )
            current_event_at = self._parse_dt((current or {}).get("last_event_at"))
            next_event_at = self._parse_dt(ended_at)
            if current_event_at is not None and next_event_at is not None and current_event_at > next_event_at:
                return

        existing = await self.db[self.rooms_collection].find_one_and_update(
            {"room_id": room_id},
            {
                "$setOnInsert": {
                    "room_id": room_id,
                    "created_by": "gateway",
                },
                "$set": {
                    "state": state,
                    "ended_at": ended_at,
                    "ended_at_dt": self._parse_dt(ended_at),
                    "participant_count_current": current_human_count,
                    "status_summary": {
                        "state": state,
                        "terminal": terminal,
                        "reason": reason,
                    },
                    "last_event_at": ended_at or self._now_str(),
                    "updated_at": self._now_str(),
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        activated_at = existing.get("activated_at") or existing.get("created_at")
        duration_seconds = self._duration_seconds(activated_at, ended_at)
        if duration_seconds is not None:
            await self.db[self.rooms_collection].update_one(
                {"room_id": room_id},
                {"$set": {"duration_seconds": duration_seconds}},
            )

    def _room_doc_from_state(self, room: Any, *, updated_at: str) -> Dict[str, Any]:
        room_id = self._value(room, "room_id")
        created_at = self._value(room, "created_at")
        expires_at = self._value(room, "expires_at")
        return {
            "room_id": room_id,
            "state": self._value(room, "state"),
            "created_at": created_at,
            "created_at_dt": self._parse_dt(created_at),
            "activated_at": self._value(room, "activated_at"),
            "activated_at_dt": self._parse_dt(self._value(room, "activated_at")),
            "emptied_at": self._value(room, "emptied_at"),
            "emptied_at_dt": self._parse_dt(self._value(room, "emptied_at")),
            "expires_at": expires_at,
            "expires_at_dt": self._parse_dt(expires_at),
            "ended_at": self._value(room, "ended_at"),
            "ended_at_dt": self._parse_dt(self._value(room, "ended_at")),
            "meeting_languages": list(self._value(room, "meeting_languages", []) or []),
            "brse_enabled": bool(self._value(room, "brse_enabled", False)),
            "brse_mode": self._value(room, "brse_mode"),
            "meeting_mode": self._value(room, "meeting_mode"),
            "interpreter_mode": self._value(room, "interpreter_mode"),
            "audio_routing": self._model_dump(self._value(room, "audio_routing", {})),
            "virtual_participants": [
                self._model_dump(participant)
                for participant in self._value(room, "virtual_participants", []) or []
            ],
            "updated_at": updated_at,
            "updated_at_dt": self._parse_dt(updated_at),
        }

    def _participant_summary(self, participant: Any) -> Dict[str, Any]:
        return {
            "participant_id": self._value(participant, "participant_id"),
            "display_name": self._value(participant, "display_name"),
            "language": self._value(participant, "language"),
            "kind": self._value(participant, "kind"),
            "is_virtual": bool(self._value(participant, "is_virtual", False)),
            "joined_at": self._value(participant, "joined_at"),
            "left_at": self._value(participant, "left_at"),
        }

    def _summary_source_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        kind = message.get("kind")
        text = ""
        source_text = message.get("source_text") or None
        if kind == "chat":
            text = message.get("text") or ""
        elif kind == "source":
            text = message.get("source_text") or message.get("text") or ""
        elif kind == "relay":
            text = message.get("brse_text") or message.get("text") or message.get("translated_text") or ""
        elif kind == "translated":
            text = message.get("translated_text") or message.get("text") or ""
        else:
            return None

        text = text.strip() if isinstance(text, str) else ""
        if not text and not source_text:
            return None

        return {
            "kind": kind,
            "conversation_type": message.get("conversation_type"),
            "created_at": message.get("created_at"),
            "message_id": message.get("message_id"),
            "utterance_id": message.get("utterance_id"),
            "participant_id": message.get("participant_id"),
            "display_name": message.get("display_name"),
            "language": message.get("language"),
            "src_lang": message.get("src_lang"),
            "target_lang": message.get("target_lang"),
            "text": text,
            "source_text": source_text,
            "translation_mode": message.get("translation_mode"),
            "translations": message.get("translations") or [],
        }

    def _summary_room_doc(self, room_doc: Dict[str, Any], *, duration_seconds: Optional[int]) -> Dict[str, Any]:
        return {
            "room_id": room_doc.get("room_id"),
            "state": room_doc.get("state"),
            "created_at": room_doc.get("created_at"),
            "activated_at": room_doc.get("activated_at"),
            "ended_at": room_doc.get("ended_at"),
            "expires_at": room_doc.get("expires_at"),
            "duration_seconds": duration_seconds,
            "meeting_languages": room_doc.get("meeting_languages") or [],
            "brse_enabled": room_doc.get("brse_enabled"),
            "brse_mode": room_doc.get("brse_mode"),
            "meeting_mode": room_doc.get("meeting_mode"),
            "interpreter_mode": room_doc.get("interpreter_mode"),
            "participant_count_total": room_doc.get("participant_count_total"),
            "status_summary": room_doc.get("status_summary") or {},
        }

    async def _update_room_meeting_summary_status(
        self,
        room_id: str,
        *,
        summary_id: Optional[str],
        status: str,
        timestamp: str,
        summary_language: Optional[str],
        source_stats: Dict[str, Any],
        error: Optional[str] = None,
    ) -> None:
        meeting_summary = {
            "summary_id": summary_id,
            "status": status,
            "generated_at": timestamp,
            "summary_language": summary_language,
            "source_stats": source_stats,
        }
        if error:
            meeting_summary["error"] = error
        await self.db[self.rooms_collection].update_one(
            {"room_id": room_id},
            {
                "$setOnInsert": {
                    "room_id": room_id,
                    "created_by": "gateway",
                },
                "$set": {
                    "meeting_summary": meeting_summary,
                    "updated_at": timestamp,
                    "updated_at_dt": self._parse_dt(timestamp),
                },
            },
            upsert=True,
        )

    def _value(self, obj: Any, field: str, default: Any = None) -> Any:
        if hasattr(obj, field):
            return getattr(obj, field)
        if isinstance(obj, dict):
            return obj.get(field, default)
        return default

    def _model_dump(self, value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, dict):
            return {key: self._model_dump(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._model_dump(item) for item in value]
        return value

    def _now_str(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _parse_dt(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    def _duration_seconds(self, start: Optional[str], end: Optional[str]) -> Optional[int]:
        start_dt = self._parse_dt(start)
        end_dt = self._parse_dt(end)
        if start_dt is None or end_dt is None:
            return None
        return max(int((end_dt - start_dt).total_seconds()), 0)
