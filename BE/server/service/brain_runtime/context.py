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
    ) -> None:
        self.room_id = room_id
        self.max_source_turns = max_source_turns
        self.max_relay_outputs = max_relay_outputs
        self.recent_validated_source_turns: list[Dict[str, Any]] = []
        self.recent_relay_outputs: list[RelayOutputRecord] = []
        self.speakers: Dict[str, Dict[str, Any]] = {}

    def reset(self) -> None:
        self.recent_validated_source_turns.clear()
        self.recent_relay_outputs.clear()
        self.speakers.clear()

    def upsert_speaker(self, speaker_id: str, payload: Dict[str, Any]) -> None:
        if not speaker_id:
            return
        current = dict(self.speakers.get(speaker_id) or {})
        current.update(payload)
        self.speakers[speaker_id] = current

    def remove_speaker(self, speaker_id: str) -> None:
        self.speakers.pop(speaker_id, None)

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
