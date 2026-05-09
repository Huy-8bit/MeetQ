from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class SourceTurn:
    utterance_id: str
    speaker_id: str
    speaker_name: str
    src_lang: str
    target_lang: str
    text: str
    created_at: str
    recorded_at: float
    blocked: bool = False
    overlap_window_id: Optional[str] = None
    glossary_hints: Dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> Dict[str, Any]:
        payload = {
            "utterance_id": self.utterance_id,
            "speaker_id": self.speaker_id,
            "speaker_name": self.speaker_name,
            "src_lang": self.src_lang,
            "target_lang": self.target_lang,
            "text": self.text,
            "created_at": self.created_at,
            "recorded_at": self.recorded_at,
            "blocked": self.blocked,
        }
        if self.overlap_window_id:
            payload["overlap_window_id"] = self.overlap_window_id
        if self.glossary_hints:
            payload["glossary_hints"] = self.glossary_hints
        return payload


@dataclass(frozen=True)
class RelayOutputRecord:
    utterance_id: str
    speaker_id: str
    target_lang: str
    text: str
    relay_style: str
    created_at: str
    recorded_at: float


@dataclass
class RelayFocusState:
    speaker_id: Optional[str] = None
    generation: Optional[int] = None
    started_at: Optional[float] = None
    cooldown_until: Optional[float] = None

    def as_payload(self) -> Dict[str, Any]:
        return {
            "speaker_id": self.speaker_id,
            "generation": self.generation,
            "started_at": self.started_at,
            "cooldown_until": self.cooldown_until,
        }


@dataclass(frozen=True)
class RelayDecisionRecord:
    utterance_id: str
    speaker_id: str
    relay_style: str
    decision: str
    reason: str
    overlap_level: str
    delivery_mode: Optional[str]
    recorded_at: float


class RoomContextBuffer:
    """Short-lived room context used by understanding and policy layers.

    Redis and Mongo remain the durable/runtime sources of truth. This buffer is
    intentionally in-memory and bounded; it exists only to help the BRSE runtime
    decide like a meeting participant instead of reacting to isolated lines.
    """

    def __init__(
        self,
        room_id: str,
        *,
        max_source_turns: int = 32,
        max_relay_outputs: int = 32,
        max_relay_decisions: int = 64,
    ) -> None:
        self.room_id = room_id
        self.max_source_turns = max_source_turns
        self.max_relay_outputs = max_relay_outputs
        self.max_relay_decisions = max_relay_decisions
        self.recent_validated_source_turns: list[Dict[str, Any]] = []
        self.recent_relay_outputs: list[RelayOutputRecord] = []
        self.recent_relay_decisions: list[RelayDecisionRecord] = []
        self.speakers: Dict[str, Dict[str, Any]] = {}
        self.relay_focus = RelayFocusState()
        self.overlap_window: Optional[Dict[str, Any]] = None

    def reset(self) -> None:
        self.recent_validated_source_turns.clear()
        self.recent_relay_outputs.clear()
        self.recent_relay_decisions.clear()
        self.speakers.clear()
        self.clear_relay_focus()
        self.clear_overlap_window()

    def upsert_speaker(self, speaker_id: str, payload: Dict[str, Any]) -> None:
        if not speaker_id:
            return
        current = dict(self.speakers.get(speaker_id) or {})
        current.update(payload)
        self.speakers[speaker_id] = current

    def remove_speaker(self, speaker_id: str) -> None:
        self.speakers.pop(speaker_id, None)

    def remove_speaker_runtime_state(self, speaker_id: str, *, keep_speaker: bool = True) -> None:
        if not keep_speaker:
            self.remove_speaker(speaker_id)
        self.recent_validated_source_turns = [
            turn
            for turn in self.recent_validated_source_turns
            if turn.get("speaker_id") != speaker_id
        ]
        self.recent_relay_outputs = [
            item
            for item in self.recent_relay_outputs
            if item.speaker_id != speaker_id
        ]
        self.recent_relay_decisions = [
            item
            for item in self.recent_relay_decisions
            if item.speaker_id != speaker_id
        ]

    def record_source_turn(self, turn: SourceTurn, *, retention_seconds: float) -> Dict[str, Any]:
        payload = turn.as_payload()
        self.recent_validated_source_turns.append(payload)
        self._trim_source_turns(now=turn.recorded_at, retention_seconds=retention_seconds)
        return payload

    def record_relay_output(
        self,
        *,
        utterance_id: str,
        speaker_id: str,
        target_lang: str,
        text: str,
        relay_style: str,
        created_at: str,
    ) -> None:
        self.recent_relay_outputs.append(
            RelayOutputRecord(
                utterance_id=utterance_id,
                speaker_id=speaker_id,
                target_lang=target_lang,
                text=text,
                relay_style=relay_style,
                created_at=created_at,
                recorded_at=time.monotonic(),
            )
        )
        if len(self.recent_relay_outputs) > self.max_relay_outputs:
            self.recent_relay_outputs = self.recent_relay_outputs[-self.max_relay_outputs :]

    def record_relay_decision(
        self,
        *,
        utterance_id: str,
        speaker_id: str,
        relay_style: str,
        decision: str,
        reason: str,
        overlap_level: str,
        delivery_mode: Optional[str] = None,
    ) -> None:
        self.recent_relay_decisions.append(
            RelayDecisionRecord(
                utterance_id=utterance_id,
                speaker_id=speaker_id,
                relay_style=relay_style,
                decision=decision,
                reason=reason,
                overlap_level=overlap_level,
                delivery_mode=delivery_mode,
                recorded_at=time.monotonic(),
            )
        )
        if len(self.recent_relay_decisions) > self.max_relay_decisions:
            self.recent_relay_decisions = self.recent_relay_decisions[-self.max_relay_decisions :]

    def claim_relay_focus(self, *, speaker_id: str, generation: int) -> Optional[str]:
        previous = self.relay_focus.speaker_id
        if previous != speaker_id:
            self.relay_focus.started_at = time.monotonic()
        self.relay_focus.speaker_id = speaker_id
        self.relay_focus.generation = generation
        self.relay_focus.cooldown_until = None
        return previous

    def refresh_relay_focus_generation(self, *, generation: int) -> None:
        self.relay_focus.generation = generation

    def start_relay_focus_cooldown(self, *, cooldown_until: float) -> None:
        self.relay_focus.cooldown_until = cooldown_until

    def clear_relay_focus(self) -> RelayFocusState:
        previous = RelayFocusState(
            speaker_id=self.relay_focus.speaker_id,
            generation=self.relay_focus.generation,
            started_at=self.relay_focus.started_at,
            cooldown_until=self.relay_focus.cooldown_until,
        )
        self.relay_focus = RelayFocusState()
        return previous

    def set_overlap_window(self, payload: Dict[str, Any]) -> None:
        self.overlap_window = dict(payload)

    def clear_overlap_window(self) -> None:
        self.overlap_window = None

    def recent_source_turns(self, *, window_seconds: float, now: Optional[float] = None) -> list[Dict[str, Any]]:
        if now is None:
            now = time.monotonic()
        return [
            turn
            for turn in self.recent_validated_source_turns
            if now - float(turn.get("recorded_at", 0.0)) <= window_seconds
        ]

    def source_turns_by_ids(
        self,
        utterance_ids: Iterable[str],
        *,
        max_items: int,
    ) -> list[Dict[str, Any]]:
        item_ids = set(utterance_ids)
        if not item_ids:
            return []
        return [
            turn
            for turn in self.recent_validated_source_turns
            if turn.get("utterance_id") in item_ids
        ][-max_items:]

    def _trim_source_turns(self, *, now: float, retention_seconds: float) -> None:
        self.recent_validated_source_turns = [
            item
            for item in self.recent_validated_source_turns[-self.max_source_turns :]
            if now - float(item.get("recorded_at", 0.0)) <= retention_seconds
        ]
