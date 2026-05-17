from types import SimpleNamespace

import pytest

from server.brain.meeting_summary import _build_system_prompt
from server.service.gateway.room_service import (
    InvalidMeetingSummaryLanguageError,
    RoomService,
)
from server.service.gateway.room_store import RoomStore


def _service(fake_settings, fake_redis) -> RoomService:
    return RoomService(RoomStore(fake_redis), fake_settings, fake_redis)


def _snapshot(room_languages, participants=()):
    return SimpleNamespace(
        room=SimpleNamespace(
            room_languages=list(room_languages),
            meeting_languages=list(room_languages),
        ),
        participants=[
            SimpleNamespace(
                participant_id=participant_id,
                language=language,
                is_virtual=False,
            )
            for participant_id, language in participants
        ],
    )


def test_summary_language_explicit_request_wins(fake_settings, fake_redis):
    service = _service(fake_settings, fake_redis)
    language, reason = service._resolve_summary_language(
        requested_language="vi",
        requester_language="ja",
        snapshot=_snapshot(["en", "ja"], [("pt_1", "ja")]),
    )

    assert language == "vi"
    assert reason == "explicit_request"


def test_summary_language_uses_current_participant_before_token(fake_settings, fake_redis):
    service = _service(fake_settings, fake_redis)
    language, reason = service._resolve_summary_language(
        requester_claims={"participant_id": "pt_1", "language": "en"},
        snapshot=_snapshot(["en", "ja"], [("pt_1", "ja")]),
    )

    assert language == "ja"
    assert reason == "authenticated_participant_language"


def test_summary_language_falls_back_to_room_language(fake_settings, fake_redis):
    service = _service(fake_settings, fake_redis)
    language, reason = service._resolve_summary_language(
        snapshot=_snapshot(["ko", "en"]),
    )

    assert language == "ko"
    assert reason == "room_language_fallback"


def test_summary_language_rejects_unsupported_explicit_language(fake_settings, fake_redis):
    service = _service(fake_settings, fake_redis)

    with pytest.raises(InvalidMeetingSummaryLanguageError):
        service._resolve_summary_language(requested_language="de")


def test_summary_prompt_requires_target_language():
    prompt = _build_system_prompt(
        "Vietnamese",
        summary_language="vi",
        summary_type="final",
    )

    assert "Write the summary in Vietnamese." in prompt
    assert "Do not default to English unless target language is English." in prompt
    assert "If the source transcript contains multiple languages" in prompt
