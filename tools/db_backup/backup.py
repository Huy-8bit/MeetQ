"""Backup: native dump → verify readable → SHA-256 → S3 dump → S3 manifest (last).

A backup is successful only when every step passed; anything else raises and the
CLI exits non-zero. The manifest is uploaded last and is the completion marker.
"""
from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from tools.db_backup.checksum import sha256_file
from tools.db_backup.config import DatabaseTarget, Settings
from tools.db_backup.db import (
    SUPPORTED_SERVER_MAJORS,
    DatabaseError,
    DatabaseInfo,
    ToolError,
    ToolRunner,
    inspect_database,
    make_work_dir,
    tail,
)
from tools.db_backup.logging_config import Console, human_duration, human_size, log
from tools.db_backup.manifest import BackupKeys, build_manifest, local_file_name, new_backup_id
from tools.db_backup.s3 import BackupStore, StoreError

PROJECT = "meetq"
MIN_FREE_BYTES = 200 * 1024 * 1024


class BackupError(Exception):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# CLI exit codes (cron/systemd/CI read these).
EXIT_VALIDATION = 2
EXIT_LOCKED = 3
EXIT_DUMP = 4
EXIT_UPLOAD = 5
EXIT_VERIFY = 6
EXIT_RESTORE = 7


@dataclass
class BackupResult:
    backup_id: str
    environment: str
    keys: BackupKeys
    size_bytes: int
    sha256: str
    seconds: float
    manifest: Dict[str, Any]
    local_path: Optional[Path]


def git_commit(settings: Settings) -> Optional[str]:
    if settings.git_commit:
        return settings.git_commit
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
            cwd=Path(__file__).resolve().parents[2],
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def check_disk_space(directory: Path, info: DatabaseInfo) -> int:
    """Abort before dumping if the temp disk can't hold the backup."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    free = shutil.disk_usage(directory).free
    # A gzip archive is normally well below the on-disk (compressed) storage size;
    # require the storage size + 20% so a production disk is never filled.
    estimate = max(int((info.storage_size + info.index_size) * 1.2), MIN_FREE_BYTES)
    if free < estimate:
        raise BackupError(
            f"Insufficient disk space.\n\nEstimated backup requirement: {human_size(estimate)}\nAvailable: {human_size(free)}",
            EXIT_VALIDATION,
        )
    return estimate


def database_metadata(info: DatabaseInfo) -> Dict[str, Any]:
    return {
        "engine": "mongodb",
        "version": info.server_version,
        "major_version": info.major,
        "name": info.database,
        "topology": "replica_set" if info.is_replica_set else "standalone",
        "collections": info.collections,
        "data_size_bytes": info.data_size,
    }


def run_backup(
    settings: Settings,
    *,
    target: Optional[DatabaseTarget] = None,
    environment: Optional[str] = None,
    trigger: str = "manual",
    label: Optional[str] = None,
    store: Optional[BackupStore] = None,
    runner: Optional[ToolRunner] = None,
    console: Optional[Console] = None,
    keep_local: Optional[bool] = None,
) -> BackupResult:
    console = console or Console()
    target = target or settings.require_database()
    environment = environment or settings.environment
    store = store or BackupStore(settings)
    runner = runner or ToolRunner(settings.use_docker, settings.docker_network, settings.docker_image)
    keep = settings.keep_local if keep_local is None else keep_local
    started = time.monotonic()
    started_at = datetime.now(timezone.utc)
    backup_id = new_backup_id(started_at)
    keys = store.keys(environment, backup_id)
    fields = {"operation": "backup", "backup_id": backup_id, "environment": environment, "database": target.safe_url, "trigger": trigger}

    console.section("Database Backup")
    console.field("Environment", environment)
    console.field("Database", target.database)
    console.field("Host", target.hosts)
    log(logging.INFO, "backup started", **fields)

    try:
        info = inspect_database(target)
    except DatabaseError as exc:
        raise BackupError(str(exc), EXIT_VALIDATION) from exc
    if info.major not in SUPPORTED_SERVER_MAJORS:
        raise BackupError(f"MongoDB {info.server_version} is not supported by this tool.", EXIT_VALIDATION)
    console.ok(f"Connected (MongoDB {info.server_version}, {len(info.user_collections)} collections)")
    if not info.is_replica_set:
        console.line("  Standalone server: each collection is dumped consistently, not the whole database at one instant.")
    if not runner.available("mongodump"):
        raise BackupError(
            "mongodump is not installed. Install the MongoDB Database Tools or pass --use-docker.", EXIT_VALIDATION
        )
    tools_version = runner.version("mongodump", info.major)

    workdir = make_work_dir(settings.tmp_dir, "backup")
    dump_path = workdir / local_file_name(PROJECT, environment, backup_id)
    try:
        check_disk_space(settings.tmp_dir, info)
        console.line()
        console.line("Creating backup...")
        try:
            # Archive + gzip: one compressed file, selective restore, no destructive
            # options baked in (the restore command decides --drop).
            runner.run(
                "mongodump",
                [f"--db={target.database}", f"--archive={_tool_path(runner, dump_path)}", "--gzip"],
                target=target, workdir=workdir, server_major=info.major,
            )
        except ToolError as exc:
            raise BackupError(f"Dump failed: {exc}\n{tail(exc.output)}", EXIT_DUMP) from exc
        if not dump_path.is_file() or dump_path.stat().st_size == 0:
            raise BackupError("Dump produced no file.", EXIT_DUMP)
        console.ok("Dump completed")

        try:
            # The file must be readable as an archive before it counts as a backup.
            runner.run(
                "mongorestore",
                [f"--archive={_tool_path(runner, dump_path)}", "--gzip", "--dryRun", f"--nsInclude={target.database}.*"],
                target=target, workdir=workdir, server_major=info.major,
            )
        except ToolError as exc:
            raise BackupError(f"Dump verification failed: {exc}\n{tail(exc.output)}", EXIT_VERIFY) from exc
        console.ok("Dump is readable (mongorestore --dryRun)")

        size = dump_path.stat().st_size
        digest = sha256_file(dump_path)
        console.field("Backup size", human_size(size))
        console.field("SHA256", digest)
        manifest = build_manifest(
            backup_id=backup_id,
            environment=environment,
            trigger=trigger,
            label=label,
            database=database_metadata(info),
            size_bytes=size,
            sha256=digest,
            tools={
                "dump_tool": f"mongodump {tools_version}",
                "hostname": socket.gethostname(),
                "git_commit": git_commit(settings),
                "docker": runner.use_docker,
            },
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        tags = {"environment": environment, "database": target.database, "backup_type": trigger}

        console.field("Uploading", f"s3://{store.bucket}/{keys.folder}")
        try:
            store.upload_dump(dump_path, keys, tags)
            remote_size = store.object_size(keys.dump)
            if remote_size != size:
                raise BackupError(f"Uploaded size {remote_size} does not match local size {size}.", EXIT_VERIFY)
            console.ok("Backup uploaded")
            store.upload_manifest(manifest, keys, tags)
            if store.object_size(keys.manifest) is None:
                raise BackupError("Manifest is missing after upload.", EXIT_VERIFY)
            console.ok("Manifest uploaded")
        except StoreError as exc:
            raise BackupError(str(exc), EXIT_UPLOAD) from exc
        console.ok("Verification passed")

        seconds = time.monotonic() - started
        console.field("Backup ID", backup_id)
        console.field("Completed in", human_duration(seconds))
        log(logging.INFO, "backup completed", status="success", size_bytes=size, duration_s=round(seconds, 1), **fields)
        return BackupResult(backup_id, environment, keys, size, digest, seconds, manifest, dump_path if keep else None)
    except BackupError as exc:
        log(logging.ERROR, "backup failed", status="failed", error=str(exc).splitlines()[0], exit_code=exc.exit_code, **fields)
        raise
    finally:
        # Default: never leave dumps on the application disk (also after a failure).
        if keep:
            console.line(f"Local copy kept: {dump_path}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


def _tool_path(runner: ToolRunner, path: Path) -> str:
    """Inside Docker the work dir is mounted at /work."""
    return f"/work/{path.name}" if runner.use_docker else str(path)
