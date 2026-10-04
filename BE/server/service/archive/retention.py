"""Retention rules for meeting archives.

- A new archive snapshots the system default (`default_retention_days_snapshot`).
- An admin may set `retention_override_days` on one archive.
- Effective days = override if set, else the snapshot. Changing the system default
  never moves the expiry of existing archives.
- `expires_at = ended_at + effective days` (archive creation time when `ended_at`
  is unknown). The cleanup worker deletes everything once `expires_at <= now`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365


class InvalidRetentionError(ValueError):
    pass


def validate_retention_days(days: Any) -> int:
    if isinstance(days, bool) or not isinstance(days, int):
        raise InvalidRetentionError("retention days must be a whole number")
    if days < MIN_RETENTION_DAYS or days > MAX_RETENTION_DAYS:
        raise InvalidRetentionError(f"retention must be between {MIN_RETENTION_DAYS} and {MAX_RETENTION_DAYS} days")
    return days


def effective_retention_days(archive: Dict[str, Any]) -> int:
    override = archive.get("retention_override_days")
    if override:
        return int(override)
    return int(archive.get("default_retention_days_snapshot") or 0)


def retention_base_time(archive: Dict[str, Any]) -> Optional[datetime]:
    """Retention counts from the meeting end; legacy/unknown end falls back to archive creation."""
    return as_utc(archive.get("ended_at")) or as_utc(archive.get("created_at"))


def compute_expires_at(archive: Dict[str, Any]) -> Optional[datetime]:
    base = retention_base_time(archive)
    days = effective_retention_days(archive)
    if base is None or days <= 0:
        return None
    return base + timedelta(days=days)


def as_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def iso(value: Any) -> Optional[str]:
    parsed = as_utc(value)
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
