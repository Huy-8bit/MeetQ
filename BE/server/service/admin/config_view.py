"""Read-only view of the configuration that actually drives MeetQ.

Values come from ``Settings`` (environment) or from code constants; the
``source`` field says which. Nothing here is runtime-editable (v1).
"""
from __future__ import annotations

from server.config import Settings
from server.meeting_modes import SUPPORTED_MEETING_LANGUAGES
from server.service.admin.metrics import LANGUAGE_LABELS
from server.service.admin.schemas import AdminConfigResponse, ConfigItem
from server.service.gateway.room_service import RoomService

ENV = "environment"
CODE_BE = "backend constant"
CODE_FE = "frontend constant"

# Mirrors of frontend constants (FE/src). Kept here only to display them.
FE_EXPIRY_WARNING_SECONDS = 5 * 60
FE_RELAY_PANEL_VISIBLE_LINES = 25
FE_DISPLAY_NAME_MAX_LENGTH = 40


def build_admin_config(settings: Settings) -> AdminConfigResponse:
    telegram_ready = bool(
        settings.telegram_notifications_enabled
        and settings.telegram_bot_token
        and settings.telegram_chat_id
    )
    return AdminConfigResponse(
        editable=False,
        room=[
            ConfigItem(key="room_meeting_duration_seconds", label="Room duration", value=settings.room_meeting_duration_seconds, unit="seconds", source=ENV, note="ROOM_MEETING_DURATION_SECONDS"),
            ConfigItem(key="room_max_participants", label="Maximum participants", value=settings.room_max_participants or None, source=ENV, note="ROOM_MAX_PARTICIPANTS (0 = no limit)"),
            ConfigItem(key="room_token_ttl_seconds", label="Participant token lifetime", value=settings.room_token_ttl_seconds, unit="seconds", source=ENV),
            ConfigItem(key="expiry_warning_seconds", label="Expiry warning threshold", value=FE_EXPIRY_WARNING_SECONDS, unit="seconds", source=CODE_FE),
            ConfigItem(key="relay_panel_visible_lines", label="Recent relay lines (Relay tab)", value=FE_RELAY_PANEL_VISIBLE_LINES, source=CODE_FE),
            ConfigItem(key="recent_transcript_buffer", label="Live transcript buffer per room", value=50, source=CODE_BE, note="Redis list, final lines only"),
            ConfigItem(key="recent_chat_buffer", label="Live chat buffer per room", value=100, source=CODE_BE),
            ConfigItem(key="display_name_max_length", label="Display name max length", value=FE_DISPLAY_NAME_MAX_LENGTH, unit="characters", source=CODE_BE),
            ConfigItem(key="chat_max_length", label="Chat message max length", value=RoomService.MAX_CHAT_MESSAGE_LENGTH, unit="characters", source=CODE_BE),
        ],
        ai=[
            ConfigItem(key="openai_realtime_model", label="Realtime model (STT + relay + voice)", value=settings.openai_realtime_model, source=ENV),
            ConfigItem(key="openai_realtime_transcription_model", label="Transcription model", value=settings.openai_realtime_transcription_model, source=ENV),
            ConfigItem(key="openai_summary_model", label="Summary model", value=settings.openai_summary_model, source=ENV),
            ConfigItem(key="caption_chat_translation_model", label="Caption & chat translation model", value="gpt-4o-mini", source=CODE_BE),
            ConfigItem(key="meeting_summary_language", label="Summary fallback language", value=settings.meeting_summary_language, source=ENV),
            ConfigItem(key="meeting_summary_max_source_items", label="Summary source items", value=settings.meeting_summary_max_source_items, source=ENV),
            ConfigItem(key="livekit_line_isolation_enabled", label="Speaker line isolation", value=settings.livekit_line_isolation_enabled, source=ENV),
        ],
        languages=[
            {
                "code": code,
                "label": LANGUAGE_LABELS.get(code, code),
                "enabled": True,
                "source": CODE_BE,
            }
            for code in SUPPORTED_MEETING_LANGUAGES
        ],
        notifications=[
            {"event": "room_created", "label": "Room created", "supported": True, "enabled": telegram_ready and settings.telegram_notify_room_created, "channel": "telegram"},
            {"event": "participant_joined", "label": "Participant joined", "supported": True, "enabled": telegram_ready and settings.telegram_notify_participant_joined, "channel": "telegram"},
            {"event": "room_ended", "label": "Room ended", "supported": False, "enabled": False, "channel": None},
            {"event": "ai_relay_error", "label": "AI relay error", "supported": False, "enabled": False, "channel": None},
            {"event": "summary_failed", "label": "Summary failed", "supported": False, "enabled": False, "channel": None},
            {"event": "system_degraded", "label": "System degraded", "supported": False, "enabled": False, "channel": None},
        ],
        operations=[
            ConfigItem(key="admin_session_ttl_seconds", label="Admin session lifetime", value=settings.admin_session_ttl_seconds, unit="seconds", source=ENV),
            ConfigItem(key="ops_event_retention_days", label="AI ops event retention", value=settings.ops_event_retention_days, unit="days", source=ENV),
            ConfigItem(key="history_storage", label="History storage", value="MongoDB", source=ENV),
        ],
    )
