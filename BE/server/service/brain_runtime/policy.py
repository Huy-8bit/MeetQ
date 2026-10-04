from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from server.brain.realtime.source_policy import (
    SOURCE_UNBOUND_OUTPUT_REASONS,
    assess_public_relay_readiness,
    assess_relay_output_text,
    assess_source_transcript,
    relay_text_has_narrator_opening,
    relay_text_needs_more_opening_context,
    weighted_text_length,
)

logger = logging.getLogger(__name__)

# Sources shorter than this (CJK-weighted chars) release text/audio only after
# the complete relay text passed validation.
SHORT_SOURCE_FINAL_TEXT_GATE_CHARS = 60


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
    relay_style: str


@dataclass(frozen=True)
class RelayCandidateDecision:
    relay_style: str
    source_text: str
    reason: str
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class OverlapSummaryDecision:
    approved: bool
    reason: str
    signal: Dict[str, Any]


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
                "reason=%s chars=%d tokens=%s technical=%s detected_terms=%s",
                event_label,
                self.room_id,
                speaker_id,
                target_lang or "-",
                accepted,
                reason,
                len(normalized_text),
                signal.get("meaningful_tokens"),
                signal.get("technical_terms"),
                signal.get("detected_terms"),
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
        if (
            not approved
            and relay_style == "normal"
            and overlap_blocked
            and overlap_level == "light"
            and reason == "overlap_blocked_literal_relay_suppressed"
        ):
            meaningful_chars = int(signal.get("meaningful_chars") or 0)
            meaningful_tokens = int(signal.get("meaningful_tokens") or 0)
            if meaningful_chars >= 5 and meaningful_tokens >= 1:
                approved = True
                reason = "light_overlap_delayed_normal_relay"
                signal["light_overlap_delayed"] = True
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
            relay_style=relay_style,
        )

    def select_relay_candidate(
        self,
        *,
        speaker_id: str,
        utterance_id: str,
        normalized_source_text: str,
        overlap_blocked: bool,
        overlap_level: str,
        summary_plan: Optional[Dict[str, Any]],
    ) -> RelayCandidateDecision:
        if summary_plan is not None:
            summary_decision = self.decide_overlap_summary_relay(
                speaker_id=speaker_id,
                utterance_id=utterance_id,
                summary_plan=summary_plan,
                overlap_level=overlap_level,
            )
            if summary_decision.approved:
                logger.info(
                    "BRSE policy candidate_selected room=%s speaker=%s utterance=%s "
                    "relay_style=summary reason=%s overlap_level=%s overlap_blocked=%s",
                    self.room_id,
                    speaker_id,
                    utterance_id,
                    summary_decision.reason,
                    overlap_level,
                    overlap_blocked,
                )
                return RelayCandidateDecision(
                    relay_style="summary",
                    source_text=str(summary_plan.get("source_text") or ""),
                    reason=summary_decision.reason,
                    metadata={
                        "summary_item_count": summary_plan.get("item_count", 0),
                        "summary_speaker_ids": summary_plan.get("speaker_ids", []),
                        "summary_window_id": summary_plan.get("window_id"),
                        "summary_signal": summary_decision.signal,
                    },
                )

        reason = "normal_single_speaker_relay"
        if overlap_blocked:
            reason = "overlap_delayed_normal_candidate"
        logger.info(
            "BRSE policy candidate_selected room=%s speaker=%s utterance=%s "
            "relay_style=normal reason=%s overlap_level=%s overlap_blocked=%s",
            self.room_id,
            speaker_id,
            utterance_id,
            reason,
            overlap_level,
            overlap_blocked,
        )
        return RelayCandidateDecision(
            relay_style="normal",
            source_text=normalized_source_text,
            reason=reason,
            metadata={},
        )

    def decide_overlap_summary_relay(
        self,
        *,
        speaker_id: str,
        utterance_id: str,
        summary_plan: Dict[str, Any],
        overlap_level: str,
    ) -> OverlapSummaryDecision:
        source_text = str(summary_plan.get("source_text") or "").strip()
        item_count = int(summary_plan.get("item_count") or 0)
        speaker_count = len(summary_plan.get("speaker_ids") or [])
        signal = {
            "chars": len(source_text),
            "item_count": item_count,
            "speaker_count": speaker_count,
            "overlap_level": overlap_level,
            "window_id": summary_plan.get("window_id"),
            "replaced_normal_count": summary_plan.get("replaced_normal_count", 0),
        }
        approved = bool(source_text and item_count >= 2 and speaker_count >= 2)
        reason = "overlap_summary_selected" if approved else "overlap_summary_insufficient_source"
        logger.info(
            "BRSE policy overlap_summary_decision room=%s speaker=%s utterance=%s "
            "approved=%s reason=%s signal=%s",
            self.room_id,
            speaker_id,
            utterance_id,
            approved,
            reason,
            signal,
        )
        return OverlapSummaryDecision(
            approved=approved,
            reason=reason,
            signal=signal,
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
        source_text: Optional[str] = None,
    ) -> RelayOutputDecision:
        output_ok, reason, signal = assess_relay_output_text(
            text,
            source_text=source_text,
            final=final,
            relay_style=relay_style,
        )
        if not output_ok:
            # A reply-style or over-long partial cannot become a translation by
            # growing, so it is rejected at once to stop its audio early.
            reject = final or reason in SOURCE_UNBOUND_OUTPUT_REASONS
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

        if (
            not final
            and source_text is not None
            and relay_style != "summary"
            and weighted_text_length(source_text) < SHORT_SOURCE_FINAL_TEXT_GATE_CHARS
        ):
            # Short sources yield short translations: wait for the complete text
            # so a reply-style response is rejected before any of its audio plays.
            return RelayOutputDecision(
                publishable=False,
                reason="short_source_waits_for_final_text",
                signal=signal,
                hold=True,
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

        logger.info(
            "BRSE policy output_%s room=%s speaker=%s utterance=%s publishable=True "
            "reason=ok relay_style=%s chars=%d",
            "final" if final else "partial",
            self.room_id,
            speaker_id,
            utterance_id,
            relay_style,
            len(text.strip()),
        )
        return RelayOutputDecision(
            publishable=True,
            reason="ok",
            signal=signal,
        )
