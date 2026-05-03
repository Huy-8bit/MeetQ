from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from server.brain.prompts.language import PLATFORM_SUPPORTED_LANGS


MEETING_MODE_DIRECT_TRANSLATION = "direct_translation"
MEETING_MODE_BRSE_RELAY = "brse_relay"

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


def build_brse_virtual_participant(
    room_id: str,
    joined_at: Optional[str],
    meeting_languages: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    pair = list(meeting_languages or [])[:2]
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
            "meeting_mode": MEETING_MODE_BRSE_RELAY,
            "interpreter_mode": INTERPRETER_MODE_BRSE_PARTICIPANT,
            "meeting_languages": pair,
            "publishes_audio": True,
            "publishes_video": False,
            "subscribes_human_audio": True,
        },
    }


def build_relay_language_map(meeting_languages: Iterable[str]) -> Dict[str, str]:
    pair = [lang for lang in meeting_languages if isinstance(lang, str)]
    if len(pair) != 2 or pair[0] == pair[1]:
        return dict(DEFAULT_RELAY_LANGUAGE_MAP)
    return {
        pair[0]: pair[1],
        pair[1]: pair[0],
    }


def build_brse_audio_routing(meeting_languages: Iterable[str]) -> Dict[str, Any]:
    relay_map = build_relay_language_map(meeting_languages)
    return {
        "model": "brse_participant_audio",
        "cross_language_remote_audio": "human_original_plus_brse",
        "canonical_remote_audio": "human_original_track",
        "same_language_policy": "human_passthrough",
        "ai_relay_audio": "virtual_participant_track",
        "interpreter_mode": INTERPRETER_MODE_BRSE_PARTICIPANT,
        "bridge_strategy": "speaker_language_map",
        "relay_language_map": relay_map,
        "virtual_participant_id": BRSE_PARTICIPANT_ID,
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
