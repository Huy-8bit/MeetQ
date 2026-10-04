"""Backup IDs, S3 key layout and the manifest (the completion marker of a backup).

  s3://<bucket>/<prefix>/<env>/<YYYY>/<MM>/<DD>/<backup_id>/database.archive.gz
  s3://<bucket>/<prefix>/<env>/<YYYY>/<MM>/<DD>/<backup_id>/manifest.json

The dump is uploaded first and the manifest (status "complete") last, so a backup
without a complete manifest is never listed or restored.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from tools.db_backup import TOOL_VERSION
from tools.db_backup.config import BACKUP_ENVIRONMENTS

MANIFEST_VERSION = 1
DUMP_FILE = "database.archive.gz"
MANIFEST_FILE = "manifest.json"
ENGINE = "mongodb"
DUMP_FORMAT = "mongodump-archive-gzip"
TRIGGERS = ("manual", "scheduled", "pre_restore")
STATUS_COMPLETE = "complete"

BACKUP_ID_RE = re.compile(r"^(\d{8}T\d{6}Z)-([0-9a-f]{6})$")
LABEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class ManifestError(Exception):
    pass


def new_backup_id(now: Optional[datetime] = None) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def backup_time(backup_id: str) -> datetime:
    match = BACKUP_ID_RE.match(backup_id)
    if not match:
        raise ManifestError(f"Invalid backup ID {backup_id!r} (expected e.g. 20261005T020000Z-a13f92).")
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class BackupKeys:
    prefix: str
    environment: str
    backup_id: str

    def __post_init__(self) -> None:
        if self.environment not in BACKUP_ENVIRONMENTS:
            raise ManifestError(f"Unknown backup environment {self.environment!r}.")
        backup_time(self.backup_id)

    @property
    def folder(self) -> str:
        created = backup_time(self.backup_id)
        return f"{self.prefix}/{self.environment}/{created:%Y/%m/%d}/{self.backup_id}/"

    @property
    def dump(self) -> str:
        return self.folder + DUMP_FILE

    @property
    def manifest(self) -> str:
        return self.folder + MANIFEST_FILE


def environment_prefix(prefix: str, environment: str) -> str:
    if environment not in BACKUP_ENVIRONMENTS:
        raise ManifestError(f"Unknown backup environment {environment!r}.")
    return f"{prefix}/{environment}/"


def local_file_name(project: str, environment: str, backup_id: str) -> str:
    return f"{project}-{environment}-{backup_id}.archive.gz"


def build_manifest(
    *,
    backup_id: str,
    environment: str,
    trigger: str,
    label: Optional[str],
    database: Dict[str, Any],
    size_bytes: int,
    sha256: str,
    tools: Dict[str, Any],
    started_at: datetime,
    finished_at: datetime,
) -> Dict[str, Any]:
    """No secrets: no password, URI with credentials, AWS key or session token."""
    if trigger not in TRIGGERS:
        raise ManifestError(f"Unknown trigger {trigger!r}.")
    if label is not None and not LABEL_RE.match(label):
        raise ManifestError("Label may only use letters, digits, '.', '_' and '-' (max 64).")
    return {
        "manifest_version": MANIFEST_VERSION,
        "status": STATUS_COMPLETE,
        "backup_id": backup_id,
        "created_at": started_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "completed_at": finished_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": environment,
        "trigger": trigger,
        "label": label,
        "database": database,
        "backup": {
            "format": DUMP_FORMAT,
            "file": DUMP_FILE,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "logical": True,
            "point_in_time": False,
        },
        "tool": {"name": "meetq-db-backup", "version": TOOL_VERSION, **tools},
    }


def validate_manifest(manifest: Dict[str, Any], *, expected_environment: Optional[str] = None) -> None:
    def need(condition: bool, message: str) -> None:
        if not condition:
            raise ManifestError(message)

    need(manifest.get("manifest_version") == MANIFEST_VERSION, "Unsupported manifest version.")
    need(manifest.get("status") == STATUS_COMPLETE, "Backup is not complete.")
    need(bool(BACKUP_ID_RE.match(str(manifest.get("backup_id", "")))), "Manifest has an invalid backup ID.")
    database = manifest.get("database") or {}
    need(database.get("engine") == ENGINE, f"Backup engine is {database.get('engine')!r}, this tool restores {ENGINE}.")
    backup = manifest.get("backup") or {}
    need(backup.get("format") == DUMP_FORMAT, f"Unsupported dump format {backup.get('format')!r}.")
    need(bool(re.fullmatch(r"[0-9a-f]{64}", str(backup.get("sha256", "")))), "Manifest has no valid SHA-256.")
    need(isinstance(backup.get("size_bytes"), int) and backup["size_bytes"] > 0, "Manifest has no backup size.")
    if expected_environment is not None:
        need(
            manifest.get("environment") == expected_environment,
            f"Backup belongs to {manifest.get('environment')!r}, not {expected_environment!r}.",
        )
