"""
server/shared/logging_utils.py
Timestamped structured logger.
- Translation output goes to stdout (print) for clean piping.
- All operational logs go to stderr via the logging module.
- Optional file handler writes to logs/ directory.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
_FMT = "[%(asctime)s] %(levelname)-5s %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S.%f"[:-3]  # ms precision


class _MsFormatter(logging.Formatter):
    """Format with millisecond timestamps."""

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        ct = datetime.fromtimestamp(record.created)
        return ct.strftime("%Y-%m-%d %H:%M:%S.") + f"{ct.microsecond // 1000:03d}"


def get_logger(name: str, file_logging: bool = False) -> logging.Logger:
    """
    Return a named logger writing to stderr.
    If file_logging=True, also writes to logs/<name>.log.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)

    # Stderr handler (always present)
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(_MsFormatter(_FMT))
    logger.addHandler(sh)

    # Optional file handler
    if file_logging:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _LOG_DIR / f"{name.replace('.', '_')}.log"
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(_MsFormatter(_FMT))
        logger.addHandler(fh)

    logger.propagate = False
    return logger


def print_translation(text: str, end: str = "", flush: bool = True) -> None:
    """
    Print translation text to stdout.
    Use end='' for streaming deltas, end='\\n' for final output.
    """
    print(text, end=end, flush=flush)


def transcript_logging_enabled() -> bool:
    """Raw meeting text is logged only when LOG_TRANSCRIPTS is set (local debugging)."""
    return os.getenv("LOG_TRANSCRIPTS", "").strip().lower() in {"1", "true", "yes", "on"}


def loggable_text(text: object) -> str:
    """Return text for a log line: the raw value in debug mode, else only its length."""
    value = "" if text is None else str(text)
    if transcript_logging_enabled():
        return repr(value)
    return f"<redacted chars={len(value)}>"
