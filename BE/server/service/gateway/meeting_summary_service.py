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
MIN_SUMMARY_SIGNAL_RECORDS = 2
MIN_SUMMARY_SIGNAL_CHARS = 80
MIN_RICH_SUMMARY_SIGNAL_CHARS = 140


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
        summary_language: Optional[str] = None,
        language_resolution_reason: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            task = asyncio.create_task(
                self.generate_for_room_end(
                    room_id=room_id,
                    trigger_reason=trigger_reason,
                    ended_at=ended_at,
                    summary_language=summary_language,
                    language_resolution_reason=language_resolution_reason,
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
        summary_language: Optional[str] = None,
        language_resolution_reason: Optional[str] = None,
        refresh: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled or self.room_history is None:
            return None

        requested_at = self._now_str()
        target_language = summary_language or self.settings.meeting_summary_language
        logger.info(
            "meeting final summary requested: room_id=%s trigger=%s ended_at=%s summary_language=%s language_reason=%s",
            room_id,
            trigger_reason,
            ended_at,
            target_language,
            language_resolution_reason or "config_default",
        )

        pending = await self.room_history.create_meeting_summary_pending(
            room_id=room_id,
            summary_type=SUMMARY_TYPE_FINAL,
            requested_at=requested_at,
            trigger_reason=trigger_reason,
            summary_language=target_language,
            source_window={"source": "mongodb_archive", "ended_at": ended_at},
            refresh=refresh,
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
                summary_language=target_language,
                language_resolution_reason=language_resolution_reason,
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
        summary_language: Optional[str] = None,
        language_resolution_reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled or self.room_history is None:
            return None

        requested_at = self._now_str()
        target_language = summary_language or self.settings.meeting_summary_language
        logger.info(
            "meeting interim summary requested: room_id=%s trigger=%s summary_language=%s language_reason=%s",
            room_id,
            trigger_reason,
            target_language,
            language_resolution_reason or "config_default",
        )
        await self.room_history.create_meeting_summary_pending(
            room_id=room_id,
            summary_type=SUMMARY_TYPE_INTERIM,
            requested_at=requested_at,
            trigger_reason=trigger_reason,
            summary_language=target_language,
            source_window=source.get("source_window") or {},
            refresh=True,
        )

        try:
            return await self._generate_and_persist(
                room_id=room_id,
                summary_type=SUMMARY_TYPE_INTERIM,
                source=source,
                summary_language=target_language,
                language_resolution_reason=language_resolution_reason,
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
        summary_language: str,
        language_resolution_reason: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if self.room_history is None:
            return None

        source_stats = dict(source.get("source_stats") or {})
        source_metrics = _summary_source_metrics(source)
        source_stats.update(source_metrics)
        source["source_stats"] = source_stats
        model = self.settings.openai_summary_model
        logger.info(
            "meeting %s recap source collected: room_id=%s summary_language=%s language_reason=%s source_records=%s transcripts=%s relay=%s chat=%s source_chars=%s token_estimate=%s model=%s truncated=%s selection_strategy=%s",
            summary_type,
            room_id,
            summary_language,
            language_resolution_reason or "provided",
            source_stats.get("source_record_count", 0),
            source_stats.get("transcript_count", 0),
            source_stats.get("relay_count", 0),
            source_stats.get("chat_count", 0),
            source_stats.get("source_char_count", 0),
            source_stats.get("source_token_estimate", 0),
            model,
            source_stats.get("truncated", False),
            source_stats.get("selection_strategy"),
        )

        generated_at = self._now_str()
        enough_source, not_enough_reason = _has_summary_content(source, source_metrics=source_metrics)
        if not enough_source:
            await self.room_history.persist_meeting_summary_skipped(
                room_id=room_id,
                summary_type=summary_type,
                generated_at=generated_at,
                source=source,
                reason=not_enough_reason,
                summary_language=summary_language,
            )
            logger.info(
                "meeting %s summary skipped: room_id=%s reason=%s summary_language=%s source_records=%s signal_records=%s signal_chars=%s source_chars=%s token_estimate=%s model=%s",
                summary_type,
                room_id,
                not_enough_reason,
                summary_language,
                source_stats.get("source_record_count", 0),
                source_stats.get("signal_record_count", 0),
                source_stats.get("signal_char_count", 0),
                source_stats.get("source_char_count", 0),
                source_stats.get("source_token_estimate", 0),
                model,
            )
            return await self.room_history.get_meeting_summary(room_id, summary_type=summary_type)

        summary = await generate_meeting_summary(
            source=source,
            api_key=self.settings.openai_api_key,
            model=model,
            summary_language=summary_language,
            summary_type=summary_type,
        )
        generated_at = self._now_str()
        await self.room_history.persist_meeting_summary_completed(
            room_id=room_id,
            summary_type=summary_type,
            generated_at=generated_at,
            summary=summary,
            source=source,
            summary_language=summary_language,
        )
        logger.info(
            "meeting %s recap generated: room_id=%s summary_language=%s model=%s source_records=%s source_chars=%s token_estimate=%s output_chars=%s key_points=%s action_items=%s decisions=%s risks_blockers=%s open_questions=%s next_steps=%s participant_highlights=%s",
            summary_type,
            room_id,
            summary_language,
            model,
            source_stats.get("source_record_count", 0),
            source_stats.get("source_char_count", 0),
            source_stats.get("source_token_estimate", 0),
            _summary_output_char_count(summary),
            len(summary.get("key_points") or []),
            len(summary.get("action_items") or []),
            len(summary.get("decisions") or []),
            len(summary.get("risks_blockers") or []),
            len(summary.get("open_questions") or []),
            len(summary.get("next_steps") or []),
            len(summary.get("participant_highlights") or []),
        )
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


def _has_summary_content(
    source: dict,
    *,
    source_metrics: Optional[Dict[str, int]] = None,
) -> tuple[bool, str]:
    metrics = source_metrics or _summary_source_metrics(source)
    signal_records = metrics.get("signal_record_count", 0)
    signal_chars = metrics.get("signal_char_count", 0)
    if signal_records <= 0:
        return False, "no_source_content"
    if signal_chars >= MIN_RICH_SUMMARY_SIGNAL_CHARS:
        return True, "sufficient_source_content"
    if signal_records >= MIN_SUMMARY_SIGNAL_RECORDS and signal_chars >= MIN_SUMMARY_SIGNAL_CHARS:
        return True, "sufficient_source_content"
    return False, "insufficient_source_content"


def _summary_source_metrics(source: dict) -> Dict[str, int]:
    messages = source.get("messages") or []
    source_char_count = 0
    signal_by_key: Dict[str, int] = {}
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        raw_text = _summary_message_text(message)
        if raw_text:
            source_char_count += len(raw_text)
        signal_text = _summary_message_signal_text(message)
        if not signal_text:
            continue
        signal_key = (
            str(message.get("utterance_id"))
            if message.get("utterance_id")
            else str(message.get("message_id") or index)
        )
        signal_by_key[signal_key] = max(
            signal_by_key.get(signal_key, 0),
            len(signal_text),
        )

    return {
        "source_record_count": len([item for item in messages if isinstance(item, dict)]),
        "source_char_count": source_char_count,
        "source_token_estimate": max((source_char_count + 3) // 4, 0),
        "signal_record_count": len(signal_by_key),
        "signal_char_count": sum(signal_by_key.values()),
    }


def _summary_message_text(message: Dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("source_text", "text"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    translations = message.get("translations")
    if isinstance(translations, list):
        for translation in translations:
            if not isinstance(translation, dict):
                continue
            text = translation.get("text") or translation.get("translated_text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts)


def _summary_message_signal_text(message: Dict[str, Any]) -> str:
    kind = message.get("kind")
    preferred_keys = {
        "source": ("source_text", "text"),
        "relay": ("source_text", "text"),
        "translated": ("source_text", "text"),
        "chat": ("text",),
    }.get(kind, ("source_text", "text"))
    for key in preferred_keys:
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _summary_output_char_count(summary: Dict[str, Any]) -> int:
    total = 0
    for value in summary.values():
        total += _summary_value_char_count(value)
    return total


def _summary_value_char_count(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_summary_value_char_count(item) for item in value)
    if isinstance(value, dict):
        return sum(_summary_value_char_count(item) for item in value.values())
    return 0
