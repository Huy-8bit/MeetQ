import json

from server.integrations.telegram import TelegramNotifier
from server.models import RoomState


def test_room_created_notification_message_is_json(fake_settings):
    notifier = TelegramNotifier(fake_settings)
    room = RoomState(
        room_id="rm_json",
        state="created",
        created_at="2026-05-02T09:00:00Z",
        expires_at="2026-05-02T09:30:00Z",
        brse_enabled=True,
        participant_limit=None,
        supported_languages=["vi", "en", "ja"],
        meeting_languages=["vi", "ja"],
    )

    message = notifier._build_room_created_message(
        room,
        share_url="/rooms/rm_json",
        creator_display_name="Nguyen Van A",
        creator_participant_id="pt_creator",
    )

    payload = json.loads(message)

    assert payload == {
        "event": "room.created",
        "room": {
            "room_id": "rm_json",
            "meeting_languages": ["vi", "ja"],
            "brse_enabled": True,
            "created_at": "2026-05-02T09:00:00Z",
            "expires_at": "2026-05-02T09:30:00Z",
            "participant_limit": None,
        },
        "share_url": "/rooms/rm_json",
        "creator": {
            "display_name": "Nguyen Van A",
            "participant_id": "pt_creator",
        },
    }
    assert "New meeting created" not in message
