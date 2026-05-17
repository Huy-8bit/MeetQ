from server.brain.meeting_summary import (
    _build_user_prompt,
    _normalize_summary_payload,
)
from server.service.gateway.meeting_summary_service import (
    _has_summary_content,
    _summary_source_metrics,
)
from server.service.persistence.room_history import _summary_sample_offsets


def test_summary_source_rejects_thin_content():
    source = {
        "messages": [
            {
                "kind": "source",
                "utterance_id": "utt_1",
                "source_text": "Hello.",
            }
        ]
    }

    metrics = _summary_source_metrics(source)
    enough, reason = _has_summary_content(source, source_metrics=metrics)

    assert enough is False
    assert reason == "insufficient_source_content"
    assert metrics["signal_record_count"] == 1


def test_summary_source_accepts_grounded_mixed_language_smoke():
    source = {
        "room": {"room_id": "rm_quality", "room_languages": ["vi", "en"]},
        "messages": [
            {
                "kind": "source",
                "utterance_id": "utt_1",
                "display_name": "Huy",
                "source_text": (
                    "Team decided to keep Redis cache for /api/rooms/{room_id}/summary "
                    "and increase model output tokens because summaries are missing decisions."
                ),
            },
            {
                "kind": "source",
                "utterance_id": "utt_2",
                "display_name": "Lan",
                "source_text": (
                    "Lan sẽ sửa Docker compose healthcheck trước Friday; blocker hiện tại "
                    "là Mongo migration thỉnh thoảng fail trong CI/CD."
                ),
            },
            {
                "kind": "chat",
                "message_id": "chat_1",
                "display_name": "Minh",
                "text": "Open question: should k8s deploy wait for database migration?",
            },
        ],
    }

    metrics = _summary_source_metrics(source)
    enough, reason = _has_summary_content(source, source_metrics=metrics)
    prompt = _build_user_prompt(source, summary_type="final")

    assert enough is True
    assert reason == "sufficient_source_content"
    assert metrics["signal_record_count"] == 3
    assert "Redis" in prompt
    assert "/api/rooms/{room_id}/summary" in prompt
    assert "Docker compose healthcheck" in prompt
    assert "CI/CD" in prompt
    assert "k8s" in prompt


def test_summary_payload_normalizes_new_structured_sections_and_action_details():
    normalized = _normalize_summary_payload(
        {
            "summary_text": "Team discussed Redis summary quality.",
            "key_points": ["Redis cache affects final summary lookup."],
            "decisions": ["Keep the existing summary API response fields."],
            "action_item_details": [
                {
                    "text": "Lan will fix Docker compose healthcheck.",
                    "owner": "Lan",
                    "due": "Friday",
                },
                {
                    "text": "Review CI/CD migration ordering.",
                },
            ],
            "risks_blockers": ["Mongo migration fails in CI/CD."],
            "open_questions": ["Should k8s deploy wait for database migration?"],
            "next_steps": ["Run a smoke summary with mixed Vietnamese and English."],
            "participant_highlights": [
                {
                    "participant_id": "pt_lan",
                    "display_name": "Lan",
                    "summary": "Lan owned the Docker healthcheck follow-up.",
                }
            ],
        }
    )

    assert normalized["action_items"] == [
        "Lan will fix Docker compose healthcheck.",
        "Review CI/CD migration ordering.",
    ]
    assert normalized["action_item_details"] == [
        {
            "text": "Lan will fix Docker compose healthcheck.",
            "owner": "Lan",
            "due": "Friday",
        },
        {
            "text": "Review CI/CD migration ordering.",
            "owner": None,
            "due": None,
        },
    ]
    assert normalized["risks_blockers"] == ["Mongo migration fails in CI/CD."]
    assert normalized["open_questions"] == ["Should k8s deploy wait for database migration?"]
    assert normalized["next_steps"] == ["Run a smoke summary with mixed Vietnamese and English."]


def test_summary_sample_offsets_cover_start_middle_and_end():
    offsets = _summary_sample_offsets(total_count=1000, max_messages=10)

    assert len(offsets) == 10
    assert offsets[0] == 0
    assert offsets[-1] == 999
    assert any(400 <= offset <= 600 for offset in offsets)
    assert offsets == sorted(set(offsets))
