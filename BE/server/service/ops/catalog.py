"""Issue catalog: maps raw ops events to stable issue codes for the admin portal.

Classification happens once, when the gateway stores an event, so issue
queries are plain index lookups.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"

# Delivered relays slower than this (end of speech -> final relay text) count as slow.
RELAY_SLOW_THRESHOLD_MS = 6000


@dataclass(frozen=True)
class IssueDefinition:
    code: str
    title: str
    stage: str  # realtime | stt | policy | translation | tts | delivery | summary | chat | config | recording | archive
    severity: str
    description: str


ISSUES: Dict[str, IssueDefinition] = {
    definition.code: definition
    for definition in (
        IssueDefinition(
            "RECORDING_FAILED", "Recording failed", "recording", SEVERITY_ERROR,
            "A meeting recording could not start or finish. The meeting itself was not affected.",
        ),
        IssueDefinition(
            "ARCHIVE_FAILED", "Meeting archive upload failed", "archive", SEVERITY_ERROR,
            "Archiving an ended meeting to S3 failed. It is retried automatically with backoff.",
        ),
        IssueDefinition(
            "ARCHIVE_DELETE_FAILED", "Archive deletion failed", "archive", SEVERITY_ERROR,
            "Deleting an expired or removed meeting archive failed. Cleanup retries on its next run.",
        ),
        IssueDefinition(
            "REALTIME_AUTH_FAILED", "Realtime authentication failed", "realtime", SEVERITY_ERROR,
            "OpenAI Realtime rejected the API key. No speech can be transcribed or relayed.",
        ),
        IssueDefinition(
            "REALTIME_UNAVAILABLE", "Realtime session gave up", "realtime", SEVERITY_ERROR,
            "A speaker's realtime session exhausted its reconnect attempts and stopped.",
        ),
        IssueDefinition(
            "REALTIME_DISCONNECTED", "Realtime disconnected", "realtime", SEVERITY_WARNING,
            "A speaker's realtime session dropped and is reconnecting.",
        ),
        IssueDefinition(
            "MODEL_ERROR", "Model error", "translation", SEVERITY_ERROR,
            "The realtime model returned an error event.",
        ),
        IssueDefinition(
            "AUDIO_TRACK_FAILURE", "AI voice track failure", "tts", SEVERITY_ERROR,
            "BRSE AI could not publish or keep its relay audio track in the meeting.",
        ),
        IssueDefinition(
            "ROUTE_CONFIG_ERROR", "Language routing error", "config", SEVERITY_ERROR,
            "A speaker's language does not match the room languages, so relay is paused.",
        ),
        IssueDefinition(
            "STT_FAILED", "Transcription failed", "stt", SEVERITY_ERROR,
            "Speech was captured but transcription failed.",
        ),
        IssueDefinition(
            "STT_EMPTY", "No speech recognized", "stt", SEVERITY_INFO,
            "Speech activity produced an empty transcript (usually noise).",
        ),
        IssueDefinition(
            "SOURCE_FILTERED", "Speech filtered", "policy", SEVERITY_INFO,
            "Transcript rejected by source validation (filler, noise, too short, unfinished).",
        ),
        IssueDefinition(
            "RELAY_SUPPRESSED_OVERLAP", "Suppressed by overlap", "policy", SEVERITY_INFO,
            "Relay held back because several people were speaking at once.",
        ),
        IssueDefinition(
            "RELAY_SUPPRESSED", "Relay suppressed", "policy", SEVERITY_INFO,
            "Relay policy decided not to publish this utterance.",
        ),
        IssueDefinition(
            "RELAY_TOO_LATE", "Relay too late", "delivery", SEVERITY_WARNING,
            "Relay was dropped because it could not start before the freshness limit.",
        ),
        IssueDefinition(
            "RELAY_REPLACED_BY_SUMMARY", "Replaced by overlap summary", "policy", SEVERITY_INFO,
            "Relay replaced by a short summary of overlapping speech.",
        ),
        IssueDefinition(
            "RELAY_DROPPED", "Relay dropped", "delivery", SEVERITY_WARNING,
            "An approved relay was dropped before delivery.",
        ),
        IssueDefinition(
            "OUTPUT_REJECTED", "Translation output rejected", "translation", SEVERITY_WARNING,
            "The model output failed the output gate (meta text, narrator style, unclear).",
        ),
        IssueDefinition(
            "RELAY_ABANDONED", "Relay abandoned", "delivery", SEVERITY_INFO,
            "Utterance was in flight when the speaker left or their route changed.",
        ),
        IssueDefinition(
            "TTS_NO_AUDIO", "No AI voice for relay", "tts", SEVERITY_WARNING,
            "Relay text was delivered but no AI voice audio was produced.",
        ),
        IssueDefinition(
            "RELAY_SLOW", "Slow relay", "delivery", SEVERITY_WARNING,
            f"Relay delivered more than {RELAY_SLOW_THRESHOLD_MS // 1000}s after the speaker stopped.",
        ),
        IssueDefinition(
            "CAPTION_TRANSLATION_FAILED", "Caption translation failed", "translation", SEVERITY_ERROR,
            "Text caption translation (3+ language rooms) returned no text.",
        ),
        IssueDefinition(
            "CHAT_TRANSLATION_FAILED", "Chat translation failed", "chat", SEVERITY_WARNING,
            "A chat message was sent untranslated because translation failed.",
        ),
        IssueDefinition(
            "SUMMARY_FAILED", "Summary failed", "summary", SEVERITY_ERROR,
            "Meeting summary generation failed.",
        ),
        IssueDefinition(
            "AI_ERROR", "AI runtime error", "realtime", SEVERITY_ERROR,
            "Unclassified BRSE runtime error.",
        ),
    )
}

_OVERLAP_REASON_RE = re.compile(r"overlap", re.IGNORECASE)
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-*]{4,}|Bearer\s+[A-Za-z0-9._\-]+)")
MAX_MESSAGE_CHARS = 300


def sanitize_message(message: Any) -> str:
    """Strip credentials and cap length before an error message is stored or shown."""
    text = str(message or "").strip()
    text = _SECRET_RE.sub("[redacted]", text)
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[: MAX_MESSAGE_CHARS - 1] + "…"
    return text


def classify_relay_trace(trace: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    outcome = trace.get("outcome")
    reason = str(trace.get("reason") or "")
    metrics = trace.get("metrics") or {}

    if outcome == "delivered":
        if trace.get("audio_requested") and not trace.get("audio_delivered"):
            return "TTS_NO_AUDIO", SEVERITY_WARNING
        total_ms = metrics.get("total_ms")
        if isinstance(total_ms, (int, float)) and total_ms >= RELAY_SLOW_THRESHOLD_MS:
            return "RELAY_SLOW", SEVERITY_WARNING
        return None, None
    if outcome == "caption_delivered":
        if reason == "partial_caption_failure":
            return "CAPTION_TRANSLATION_FAILED", SEVERITY_ERROR
        return None, None
    if outcome == "source_rejected":
        return "SOURCE_FILTERED", SEVERITY_INFO
    if outcome == "stt_failed":
        return "STT_FAILED", SEVERITY_ERROR
    if outcome == "stt_empty":
        return "STT_EMPTY", SEVERITY_INFO
    if outcome == "relay_suppressed":
        if _OVERLAP_REASON_RE.search(reason):
            return "RELAY_SUPPRESSED_OVERLAP", SEVERITY_INFO
        return "RELAY_SUPPRESSED", SEVERITY_INFO
    if outcome == "relay_dropped":
        if reason == "stale_public_relay":
            return "RELAY_TOO_LATE", SEVERITY_WARNING
        if reason == "replaced_by_overlap_summary":
            return "RELAY_REPLACED_BY_SUMMARY", SEVERITY_INFO
        if reason == "caption_translation_failed":
            return "CAPTION_TRANSLATION_FAILED", SEVERITY_ERROR
        if reason in {"no_active_cross_language_audience", "same_language_no_translation_required"}:
            return None, None
        return "RELAY_DROPPED", SEVERITY_WARNING
    if outcome == "output_rejected":
        return "OUTPUT_REJECTED", SEVERITY_WARNING
    if outcome == "abandoned":
        return "RELAY_ABANDONED", SEVERITY_INFO
    return None, None


def classify_ai_error(code: Optional[str], message: Optional[str]) -> Tuple[str, str]:
    code = str(code or "")
    lowered = str(message or "").lower()
    if code == "recording_failed":
        return "RECORDING_FAILED", SEVERITY_ERROR
    if code == "archive_failed":
        return "ARCHIVE_FAILED", SEVERITY_ERROR
    if code == "archive_delete_failed":
        return "ARCHIVE_DELETE_FAILED", SEVERITY_ERROR
    if code == "realtime_auth_error":
        return "REALTIME_AUTH_FAILED", SEVERITY_ERROR
    if code == "realtime_unavailable":
        return "REALTIME_UNAVAILABLE", SEVERITY_ERROR
    if code == "realtime_connection_error":
        return "REALTIME_DISCONNECTED", SEVERITY_WARNING
    if code == "caption_translation_failed":
        return "CAPTION_TRANSLATION_FAILED", SEVERITY_ERROR
    if code == "chat_translation_failed":
        return "CHAT_TRANSLATION_FAILED", SEVERITY_WARNING
    if code in {"invalid_language", "missing_room_language_context"}:
        return "ROUTE_CONFIG_ERROR", SEVERITY_ERROR
    if code == "interpreter_unavailable":
        if "audio track" in lowered:
            return "AUDIO_TRACK_FAILURE", SEVERITY_ERROR
        return "MODEL_ERROR", SEVERITY_ERROR
    return "AI_ERROR", SEVERITY_ERROR


def issue_definition(code: str) -> IssueDefinition:
    return ISSUES.get(code) or IssueDefinition(code, code.replace("_", " ").title(), "unknown", SEVERITY_WARNING, "")


def language_pair(src: Optional[str], tgt: Optional[str]) -> Optional[str]:
    if not src or not tgt or src == tgt:
        return None
    return f"{src}>{tgt}"
