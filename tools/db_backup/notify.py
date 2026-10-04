"""Optional failure notification through the existing MeetQ Telegram bot."""
from __future__ import annotations

import json
import urllib.request

from tools.db_backup.config import Settings


def notify_failure(settings: Settings, text: str) -> None:
    if not (settings.notify_telegram and settings.telegram_bot_token and settings.telegram_chat_id):
        return
    body = json.dumps({"chat_id": settings.telegram_chat_id, "text": text[:3500]}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=10).close()
    except Exception:
        pass  # notification is best effort; the exit code still reports the failure
