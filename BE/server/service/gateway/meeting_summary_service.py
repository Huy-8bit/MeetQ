from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from server.brain.meeting_summary import generate_meeting_summary
from server.config import Settings
from server.service.persistence.room_history import MongoRoomHistoryRepository


logger = logging.getLogger(__name__)

SUMMARY_TYPE_INTERIM = "interim"
SUMMARY_TYPE_FINAL = "final"


class MeetingSummaryService:
    """Orchestrates interim and final meeting summary generation."""

    def __init__(
        self,
        *,
        settings: Settings,
        room_history: Optional[MongoRoomHistoryRepository],
    ):
        self.settings = settings
        self.room_history = room_history
        self._tasks: set[asyncio.Task] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.room_history and self.room_history.enabled)

    def schedule_for_room_end(
        self,
        *,
        room_id: str,
        trigger_reason: str,
        ended_at: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            task = asyncio.create_task(
                self.generate_for_room_end(
                    room_id=room_id,
                    trigger_reason=trigger_reason,
                    ended_at=ended_at,
                )
            )
        except RuntimeError:
            logger.warning(
                "meeting summary skipped: no running event loop; room_id=%s trigger=%s",
                room_id,
                trigger_reason,
            )
            return

        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    async def generate_for_room_end(
        self,
        *,
        room_id: str,
        trigger_reason: str,
        ended_at: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled or self.room_history is None:
            return None

        requested_at = self._now_str()
        logger.info(
            "meeting final summary requested: room_id=%s trigger=%s ended_at=%s",
            room_id,
            trigger_reason,
            ended_at,
        )

        pending = await self.room_history.create_meeting_summary_pending(
            room_id=room_id,
            summary_type=SUMMARY_TYPE_FINAL,
            requested_at=requested_at,
            trigger_reason=trigger_reason,
            summary_language=self.settings.meeting_summary_language,
            source_window={"source": "mongodb_archive", "ended_at": ended_at},
            refresh=False,
        )
        if pending is None:
            logger.info("meeting final summary already requested or generated: room_id=%s", room_id)
            return await self.room_history.get_meeting_summary(room_id, summary_type=SUMMARY_TYPE_FINAL)

        try:
            source = await self.room_history.collect_meeting_summary_source(
                room_id,
                max_messages=self.settings.meeting_summary_max_source_items,
            )
            return await self._generate_and_persist(
                room_id=room_id,
                summary_type=SUMMARY_TYPE_FINAL,
                source=source,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._persist_failure(
                room_id=room_id,
                summary_type=SUMMARY_TYPE_FINAL,
                exc=exc,
            )
            return await self.room_history.get_meeting_summary(room_id, summary_type=SUMMARY_TYPE_FINAL)

    async def generate_interim_from_source(
        self,
        *,
        room_id: str,
        source: Dict[str, Any],
        trigger_reason: str,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled or self.room_history is None:
            return None

        requested_at = self._now_str()
        logger.info(
            "meeting interim summary requested: room_id=%s trigger=%s",
            room_id,
            trigger_reason,
        )
        await self.room_history.create_meeting_summary_pending(
            room_id=room_id,
            summary_type=SUMMARY_TYPE_INTERIM,
            requested_at=requested_at,
            trigger_reason=trigger_reason,
            summary_language=self.settings.meeting_summary_language,
            source_window=source.get("source_window") or {},
            refresh=True,
        )

        try:
            return await self._generate_and_persist(
                room_id=room_id,
                summary_type=SUMMARY_TYPE_INTERIM,
                source=source,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._persist_failure(
                room_id=room_id,
                summary_type=SUMMARY_TYPE_INTERIM,
                exc=exc,
            )
            return await self.room_history.get_meeting_summary(room_id, summary_type=SUMMARY_TYPE_INTERIM)

    async def _generate_and_persist(
        self,
        *,
        room_id: str,
        summary_type: str,
        source: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if self.room_history is None:
            return None

        source_stats = source.get("source_stats", {})
        logger.info(
            "meeting %s summary source collected: room_id=%s transcripts=%s relay=%s chat=%s included=%s",
            summary_type,
            room_id,
            source_stats.get("transcript_count", 0),
            source_stats.get("relay_count", 0),
            source_stats.get("chat_count", 0),
            source_stats.get("included_message_count", 0),
        )

        generated_at = self._now_str()
        if not _has_summary_content(source):
            await self.room_history.persist_meeting_summary_skipped(
                room_id=room_id,
                summary_type=summary_type,
                generated_at=generated_at,
                source=source,
                reason="insufficient_source_content",
            )
            logger.info(
                "meeting %s summary skipped: room_id=%s reason=insufficient_source_content",
                summary_type,
                room_id,
            )
            return await self.room_history.get_meeting_summary(room_id, summary_type=summary_type)

        summary = await generate_meeting_summary(
            source=source,
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_summary_model,
            summary_language=self.settings.meeting_summary_language,
            summary_type=summary_type,
        )
        generated_at = self._now_str()
        await self.room_history.persist_meeting_summary_completed(
            room_id=room_id,
            summary_type=summary_type,
            generated_at=generated_at,
            summary=summary,
            source=source,
        )
        logger.info("meeting %s summary generated: room_id=%s", summary_type, room_id)
        return await self.room_history.get_meeting_summary(room_id, summary_type=summary_type)

    async def _persist_failure(
        self,
        *,
        room_id: str,
        summary_type: str,
        exc: Exception,
    ) -> None:
        logger.exception("meeting %s summary generation failed: room_id=%s", summary_type, room_id)
        if self.room_history is None:
            return
        try:
            await self.room_history.persist_meeting_summary_failed(
                room_id=room_id,
                summary_type=summary_type,
                failed_at=self._now_str(),
                error=str(exc),
            )
        except Exception:
            logger.exception(
                "meeting %s summary failure status persistence failed: room_id=%s",
                summary_type,
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

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("meeting summary task failed unexpectedly")

    def _now_str(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _has_summary_content(source: dict) -> bool:
    messages = source.get("messages") or []
    for message in messages:
        if isinstance(message, dict) and (message.get("text") or message.get("source_text")):
            return True
    return False
