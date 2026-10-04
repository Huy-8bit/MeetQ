from __future__ import annotations

from typing import Any, Dict, Optional


class AdminApiError(Exception):
    """Raised by admin services; rendered as the standard ``{"error": {...}}`` envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def to_payload(self) -> Dict[str, Any]:
        error: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = self.details
        return {"error": error}


def history_unavailable() -> AdminApiError:
    return AdminApiError(
        503,
        "history_unavailable",
        "Meeting history storage (MongoDB) is not configured or not reachable.",
    )


def room_not_found(room_id: str) -> AdminApiError:
    return AdminApiError(404, "room_not_found", f"Room {room_id} was not found.")
