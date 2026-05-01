import json
import logging
from typing import Any, Optional

import httpx

from server.config import Settings


logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Small Telegram Bot API wrapper for operational notifications."""

    def __init__(self, settings: Settings):
        self.enabled = settings.telegram_notifications_enabled
        self.notify_room_created = settings.telegram_notify_room_created
        self.bot_token = (settings.telegram_bot_token or "").strip()
        self.chat_id = (settings.telegram_chat_id or "").strip()
        self.api_base_url = settings.telegram_api_base_url.rstrip("/")
        self.timeout_seconds = max(float(settings.telegram_request_timeout_seconds), 0.5)
        self._warned_missing_config = False

    def is_room_created_enabled(self) -> bool:
        return self.enabled and self.notify_room_created

    def _configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _room_value(self, room: Any, field: str, default: Any = None) -> Any:
        if hasattr(room, field):
            return getattr(room, field)
        if isinstance(room, dict):
            return room.get(field, default)
        return default

    def _build_room_created_message(
        self,
        room: Any,
        *,
        share_url: Optional[str] = None,
        creator_display_name: Optional[str] = None,
        creator_participant_id: Optional[str] = None,
    ) -> str:
        room_id = self._room_value(room, "room_id", "unknown")
        meeting_languages = self._room_value(room, "meeting_languages", []) or []
        brse_enabled = self._room_value(room, "brse_enabled")
        created_at = self._room_value(room, "created_at", "unknown")
        expires_at = self._room_value(room, "expires_at")
        participant_limit = self._room_value(room, "participant_limit")

        if isinstance(meeting_languages, (list, tuple)):
            meeting_languages_value = [str(lang) for lang in meeting_languages]
        else:
            meeting_languages_value = meeting_languages

        message: dict[str, Any] = {
            "event": "room.created",
            "room": {
                "room_id": room_id,
                "meeting_languages": meeting_languages_value,
                "brse_enabled": bool(brse_enabled) if brse_enabled is not None else None,
                "created_at": created_at,
                "expires_at": expires_at,
                "participant_limit": participant_limit,
            },
            "share_url": share_url,
        }

        creator: dict[str, str] = {}
        if creator_display_name or creator_participant_id:
            if creator_display_name:
                creator["display_name"] = creator_display_name
            if creator_participant_id:
                creator["participant_id"] = creator_participant_id
            message["creator"] = creator

        return json.dumps(message, ensure_ascii=False, indent=2, default=str)

    async def send_room_created(
        self,
        room: Any,
        *,
        share_url: Optional[str] = None,
        creator_display_name: Optional[str] = None,
        creator_participant_id: Optional[str] = None,
    ) -> bool:
        room_id = self._room_value(room, "room_id", "unknown")

        if not self.is_room_created_enabled():
            return False

        if not self._configured():
            if not self._warned_missing_config:
                logger.warning(
                    "telegram room-created notification skipped: missing bot token or chat id; room_id=%s",
                    room_id,
                )
                self._warned_missing_config = True
            return False

        url = f"{self.api_base_url}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": self._build_room_created_message(
                room,
                share_url=share_url,
                creator_display_name=creator_display_name,
                creator_participant_id=creator_participant_id,
            ),
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "telegram room-created notification failed: room_id=%s status=%s body=%s",
                room_id,
                exc.response.status_code,
                exc.response.text[:300],
            )
            return False
        except httpx.RequestError as exc:
            logger.warning(
                "telegram room-created notification failed: room_id=%s error=%s",
                room_id,
                exc,
            )
            return False
        except Exception:
            logger.exception(
                "telegram room-created notification failed unexpectedly: room_id=%s",
                room_id,
            )
            return False

        logger.info("telegram room-created notification sent: room_id=%s", room_id)
        return True
