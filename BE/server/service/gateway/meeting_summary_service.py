from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from server.brain.meeting_summary import generate_meeting_summary
from server.config import Settings
from server.service.persistence.room_history import MongoRoomHistoryRepository


logger = logging.getLogger(__name__)


class MeetingSummaryService:
    """Orchestrates post-meeting summary generation outside the room hot path."""

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
    ) -> None:
        if not self.enabled or self.room_history is None:
            return

        requested_at = self._now_str()
        logger.info(
            "meeting summary requested: room_id=%s trigger=%s ended_at=%s",
            room_id,
            trigger_reason,
            ended_at,
        )

        pending_created = await self.room_history.create_meeting_summary_pending(
            room_id=room_id,
            requested_at=requested_at,
            trigger_reason=trigger_reason,
            summary_language=self.settings.meeting_summary_language,
        )
        if not pending_created:
            logger.info("meeting summary already requested or generated: room_id=%s", room_id)
            return

        try:
            source = await self.room_history.collect_meeting_summary_source(
                room_id,
                max_messages=self.settings.meeting_summary_max_source_items,
            )
            source_stats = source.get("source_stats", {})
            logger.info(
                "meeting summary source collected: room_id=%s transcripts=%s relay=%s chat=%s included=%s",
                room_id,
                source_stats.get("transcript_count", 0),
                source_stats.get("relay_count", 0),
                source_stats.get("chat_count", 0),
                source_stats.get("included_message_count", 0),
            )

            if not _has_summary_content(source):
                generated_at = self._now_str()
                await self.room_history.persist_meeting_summary_skipped(
                    room_id=room_id,
                    generated_at=generated_at,
                    source=source,
                    reason="insufficient_source_content",
                )
                logger.info("meeting summary skipped: room_id=%s reason=insufficient_source_content", room_id)
                return

            summary = await generate_meeting_summary(
                source=source,
                api_key=self.settings.openai_api_key,
                model=self.settings.openai_summary_model,
                summary_language=self.settings.meeting_summary_language,
            )
            generated_at = self._now_str()
            await self.room_history.persist_meeting_summary_completed(
                room_id=room_id,
                generated_at=generated_at,
                summary=summary,
                source=source,
            )
            logger.info("meeting summary generated: room_id=%s", room_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("meeting summary generation failed: room_id=%s", room_id)
            try:
                await self.room_history.persist_meeting_summary_failed(
                    room_id=room_id,
                    failed_at=self._now_str(),
                    error=str(exc),
                )
            except Exception:
                logger.exception("meeting summary failure status persistence failed: room_id=%s", room_id)

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
