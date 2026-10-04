"""Per-utterance relay trace for operations visibility.

Each utterance's transcript state carries a small ``_trace`` dict of
monotonic milestones. When the utterance reaches a terminal outcome the room
manager publishes one ``ops.relay_trace`` event built by
``build_trace_payload``. The payload holds timings and decisions only — never
transcript text; admin views join text from the transcript archive by
``utterance_id``.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

TRACE_KEY = "_trace"
TRACE_EMITTED_KEY = "_trace_emitted"

# Terminal outcomes.
OUTCOME_DELIVERED = "delivered"
OUTCOME_CAPTION_DELIVERED = "caption_delivered"
OUTCOME_SOURCE_ONLY = "source_only"
OUTCOME_SOURCE_REJECTED = "source_rejected"
OUTCOME_STT_FAILED = "stt_failed"
OUTCOME_STT_EMPTY = "stt_empty"
OUTCOME_SUPERSEDED = "superseded"
OUTCOME_RELAY_SUPPRESSED = "relay_suppressed"
OUTCOME_RELAY_DROPPED = "relay_dropped"
OUTCOME_OUTPUT_REJECTED = "output_rejected"
OUTCOME_ABANDONED = "abandoned"

# Client-side input rejection reasons mapped to trace outcomes.
INPUT_REJECTION_OUTCOMES = {
    "input_transcription_failed": OUTCOME_STT_FAILED,
    "empty_input_transcript": OUTCOME_STT_EMPTY,
    "speech_continued_during_source_quality_hold": OUTCOME_SUPERSEDED,
}


def trace_init(
    state: Dict[str, Any],
    *,
    speech_started_at: Optional[float],
    speech_stopped_at: Optional[float],
    audio_requested: bool,
) -> None:
    committed_at = time.monotonic()
    # Speaker-level VAD timestamps can belong to an earlier turn; keep only a
    # consistent pair that ends before this commit.
    if speech_stopped_at is None or speech_stopped_at > committed_at:
        speech_stopped_at = None
    if speech_started_at is None or (
        speech_stopped_at is not None and speech_started_at > speech_stopped_at
    ):
        speech_started_at = None
    state[TRACE_KEY] = {
        "speech_started_at": speech_started_at,
        "speech_stopped_at": speech_stopped_at,
        "committed_at": committed_at,
        "audio_requested": audio_requested,
    }
    state[TRACE_EMITTED_KEY] = False


def trace_mark(state: Optional[Dict[str, Any]], name: str) -> None:
    """Record the first occurrence of a milestone."""
    if not state:
        return
    trace = state.get(TRACE_KEY)
    if trace is not None and trace.get(name) is None:
        trace[name] = time.monotonic()


def trace_set(state: Optional[Dict[str, Any]], **fields: Any) -> None:
    if not state:
        return
    trace = state.get(TRACE_KEY)
    if trace is not None:
        trace.update(fields)


def _ms(start: Optional[float], end: Optional[float]) -> Optional[int]:
    if start is None or end is None:
        return None
    return max(0, int((end - start) * 1000))


def build_trace_payload(
    state: Dict[str, Any],
    *,
    outcome: str,
    reason: Optional[str],
    speaker_name: str,
) -> Dict[str, Any]:
    trace = dict(state.get(TRACE_KEY) or {})
    now = time.monotonic()
    committed_at = trace.get("committed_at")
    speech_stopped_at = trace.get("speech_stopped_at")
    turn_end_at = speech_stopped_at if speech_stopped_at is not None else committed_at
    response_started_at = trace.get("response_started_at")
    first_audio_at = trace.get("first_audio_at")
    gate_passed_at = trace.get("text_gate_passed_at")
    audio_out_at = None
    if first_audio_at is not None and gate_passed_at is not None:
        audio_out_at = max(first_audio_at, gate_passed_at)
    audio_requested = bool(trace.get("audio_requested"))
    final_published_at = trace.get("final_published_at")

    metrics = {
        "speech_ms": _ms(trace.get("speech_started_at"), speech_stopped_at),
        "stt_ms": _ms(committed_at, trace.get("transcript_completed_at")),
        "policy_ms": _ms(trace.get("transcript_completed_at"), trace.get("policy_at")),
        "queue_ms": _ms(trace.get("policy_at"), response_started_at),
        "first_text_ms": _ms(response_started_at, trace.get("first_text_at")),
        "translation_ms": _ms(response_started_at, trace.get("text_done_at")),
        "first_audio_ms": _ms(response_started_at, first_audio_at),
        "total_ms": _ms(turn_end_at, final_published_at),
        "audio_e2e_ms": _ms(turn_end_at, audio_out_at),
        "age_ms": _ms(turn_end_at, now),
    }
    payload: Dict[str, Any] = {
        "utterance_id": state.get("utterance_id"),
        "speaker_id": state.get("speaker_id"),
        "speaker_name": speaker_name,
        "src_lang": state.get("src_lang"),
        "target_lang": state.get("target_lang"),
        "route_mode": state.get("route_mode"),
        "relay_style": state.get("relay_style") or "normal",
        "overlap_level": state.get("public_relay_overlap_level"),
        "delivery_mode": state.get("delivery_mode"),
        "created_at": state.get("created_at"),
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "outcome": outcome,
        "reason": reason,
        "source_accepted": trace.get("source_accepted"),
        "source_reason": trace.get("source_reason"),
        "policy_decision": trace.get("policy_decision"),
        "policy_reason": trace.get("policy_reason"),
        "translation_requested": response_started_at is not None,
        "audio_requested": audio_requested,
        "audio_delivered": bool(
            audio_requested
            and first_audio_at is not None
            and outcome == OUTCOME_DELIVERED
        ),
        "output_rejected_reason": trace.get("output_rejected_reason"),
        "metrics": metrics,
    }
    captions = trace.get("captions")
    if captions:
        payload["captions"] = list(captions)
    return payload
