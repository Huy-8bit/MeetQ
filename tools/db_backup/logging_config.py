"""Structured logs (stderr) for cron/systemd, plus human output (stdout).

Log lines carry operation, backup_id, environment, database (sanitized), duration,
size and status — never passwords, AWS secrets, tokens or raw database URLs.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

LOGGER_NAME = "meetq.db_backup"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, default=str)


def configure(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    return logger


def log(level: int, message: str, **fields: Any) -> None:
    logging.getLogger(LOGGER_NAME).log(level, message, extra={"fields": fields})


class Console:
    """Readable progress for people; quiet mode (cron) prints only the summary."""

    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet

    def line(self, text: str = "") -> None:
        if not self.quiet:
            print(text, flush=True)

    def ok(self, text: str) -> None:
        self.line(f"✓ {text}")

    def warn(self, text: str) -> None:
        print(f"! {text}", file=sys.stderr, flush=True)

    def section(self, title: str) -> None:
        self.line()
        self.line(title)
        self.line()

    def field(self, label: str, value: Any) -> None:
        self.line(f"{label}:")
        self.line(f"  {value}")


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" or value >= 10 else f"{value:.1f} {unit}"
        value /= 1000
    return f"{size} B"


def human_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"
