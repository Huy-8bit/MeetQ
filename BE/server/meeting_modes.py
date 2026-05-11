from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from server.brain.prompts.language import PLATFORM_SUPPORTED_LANGS


MEETING_MODE_DIRECT_TRANSLATION = "direct_translation"
MEETING_MODE_BRSE_RELAY = "brse_relay"
MEETING_MODE_BRSE_SILENT_SUMMARY = "brse_silent_summary"

BRSE_MODE_RELAY = "relay"
BRSE_MODE_SILENT_SUMMARY = "silent_summary"
DEFAULT_BRSE_MODE = BRSE_MODE_RELAY

BRSE_OUTPUT_MODE_VOICE_TEXT = "voice_text"
BRSE_OUTPUT_MODE_TEXT_ONLY = "text_only"
DEFAULT_BRSE_OUTPUT_MODE = BRSE_OUTPUT_MODE_VOICE_TEXT

INTERPRETER_MODE_PER_LISTENER = "per_listener"
INTERPRETER_MODE_BRSE_PARTICIPANT = "brse_participant"

PARTICIPANT_KIND_HUMAN = "human"
PARTICIPANT_KIND_VIRTUAL_BRSE = "virtual_brse"

BRSE_PARTICIPANT_ID = "brse_ai"
BRSE_PARTICIPANT_DISPLAY_NAME = "BRSE AI"
BRSE_LIVEKIT_IDENTITY_PREFIX = "interp::brse_ai"

DEFAULT_ROOM_MEETING_LANGUAGES = ("vi", "ja")
DEFAULT_BRSE_ENABLED = True
DEFAULT_RELAY_LANGUAGE_MAP: Dict[str, str] = {
    DEFAULT_ROOM_MEETING_LANGUAGES[0]: DEFAULT_ROOM_MEETING_LANGUAGES[1],
    DEFAULT_ROOM_MEETING_LANGUAGES[1]: DEFAULT_ROOM_MEETING_LANGUAGES[0],
}

SUPPORTED_MEETING_LANGUAGES = PLATFORM_SUPPORTED_LANGS


def build_brse_livekit_identity(room_id: str) -> str:
    return f"{BRSE_LIVEKIT_IDENTITY_PREFIX}::{room_id}"


def normalize_brse_mode(value: Optional[str]) -> str:
    if value == BRSE_MODE_SILENT_SUMMARY:
        return BRSE_MODE_SILENT_SUMMARY
    return BRSE_MODE_RELAY


def normalize_brse_output_mode(value: Optional[str]) -> str:
    if value == BRSE_OUTPUT_MODE_TEXT_ONLY:
        return BRSE_OUTPUT_MODE_TEXT_ONLY
    return BRSE_OUTPUT_MODE_VOICE_TEXT


def meeting_mode_for_brse_mode(brse_mode: Optional[str]) -> str:
    if normalize_brse_mode(brse_mode) == BRSE_MODE_SILENT_SUMMARY:
        return MEETING_MODE_BRSE_SILENT_SUMMARY
    return MEETING_MODE_BRSE_RELAY


def brse_relay_text_enabled(brse_enabled: bool, brse_mode: Optional[str]) -> bool:
    return bool(brse_enabled and normalize_brse_mode(brse_mode) == BRSE_MODE_RELAY)


def brse_audio_output_enabled(
    brse_enabled: bool,
    brse_mode: Optional[str],
    brse_output_mode: Optional[str] = DEFAULT_BRSE_OUTPUT_MODE,
) -> bool:
    return bool(
        brse_relay_text_enabled(brse_enabled, brse_mode)
        and normalize_brse_output_mode(brse_output_mode) == BRSE_OUTPUT_MODE_VOICE_TEXT
    )


def brse_output_enabled(
    brse_enabled: bool,
    brse_mode: Optional[str],
    brse_output_mode: Optional[str] = DEFAULT_BRSE_OUTPUT_MODE,
) -> bool:
    return brse_audio_output_enabled(brse_enabled, brse_mode, brse_output_mode)


def build_brse_virtual_participant(
    room_id: str,
    joined_at: Optional[str],
    meeting_languages: Optional[Iterable[str]] = None,
    brse_mode: Optional[str] = DEFAULT_BRSE_MODE,
    brse_output_mode: Optional[str] = DEFAULT_BRSE_OUTPUT_MODE,
) -> Dict[str, Any]:
    room_languages = normalize_room_languages_for_runtime(meeting_languages)
    normalized_mode = normalize_brse_mode(brse_mode)
    normalized_output_mode = normalize_brse_output_mode(brse_output_mode)
    relay_text_enabled = brse_relay_text_enabled(True, normalized_mode)
    audio_enabled = brse_audio_output_enabled(True, normalized_mode, normalized_output_mode)
    return {
        "participant_id": BRSE_PARTICIPANT_ID,
        "display_name": BRSE_PARTICIPANT_DISPLAY_NAME,
        "language": "auto",
        "status": "connected",
        "joined_at": joined_at,
        "kind": PARTICIPANT_KIND_VIRTUAL_BRSE,
        "is_virtual": True,
        "livekit_identity": build_brse_livekit_identity(room_id),
        "metadata": {
            "meeting_mode": meeting_mode_for_brse_mode(normalized_mode),
            "brse_mode": normalized_mode,
            "brse_output_mode": normalized_output_mode,
            "interpreter_mode": INTERPRETER_MODE_BRSE_PARTICIPANT,
            "room_languages": room_languages,
            "meeting_languages": room_languages,
            "publishes_audio": audio_enabled,
            "publishes_text": relay_text_enabled,
            "publishes_video": False,
            "subscribes_human_audio": True,
            "summary_ready": normalized_mode == BRSE_MODE_SILENT_SUMMARY,
            "relay_transcript_policy": "publish_realtime" if relay_text_enabled else "source_only_internal",
        },
    }


def normalize_room_languages_for_runtime(meeting_languages: Optional[Iterable[str]]) -> list[str]:
    normalized: list[str] = []
    supported = set(SUPPORTED_MEETING_LANGUAGES)
    for lang in meeting_languages or []:
        if not isinstance(lang, str) or lang not in supported or lang in normalized:
            continue
        normalized.append(lang)
    return normalized or list(DEFAULT_ROOM_MEETING_LANGUAGES)


def build_relay_language_targets(meeting_languages: Iterable[str]) -> Dict[str, list[str]]:
    room_languages = normalize_room_languages_for_runtime(meeting_languages)
    return {
        source_language: [
            target_language
            for target_language in room_languages
            if target_language != source_language
        ]
        for source_language in room_languages
    }


def build_relay_language_map(meeting_languages: Iterable[str]) -> Dict[str, str]:
    pair = normalize_room_languages_for_runtime(meeting_languages)
    if len(pair) != 2 or pair[0] == pair[1]:
        return {}
    return {
        pair[0]: pair[1],
        pair[1]: pair[0],
    }


def resolve_relay_target_language(
    source_language: Optional[str],
    meeting_languages: Iterable[str],
    *,
    audience_languages: Optional[Iterable[str]] = None,
) -> Optional[str]:
    if source_language is None:
        return None
    room_languages = normalize_room_languages_for_runtime(meeting_languages)
    if source_language not in room_languages:
        return None

    cross_language_targets = [
        language for language in room_languages if language != source_language
    ]
    if not cross_language_targets:
        return None

    if audience_languages is not None:
        audience_language_set = {
            language
            for language in audience_languages
            if isinstance(language, str) and language != source_language
        }
        for language in cross_language_targets:
            if language in audience_language_set:
                return language

    return cross_language_targets[0]


def build_brse_audio_routing(
    meeting_languages: Iterable[str],
    brse_mode: Optional[str] = DEFAULT_BRSE_MODE,
    brse_output_mode: Optional[str] = DEFAULT_BRSE_OUTPUT_MODE,
) -> Dict[str, Any]:
    room_languages = normalize_room_languages_for_runtime(meeting_languages)
    relay_map = build_relay_language_map(room_languages)
    relay_targets = build_relay_language_targets(room_languages)
    normalized_mode = normalize_brse_mode(brse_mode)
    normalized_output_mode = normalize_brse_output_mode(brse_output_mode)
    relay_text_enabled = brse_relay_text_enabled(True, normalized_mode)
    audio_enabled = brse_audio_output_enabled(True, normalized_mode, normalized_output_mode)
    if normalized_mode == BRSE_MODE_SILENT_SUMMARY:
        model = "brse_silent_listener"
    elif audio_enabled:
        model = "brse_participant_audio"
    else:
        model = "brse_text_only_relay"
    suppressed_reason = None
    if relay_text_enabled and not audio_enabled:
        suppressed_reason = "brse_text_only_output_mode"
    elif normalized_mode == BRSE_MODE_SILENT_SUMMARY:
        suppressed_reason = "brse_silent_summary_mode"
    return {
        "model": model,
        "cross_language_remote_audio": "human_original_plus_brse" if audio_enabled else "human_original_only",
        "canonical_remote_audio": "human_original_track",
        "same_language_policy": "human_passthrough",
        "ai_relay_audio": "virtual_participant_track" if audio_enabled else "disabled",
        "interpreter_mode": INTERPRETER_MODE_BRSE_PARTICIPANT,
        "bridge_strategy": "participant_language_preference",
        "relay_language_map": relay_map,
        "relay_language_targets": relay_targets,
        "virtual_participant_id": BRSE_PARTICIPANT_ID,
        "brse_mode": normalized_mode,
        "brse_output_mode": normalized_output_mode,
        "ai_audio_output_enabled": audio_enabled,
        "relay_text_output_enabled": relay_text_enabled,
        "ai_audio_suppressed_reason": suppressed_reason,
        "source_transcript_capture": True,
        "relay_transcript_policy": "publish_realtime" if relay_text_enabled else "source_only_internal",
    }


def relay_target_language(source_language: Optional[str], relay_map: Optional[Dict[str, str]] = None) -> Optional[str]:
    if source_language is None:
        return None
    mapping = relay_map or DEFAULT_RELAY_LANGUAGE_MAP
    return mapping.get(source_language)


def participant_kind(payload: Any) -> Optional[str]:
    if hasattr(payload, "kind"):
        return getattr(payload, "kind")
    if isinstance(payload, dict):
        return payload.get("kind")
    return None


def participant_status(payload: Any) -> Optional[str]:
    if hasattr(payload, "status"):
        return getattr(payload, "status")
    if isinstance(payload, dict):
        return payload.get("status")
    return None


def participant_left_at(payload: Any) -> Optional[str]:
    if hasattr(payload, "left_at"):
        return getattr(payload, "left_at")
    if isinstance(payload, dict):
        return payload.get("left_at")
    return None


def is_virtual_participant(payload: Any) -> bool:
    if hasattr(payload, "is_virtual"):
        return bool(getattr(payload, "is_virtual"))
    if isinstance(payload, dict):
        return bool(payload.get("is_virtual"))
    return participant_kind(payload) == PARTICIPANT_KIND_VIRTUAL_BRSE


def is_active_human_participant(payload: Any) -> bool:
    return (
        not is_virtual_participant(payload)
        and participant_kind(payload) != PARTICIPANT_KIND_VIRTUAL_BRSE
        and participant_status(payload) != "disconnected"
        and participant_left_at(payload) is None
    )


def active_human_participant_count(participants: Iterable[Any]) -> int:
    return sum(1 for payload in participants if is_active_human_participant(payload))
