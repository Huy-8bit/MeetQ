from __future__ import annotations

import logging

from server.meeting_modes import (
    BRSE_MODE_SILENT_SUMMARY,
    brse_audio_output_enabled,
    brse_relay_text_enabled,
    normalize_brse_mode,
    normalize_brse_output_mode,
)

logger = logging.getLogger(__name__)


class RelayDeliveryController:
    """Mode-aware delivery layer.

    Relay text is the source of truth. Audio is an optional delivery channel
    controlled by BRSE mode and output mode.
    """

    def __init__(self, *, room_id: str, brse_mode: str, brse_output_mode: str) -> None:
        self.room_id = room_id
        self.brse_mode = normalize_brse_mode(brse_mode)
        self.brse_output_mode = normalize_brse_output_mode(brse_output_mode)
        self.relay_text_enabled = brse_relay_text_enabled(True, self.brse_mode)
        self.relay_audio_enabled = brse_audio_output_enabled(
            True,
            self.brse_mode,
            self.brse_output_mode,
        )
        self.relay_output_enabled = self.relay_text_enabled
        self.silent_summary_mode = self.brse_mode == BRSE_MODE_SILENT_SUMMARY
        self.text_only_output_mode = self.relay_text_enabled and not self.relay_audio_enabled

    @property
    def suppressed_audio_reason(self) -> str:
        if self.text_only_output_mode:
            return "brse_text_only_output_mode"
        return "brse_silent_summary_mode"

    def describe(self) -> dict[str, object]:
        return {
            "brse_mode": self.brse_mode,
            "brse_output_mode": self.brse_output_mode,
            "relay_text_enabled": self.relay_text_enabled,
            "relay_audio_enabled": self.relay_audio_enabled,
            "relay_output_enabled": self.relay_output_enabled,
            "silent_summary_mode": self.silent_summary_mode,
            "text_only_output_mode": self.text_only_output_mode,
        }

    def log_startup(self) -> None:
        logger.info(
            "BRSE delivery startup room=%s brse_mode=%s brse_output_mode=%s "
            "relay_text_enabled=%s relay_audio_enabled=%s",
            self.room_id,
            self.brse_mode,
            self.brse_output_mode,
            self.relay_text_enabled,
            self.relay_audio_enabled,
        )
        if self.text_only_output_mode:
            logger.info(
                "BRSE delivery text-first text-only room=%s: relay text remains enabled; relay audio is suppressed",
                self.room_id,
            )

    def log_publish_decision(
        self,
        *,
        speaker_id: str,
        utterance_id: str,
        relay_style: str,
        text_action: str,
        audio_action: str,
        reason: str,
    ) -> None:
        logger.info(
            "BRSE delivery relay_publish room=%s speaker=%s utterance=%s relay_style=%s "
            "text_action=%s audio_action=%s reason=%s",
            self.room_id,
            speaker_id,
            utterance_id,
            relay_style,
            text_action,
            audio_action,
            reason,
        )
