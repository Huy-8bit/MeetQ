from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from server.brain.realtime.source_policy import (
    assess_public_relay_readiness,
    assess_relay_output_text,
    assess_source_transcript,
    relay_text_has_narrator_opening,
    relay_text_needs_more_opening_context,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceAssessment:
    accepted: bool
    reason: str
    normalized_text: str
    signal: Dict[str, Any]


@dataclass(frozen=True)
class PublicRelayDecision:
    approved: bool
    reason: str
    signal: Dict[str, Any]
    overlap_level: str


@dataclass(frozen=True)
class RelayOutputDecision:
    publishable: bool
    reason: str
    signal: Dict[str, Any]
    hold: bool = False
    reject: bool = False


class ConversationPolicyEngine:
    """Central policy layer for source, relay, and delivery decisions."""

    def __init__(self, room_id: str) -> None:
        self.room_id = room_id

    def assess_source(
        self,
        text: str,
        *,
        duration_ms: Optional[int],
        final: bool,
        speaker_id: str,
        target_lang: Optional[str] = None,
    ) -> SourceAssessment:
        accepted, reason, normalized_text, signal = assess_source_transcript(
            text,
            duration_ms=duration_ms,
            final=final,
        )
        if final or not accepted:
            event_label = "source_final" if final else "source_rejected_partial"
            logger.info(
                "BRSE perception %s room=%s speaker=%s target=%s accepted=%s "
                "reason=%s chars=%d tokens=%s technical=%s",
                event_label,
                self.room_id,
                speaker_id,
                target_lang or "-",
                accepted,
                reason,
                len(normalized_text),
                signal.get("meaningful_tokens"),
                signal.get("technical_terms"),
            )
        return SourceAssessment(
            accepted=accepted,
            reason=reason,
            normalized_text=normalized_text,
            signal=signal,
        )

    def decide_public_relay(
        self,
        *,
        speaker_id: str,
        utterance_id: str,
        source_text: str,
        duration_ms: Optional[int],
        relay_style: str,
        overlap_blocked: bool,
        audience_count: int,
        overlap_level: str,
    ) -> PublicRelayDecision:
        approved, reason, signal = assess_public_relay_readiness(
            source_text,
            duration_ms=duration_ms,
            relay_style=relay_style,
            overlap_blocked=overlap_blocked,
            audience_count=audience_count,
            chaos=overlap_level == "heavy",
            overlap_level=overlap_level,
        )
        logger.info(
            "BRSE policy relay_decision room=%s speaker=%s utterance=%s approved=%s "
            "reason=%s relay_style=%s overlap_level=%s audience=%d",
            self.room_id,
            speaker_id,
            utterance_id,
            approved,
            reason,
            relay_style,
            overlap_level,
            audience_count,
        )
        return PublicRelayDecision(
            approved=approved,
            reason=reason,
            signal=signal,
            overlap_level=overlap_level,
        )

    def decide_relay_output_text(
        self,
        *,
        speaker_id: str,
        utterance_id: str,
        text: str,
        speaker_name: str,
        final: bool,
        relay_style: str,
        min_partial_meaningful_chars: int,
    ) -> RelayOutputDecision:
        output_ok, reason, signal = assess_relay_output_text(text)
        if not output_ok:
            reject = final
            logger.info(
                "BRSE policy output_%s room=%s speaker=%s utterance=%s publishable=False "
                "reason=%s relay_style=%s reject=%s signal=%s",
                "final" if final else "partial",
                self.room_id,
                speaker_id,
                utterance_id,
                reason,
                relay_style,
                reject,
                signal,
            )
            return RelayOutputDecision(
                publishable=False,
                reason=reason,
                signal=signal,
                hold=not final,
                reject=reject,
            )

        if relay_text_has_narrator_opening(text, speaker_name=speaker_name):
            return RelayOutputDecision(
                publishable=False,
                reason="narrator_style_output",
                signal=signal,
                reject=True,
            )

        meaningful_chars = int(signal.get("meaningful_chars") or 0)
        if not final and meaningful_chars < min_partial_meaningful_chars:
            return RelayOutputDecision(
                publishable=False,
                reason="partial_needs_more_meaningful_text",
                signal=signal,
                hold=True,
            )

        if not final and relay_text_needs_more_opening_context(text, speaker_name=speaker_name):
            return RelayOutputDecision(
                publishable=False,
                reason="partial_needs_more_opening_context",
                signal=signal,
                hold=True,
            )

        return RelayOutputDecision(
            publishable=True,
            reason="ok",
            signal=signal,
        )
