from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Set

from server.service.brain_runtime.context import RoomContextBuffer, SourceTurn

logger = logging.getLogger(__name__)


OVERLAP_LEVEL_SINGLE = "single"
OVERLAP_LEVEL_LIGHT = "light"
OVERLAP_LEVEL_HEAVY = "heavy"


@dataclass
class OverlapUnderstandingWindow:
    window_id: str
    opened_at: float
    updated_at: float
    primary_speaker_id: Optional[str] = None
    speaker_ids: Set[str] = field(default_factory=set)
    source_utterance_ids: Set[str] = field(default_factory=set)
    summary_target_langs: Set[str] = field(default_factory=set)
    summary_count: int = 0


class OverlapManager:
    """Room-level understanding component for overlap detection and rescue relay."""

    def __init__(
        self,
        *,
        room_id: str,
        context: RoomContextBuffer,
        recent_window_seconds: float,
        understanding_window_seconds: float,
        summary_min_turns: int,
        summary_min_signal_chars: int,
        summary_max_turns: int,
        chaos_min_summary_turns: int,
        chaos_min_distinct_speakers: int,
        chaos_pending_relay_threshold: int,
        heavy_blocked_speaker_threshold: int,
        summary_max_source_chars: int,
    ) -> None:
        self.room_id = room_id
        self.context = context
        self.recent_window_seconds = recent_window_seconds
        self.understanding_window_seconds = understanding_window_seconds
        self.summary_min_turns = summary_min_turns
        self.summary_min_signal_chars = summary_min_signal_chars
        self.summary_max_turns = summary_max_turns
        self.chaos_min_summary_turns = chaos_min_summary_turns
        self.chaos_min_distinct_speakers = chaos_min_distinct_speakers
        self.chaos_pending_relay_threshold = chaos_pending_relay_threshold
        self.heavy_blocked_speaker_threshold = heavy_blocked_speaker_threshold
        self.summary_max_source_chars = summary_max_source_chars
        self.blocked_speakers: Set[str] = set()
        self.blocked_generations: Dict[str, int] = {}
        self.started_at: Dict[str, float] = {}
        self.window: Optional[OverlapUnderstandingWindow] = None
        self.summary_emitted_keys: Set[tuple[Any, ...]] = set()

    def reset(self) -> None:
        self.blocked_speakers.clear()
        self.blocked_generations.clear()
        self.started_at.clear()
        self.window = None
        self.summary_emitted_keys.clear()

    def is_blocked(self, speaker_id: str, generation: Optional[int] = None) -> bool:
        if generation is not None and self.blocked_generations.get(speaker_id) == generation:
            return True
        return speaker_id in self.blocked_speakers

    def block_speaker(
        self,
        *,
        primary_speaker_id: Optional[str],
        blocked_speaker_id: str,
        generation: int,
    ) -> tuple[OverlapUnderstandingWindow, bool]:
        now = time.monotonic()
        first_block = (
            blocked_speaker_id not in self.blocked_speakers
            or self.blocked_generations.get(blocked_speaker_id) != generation
        )
        self.blocked_speakers.add(blocked_speaker_id)
        self.blocked_generations[blocked_speaker_id] = generation
        self.started_at.setdefault(blocked_speaker_id, now)
        window = self.open_window(
            primary_speaker_id=primary_speaker_id,
            blocked_speaker_id=blocked_speaker_id,
            reason="speech_overlap",
        )
        return window, first_block

    def clear_speaker(self, speaker_id: str) -> None:
        self.blocked_speakers.discard(speaker_id)
        self.blocked_generations.pop(speaker_id, None)
        self.started_at.pop(speaker_id, None)

    def mark_blocked_turn_finished(self, speaker_id: str, generation: int) -> bool:
        if self.blocked_generations.get(speaker_id) != generation:
            return False
        self.blocked_generations.pop(speaker_id, None)
        return True

    def open_window(
        self,
        *,
        primary_speaker_id: Optional[str],
        blocked_speaker_id: str,
        reason: str,
    ) -> OverlapUnderstandingWindow:
        now = time.monotonic()
        window = self.window
        if window is not None and now - window.opened_at > self.understanding_window_seconds:
            self.close_window(reason="window_rotated_before_new_overlap")
            window = None

        if window is None:
            window = OverlapUnderstandingWindow(
                window_id=f"ovl_{uuid.uuid4().hex[:10]}",
                opened_at=now,
                updated_at=now,
                primary_speaker_id=primary_speaker_id,
            )
            self.window = window
            logger.warning(
                "BRSE understanding overlap_window_opened room=%s window=%s primary=%s reason=%s",
                self.room_id,
                window.window_id,
                primary_speaker_id or "-",
                reason,
            )

        window.updated_at = now
        if primary_speaker_id:
            window.speaker_ids.add(primary_speaker_id)
        window.speaker_ids.add(blocked_speaker_id)
        return window

    def current_window(self) -> Optional[OverlapUnderstandingWindow]:
        window = self.window
        if window is None:
            return None
        now = time.monotonic()
        if now - window.opened_at <= self.understanding_window_seconds:
            return window
        self.close_window(reason="window_expired")
        return None

    def close_window(self, *, reason: str, summary_utterance_id: Optional[str] = None) -> None:
        window = self.window
        if window is None:
            return
        age_ms = int(max(0.0, time.monotonic() - window.opened_at) * 1000)
        logger.info(
            "BRSE understanding overlap_window_closed room=%s window=%s reason=%s "
            "age_ms=%d source_items=%d speakers=%d summaries=%d summary_utterance=%s",
            self.room_id,
            window.window_id,
            reason,
            age_ms,
            len(window.source_utterance_ids),
            len(window.speaker_ids),
            window.summary_count,
            summary_utterance_id or "-",
        )
        self.window = None

    def window_turns(self) -> list[Dict[str, Any]]:
        window = self.current_window()
        if window is None or not window.source_utterance_ids:
            return []
        return self.context.source_turns_by_ids(
            window.source_utterance_ids,
            max_items=self.summary_max_turns,
        )

    def recent_overlap_context(self) -> tuple[list[Dict[str, Any]], set[Any]]:
        recent_turns = self.context.recent_source_turns(
            window_seconds=self.recent_window_seconds,
        )
        distinct_speakers = {
            turn.get("speaker_id")
            for turn in recent_turns
            if turn.get("speaker_id")
        }
        return recent_turns, distinct_speakers

    def summary_signal_chars(self, turns: list[Dict[str, Any]]) -> int:
        return sum(
            1
            for turn in turns
            for char in str(turn.get("text") or "")
            if char.isalnum()
        )

    def overlap_level(self, *, pending_relay_count: int) -> str:
        recent_turns, distinct_speakers = self.recent_overlap_context()
        window_turns = self.window_turns()
        window_speakers = {
            turn.get("speaker_id")
            for turn in window_turns
            if turn.get("speaker_id")
        }
        window_has_summary_signal = bool(
            len(window_turns) >= self.summary_min_turns
            and len(window_speakers) >= self.chaos_min_distinct_speakers
            and self.summary_signal_chars(window_turns) >= self.summary_min_signal_chars
        )
        heavy = bool(
            window_has_summary_signal
            or (
                len(recent_turns) >= self.chaos_min_summary_turns
                and len(distinct_speakers) >= self.chaos_min_distinct_speakers
                and (
                    len(self.blocked_speakers) >= self.heavy_blocked_speaker_threshold
                    or pending_relay_count >= self.chaos_pending_relay_threshold
                )
            )
        )
        if heavy:
            return OVERLAP_LEVEL_HEAVY
        if (
            self.blocked_speakers
            or pending_relay_count
            or len(distinct_speakers) >= self.chaos_min_distinct_speakers
            or self.current_window() is not None
        ):
            return OVERLAP_LEVEL_LIGHT
        return OVERLAP_LEVEL_SINGLE

    def record_validated_source_turn(
        self,
        *,
        speaker_id: str,
        speaker_name: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = time.monotonic()
        window = self.current_window()
        overlap_window_id = None
        if window is not None:
            overlap_window_id = window.window_id
            state["overlap_window_id"] = window.window_id
            window.updated_at = now
            window.speaker_ids.add(speaker_id)
            window.source_utterance_ids.add(state["utterance_id"])
            logger.info(
                "BRSE understanding overlap_source_aggregated room=%s window=%s utterance=%s "
                "speaker=%s items=%d speakers=%d blocked=%s",
                self.room_id,
                window.window_id,
                state["utterance_id"],
                speaker_id,
                len(window.source_utterance_ids),
                len(window.speaker_ids),
                state.get("source_blocked_for_overlap", False),
            )

        turn = SourceTurn(
            utterance_id=state["utterance_id"],
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            src_lang=state["src_lang"],
            target_lang=state["target_lang"],
            text=state["source_text"],
            created_at=state["created_at"],
            recorded_at=now,
            blocked=state.get("source_blocked_for_overlap", False),
            overlap_window_id=overlap_window_id,
            glossary_hints=state.get("source_signal", {}).get("technical_terms") or {},
        )
        return self.context.record_source_turn(
            turn,
            retention_seconds=self.recent_window_seconds,
        )

    def overlap_payload(
        self,
        *,
        speaker_id: str,
        overlap_window_ms: Optional[int],
        pending_relay_count: int = 0,
        primary_speaker_id: Optional[str] = None,
        blocked_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        window = self.current_window()
        window_payload = None
        if window is not None:
            age_ms = int(max(0.0, time.monotonic() - window.opened_at) * 1000)
            window_payload = {
                "id": window.window_id,
                "age_ms": age_ms,
                "source_item_count": len(window.source_utterance_ids),
                "speaker_count": len(window.speaker_ids),
                "summary_count": window.summary_count,
                "summary_target_languages": sorted(window.summary_target_langs),
            }
        level = self.overlap_level(pending_relay_count=pending_relay_count)
        return {
            "detected": bool(self.blocked_speakers or window_payload),
            "level": level,
            "speaker_blocked": speaker_id in self.blocked_speakers,
            "primary_speaker_id": primary_speaker_id,
            "blocked_by": blocked_by,
            "blocked_speaker_ids": sorted(self.blocked_speakers),
            "suppressed_speaker_count": len(self.blocked_speakers),
            "overlap_window_ms": overlap_window_ms,
            "chaos": level == OVERLAP_LEVEL_HEAVY,
            "understanding_window": window_payload,
        }

    def build_summary_plan_if_chaotic(
        self,
        *,
        speaker_id: str,
        target_lang: str,
        current_state: Dict[str, Any],
        pending_relay_count: int,
        transcript_states: Dict[str, Dict[str, Any]],
        relay_source_is_active_response: Callable[[str], bool],
    ) -> Optional[Dict[str, Any]]:
        overlap_level = self.overlap_level(pending_relay_count=pending_relay_count)
        if overlap_level != OVERLAP_LEVEL_HEAVY:
            return None

        window = self.current_window()
        window_turns = self.window_turns()
        if window_turns:
            summary_turns = window_turns[-self.summary_max_turns :]
            summary_scope_id = window.window_id if window is not None else "overlap_window"
        else:
            recent_turns, _distinct_speaker_set = self.recent_overlap_context()
            summary_turns = recent_turns[-self.summary_max_turns :]
            summary_scope_id = "recent_overlap"

        distinct_speakers = sorted(
            {str(turn.get("speaker_id")) for turn in summary_turns if turn.get("speaker_id")}
        )
        signal_chars = self.summary_signal_chars(summary_turns)
        if (
            len(summary_turns) < self.summary_min_turns
            or len(distinct_speakers) < self.chaos_min_distinct_speakers
            or signal_chars < self.summary_min_signal_chars
        ):
            return None

        summary_key = (
            target_lang,
            summary_scope_id,
            tuple(turn.get("utterance_id") for turn in summary_turns),
        )
        if summary_key in self.summary_emitted_keys:
            return None

        lines: list[str] = []
        remaining_chars = self.summary_max_source_chars
        for turn in summary_turns:
            text = str(turn.get("text") or "").strip()
            if not text:
                continue
            line = f"- [{turn.get('src_lang')}] {text}"
            if len(line) > remaining_chars:
                line = line[: max(0, remaining_chars - 3)].rstrip() + "..."
            lines.append(line)
            remaining_chars -= len(line)
            if remaining_chars <= 0:
                break
        if len(lines) < self.summary_min_turns:
            return None

        self.summary_emitted_keys.add(summary_key)
        replaced_normal_count = 0
        for turn in summary_turns:
            turn_utterance_id = str(turn.get("utterance_id") or "")
            turn_state = transcript_states.get(turn_utterance_id)
            if (
                turn_state is not None
                and turn_state is not current_state
                and turn_state.get("target_lang") == target_lang
                and turn_state.get("relay_style") == "normal"
                and not turn_state.get("relay_final_published")
                and not relay_source_is_active_response(turn_utterance_id)
            ):
                turn_state["public_relay_approved"] = False
                turn_state["public_relay_reason"] = "replaced_by_overlap_summary"
                replaced_normal_count += 1

        source_text = (
            "Create one short interpreter-style overlap summary relay for the target listeners "
            "from only these validated chronological snippets. Capture the shared gist and "
            "practical meaning. Do not mention participant names, do not list speaker-by-speaker, "
            "and do not narrate the overlap unless unavoidable.\n"
            f"Target language: {target_lang}\n"
            + "\n".join(lines)
        )
        if window is not None:
            window.summary_count += 1
            window.summary_target_langs.add(target_lang)
        logger.warning(
            "BRSE understanding overlap_summary_candidate room=%s speaker=%s target=%s "
            "window=%s items=%d distinct_speakers=%d signal_chars=%d pending_relays=%d "
            "blocked=%d overlap_level=%s replaced_normals=%d",
            self.room_id,
            speaker_id,
            target_lang,
            summary_scope_id,
            len(lines),
            len(distinct_speakers),
            signal_chars,
            pending_relay_count,
            len(self.blocked_speakers),
            overlap_level,
            replaced_normal_count,
        )
        return {
            "source_text": source_text,
            "item_count": len(lines),
            "speaker_ids": distinct_speakers,
            "window_id": summary_scope_id,
            "overlap_level": overlap_level,
            "replaced_normal_count": replaced_normal_count,
        }
