"""Restore: select → plan → (confirm) → download → SHA-256 → (pre-restore backup) → restore → verify.

Safety rules
- The target is always explicit (--target-database-url / RESTORE_DATABASE_URL), never DATABASE_URL.
- Default mode "empty" refuses a target that already has collections; "clean" drops
  each restored collection first and needs confirmation.
- A production target needs --confirm-production and typing "RESTORE PRODUCTION"
  (or --yes together with --confirm-production), plus a pre-restore backup unless
  --skip-pre-restore-backup is given.
- Nothing is restored unless the downloaded file matches the manifest SHA-256.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from tools.db_backup.backup import (
    EXIT_RESTORE,
    EXIT_UPLOAD,
    EXIT_VALIDATION,
    EXIT_VERIFY,
    BackupError,
    run_backup,
)
from tools.db_backup.checksum import sha256_file
from tools.db_backup.config import (
    BACKUP_ENVIRONMENTS,
    DatabaseTarget,
    Settings,
    is_production,
)
from tools.db_backup.db import DatabaseError, ToolError, ToolRunner, active_connections, inspect_database, make_work_dir, tail
from tools.db_backup.logging_config import Console, human_duration, human_size, log
from tools.db_backup.manifest import ManifestError, validate_manifest
from tools.db_backup.s3 import BackupEntry, BackupStore, StoreError

PRODUCTION_PHRASE = "RESTORE PRODUCTION"
MODES = ("empty", "clean")


@dataclass
class RestoreRequest:
    source_environment: str
    target: DatabaseTarget
    target_environment: str
    backup_id: Optional[str] = None
    latest: bool = False
    mode: str = "empty"
    dry_run: bool = False
    yes: bool = False
    confirm_production: bool = False
    pre_restore_backup: Optional[bool] = None  # None = default for the target
    skip_pre_restore_backup: bool = False
    allow_version_mismatch: bool = False
    jobs: int = 4


@dataclass
class RestoreReport:
    backup_id: str
    source_environment: str
    created_at: str
    target_environment: str
    database: str
    seconds: float
    checks: List[str] = field(default_factory=list)
    pre_restore_backup_id: Optional[str] = None
    collections: Dict[str, int] = field(default_factory=dict)


def resolve_backup(store: BackupStore, environment: str, backup_id: Optional[str], latest: bool) -> BackupEntry:
    if bool(backup_id) == bool(latest):
        raise BackupError("Pass exactly one of --backup-id or --latest.", EXIT_VALIDATION)
    try:
        entry = store.latest(environment) if latest else store.find(environment, backup_id or "")
        validate_manifest(entry.manifest, expected_environment=environment)
    except (StoreError, ManifestError) as exc:
        raise BackupError(str(exc), EXIT_VALIDATION) from exc
    return entry


def download_verified(store: BackupStore, entry: BackupEntry, directory: Path, console: Console) -> Path:
    """Stream the dump to disk and accept it only if size and SHA-256 match the manifest."""
    path = directory / "database.archive.gz"
    expected = entry.manifest["backup"]
    try:
        store.download_dump(entry.keys, path)
    except StoreError as exc:
        raise BackupError(str(exc), EXIT_UPLOAD) from exc
    size = path.stat().st_size
    if size != expected["size_bytes"]:
        raise BackupError(f"Downloaded size {size} does not match the manifest ({expected['size_bytes']}). ABORT.", EXIT_VERIFY)
    digest = sha256_file(path)
    if digest != expected["sha256"]:
        path.unlink(missing_ok=True)
        raise BackupError(
            f"Checksum mismatch. ABORT.\n  manifest: {expected['sha256']}\n  download: {digest}\nThe backup is corrupt or was modified; nothing was restored.",
            EXIT_VERIFY,
        )
    console.ok(f"Checksum verified ({human_size(size)}, sha256 {digest[:12]}…)")
    return path


def _confirm(prompt: str, phrase: str, *, input_fn: Callable[[str], str]) -> bool:
    if not sys.stdin.isatty() and input_fn is input:
        return False
    try:
        answer = input_fn(f"{prompt}\n\nType:\n\n{phrase}\n\nto continue: ")
    except EOFError:
        return False
    return answer.strip() == phrase


def guard(request: RestoreRequest, settings: Settings, existing_collections: int, console: Console, *, input_fn: Callable[[str], str] = input) -> None:
    """Refuse dangerous restores unless explicitly confirmed."""
    production = is_production(request.target_environment)
    source_db = settings.database
    if (
        source_db is not None
        and not production
        and is_production(settings.environment)
        and request.target.identity == source_db.identity
    ):
        raise BackupError(
            "The restore target is the production database configured in DATABASE_URL. "
            "Pass --target-env prod --confirm-production if you really mean to restore production.",
            EXIT_VALIDATION,
        )
    if production and not request.confirm_production:
        raise BackupError("Restoring into PRODUCTION requires --confirm-production.", EXIT_VALIDATION)
    destructive = request.mode == "clean" and existing_collections > 0
    if not (production or destructive):
        return
    if request.dry_run:
        return
    if request.yes:
        if production:
            console.warn("Non-interactive PRODUCTION restore (--confirm-production --yes).")
        return
    if production:
        warning = (
            f"WARNING\n\nYou are about to restore backup:\n\n{request.backup_id or 'latest'}\n\n"
            f"into:\n\nPRODUCTION DATABASE ({request.target.safe_url})\n\nThis operation may overwrite existing data."
        )
        if not _confirm(warning, PRODUCTION_PHRASE, input_fn=input_fn):
            raise BackupError("Production restore not confirmed. Nothing was changed.", EXIT_VALIDATION)
        return
    warning = f"This restore drops and replaces {existing_collections} collection(s) in {request.target.safe_url}."
    if not _confirm(warning, "RESTORE", input_fn=input_fn):
        raise BackupError("Restore not confirmed. Nothing was changed. (Use --yes in automation.)", EXIT_VALIDATION)


def print_plan(console: Console, entry: BackupEntry, request: RestoreRequest, existing: int, pre_backup: bool) -> None:
    manifest = entry.manifest
    console.section("Restore Plan")
    console.field("Backup", f"{entry.backup_id} ({manifest.get('label') or manifest.get('trigger')})")
    console.field("Source environment", request.source_environment)
    console.field("Created", manifest.get("created_at"))
    console.field("Source database", f"{manifest['database'].get('name')} (MongoDB {manifest['database'].get('version')})")
    console.field("Target", f"{request.target.safe_url} [{request.target_environment}]")
    console.field("Target collections now", existing)
    console.field("Mode", request.mode)
    steps = ["Download backup and verify SHA-256"]
    if pre_backup:
        steps.append("Create pre-restore backup of the target and upload it")
    if request.mode == "clean":
        steps.append("Drop each collection contained in the backup, then restore it (mongorestore --drop)")
    else:
        steps.append("Restore into the empty target database")
    steps += ["Restore indexes and data", "Verify connection, collections and document counts"]
    console.line("Actions:")
    for index, step in enumerate(steps, 1):
        console.line(f"  {index}. {step}")
    console.line()
    if request.target_environment in ("local", "test", "custom", "dev") and is_production(request.source_environment):
        console.warn("This is a PRODUCTION backup: it contains production data. Keep the restored copy secure and delete it when done.")


def run_restore(
    settings: Settings,
    request: RestoreRequest,
    *,
    store: Optional[BackupStore] = None,
    runner: Optional[ToolRunner] = None,
    console: Optional[Console] = None,
    input_fn: Callable[[str], str] = input,
) -> Optional[RestoreReport]:
    console = console or Console()
    store = store or BackupStore(settings)
    runner = runner or ToolRunner(settings.use_docker, settings.docker_network, settings.docker_image)
    if request.mode not in MODES:
        raise BackupError(f"--mode must be one of {', '.join(MODES)}.", EXIT_VALIDATION)
    started = time.monotonic()
    if is_production(request.target_environment) and not request.confirm_production:
        # Refuse before touching anything (not even connecting to the target).
        raise BackupError("Restoring into PRODUCTION requires --confirm-production.", EXIT_VALIDATION)

    entry = resolve_backup(store, request.source_environment, request.backup_id, request.latest)
    request.backup_id = entry.backup_id
    manifest = entry.manifest
    fields = {
        "operation": "restore",
        "backup_id": entry.backup_id,
        "environment": request.source_environment,
        "target": request.target.safe_url,
        "target_environment": request.target_environment,
        "mode": request.mode,
    }
    log(logging.INFO, "restore requested", dry_run=request.dry_run, **fields)

    try:
        target_info = inspect_database(request.target, with_counts=False)
    except DatabaseError as exc:
        raise BackupError(str(exc), EXIT_VALIDATION) from exc
    source_major = int(manifest["database"].get("major_version") or str(manifest["database"].get("version", "0")).split(".")[0])
    if target_info.major < source_major and not request.allow_version_mismatch:
        raise BackupError(
            f"MongoDB version mismatch.\n\nBackup source: MongoDB {manifest['database'].get('version')}\n"
            f"Target server: MongoDB {target_info.server_version}\n\nRestore into MongoDB {source_major} or newer "
            "(or pass --allow-version-mismatch if you know it is compatible).",
            EXIT_VALIDATION,
        )
    existing = len(target_info.user_collections)
    if request.mode == "empty" and existing > 0:
        raise BackupError(
            f"Target database {request.target.database} already has {existing} collection(s). "
            "Restore into an empty database, or pass --mode clean to replace them.",
            EXIT_VALIDATION,
        )

    production = is_production(request.target_environment)
    pre_backup = existing > 0 and (
        request.pre_restore_backup if request.pre_restore_backup is not None else production
    )
    if request.skip_pre_restore_backup:
        if production:
            console.warn("Skipping the pre-restore backup of PRODUCTION. Current data cannot be recovered by this tool.")
        pre_backup = False
    if pre_backup and request.target_environment not in BACKUP_ENVIRONMENTS:
        raise BackupError("A pre-restore backup needs --target-env dev, staging or prod (where to store it).", EXIT_VALIDATION)

    print_plan(console, entry, request, existing, pre_backup)
    if existing > 0:
        others = active_connections(request.target)
        if others:
            # MongoDB has no "terminate connections" step in this tool: stop the app instead.
            console.warn(f"{others} other client connection(s) are open on the target server. Stop the application before restoring over live data.")
    guard(request, settings, existing, console, input_fn=input_fn)
    if request.dry_run:
        console.ok("Dry run: backup found, manifest valid, target reachable. Nothing was changed.")
        return None
    if not runner.available("mongorestore"):
        raise BackupError("mongorestore is not installed. Install the MongoDB Database Tools or pass --use-docker.", EXIT_VALIDATION)

    workdir = make_work_dir(settings.tmp_dir, "restore")
    report = RestoreReport(
        backup_id=entry.backup_id,
        source_environment=request.source_environment,
        created_at=str(manifest.get("created_at")),
        target_environment=request.target_environment,
        database=request.target.database,
        seconds=0.0,
    )
    try:
        dump_path = download_verified(store, entry, workdir, console)
        report.checks.append("checksum")

        if pre_backup:
            console.line("Creating pre-restore backup of the target...")
            result = run_backup(
                settings,
                target=request.target,
                environment=request.target_environment,
                trigger="pre_restore",
                label=f"before-restore-{entry.backup_id}"[:64],
                store=store,
                runner=runner,
                console=Console(quiet=True),
                keep_local=False,
            )
            report.pre_restore_backup_id = result.backup_id
            console.ok(f"Pre-restore backup {result.backup_id} uploaded")

        source_db = manifest["database"]["name"]
        archive = f"/work/{dump_path.name}" if runner.use_docker else str(dump_path)
        args = [
            f"--archive={archive}",
            "--gzip",
            f"--nsInclude={source_db}.*",
            f"--nsFrom={source_db}.*",
            f"--nsTo={request.target.database}.*",
            f"--numParallelCollections={request.jobs}",
            "--stopOnError",
        ]
        if request.mode == "clean":
            args.append("--drop")
        console.line("Restoring...")
        try:
            output = runner.run("mongorestore", args, target=request.target, workdir=workdir, server_major=target_info.major)
        except ToolError as exc:
            raise BackupError(f"Restore failed: {exc}\n{tail(exc.output)}", EXIT_RESTORE) from exc
        failed = re.search(r"(\d+) document\(s\) failed to restore", output)
        if failed and int(failed.group(1)) > 0:
            raise BackupError(f"Restore incomplete: {failed.group(1)} document(s) failed to restore.\n{tail(output)}", EXIT_RESTORE)
        report.checks.append("restore")

        report.collections = verify_restored(request.target, manifest, console)
        report.checks += ["database connection", "collections", "document counts"]
        report.seconds = time.monotonic() - started
        print_report(console, report)
        log(logging.INFO, "restore completed", status="success", duration_s=round(report.seconds, 1), **fields)
        return report
    except BackupError as exc:
        log(logging.ERROR, "restore failed", status="failed", error=str(exc).splitlines()[0], exit_code=exc.exit_code, **fields)
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def verify_restored(target: DatabaseTarget, manifest: Dict[str, Any], console: Console) -> Dict[str, int]:
    """Post-restore checks: connect, every backed-up collection/view exists, counts match."""
    try:
        info = inspect_database(target)
    except DatabaseError as exc:
        raise BackupError(f"Post-restore check failed: {exc}", EXIT_RESTORE) from exc
    restored = {c["name"]: c for c in info.collections}
    counts: Dict[str, int] = {}
    problems = []
    for expected in manifest["database"].get("collections", []):
        name = expected["name"]
        if name.startswith("system."):
            continue
        actual = restored.get(name)
        if actual is None:
            problems.append(f"missing {expected.get('type', 'collection')} {name}")
            continue
        if expected.get("type", "collection") == "collection":
            counts[name] = int(actual.get("documents", 0))
            if expected.get("documents") is not None and counts[name] < int(expected["documents"]):
                problems.append(f"{name}: {counts[name]} documents, backup listed {expected['documents']}")
            missing_indexes = set(expected.get("indexes", [])) - set(actual.get("indexes", []))
            if missing_indexes:
                problems.append(f"{name}: missing indexes {sorted(missing_indexes)}")
    if problems:
        raise BackupError("Post-restore verification failed:\n  " + "\n  ".join(problems), EXIT_RESTORE)
    console.ok(f"Database connection ({target.database}, MongoDB {info.server_version})")
    console.ok(f"{len(counts)} collections and their indexes present; document counts match the backup")
    return counts


def print_report(console: Console, report: RestoreReport) -> None:
    console.section("Restore completed")
    console.field("Backup", report.backup_id)
    console.field("Source", report.source_environment)
    console.field("Created", report.created_at)
    console.field("Target", report.target_environment)
    console.field("Database", report.database)
    if report.pre_restore_backup_id:
        console.field("Pre-restore backup", report.pre_restore_backup_id)
    console.field("Duration", human_duration(report.seconds))
    console.line("Verification:")
    for check in report.checks:
        console.line(f"  ✓ {check}")


# ── Restore drill in a throw-away container ────────────────────────────────


def restore_test(
    settings: Settings,
    *,
    environment: str,
    backup_id: Optional[str],
    latest: bool,
    store: Optional[BackupStore] = None,
    console: Optional[Console] = None,
) -> RestoreReport:
    """Restore a backup into a temporary mongo:<major> container, verify it, remove it."""
    console = console or Console()
    store = store or BackupStore(settings)
    if shutil.which("docker") is None:
        raise BackupError("restore-test needs Docker.", EXIT_VALIDATION)
    entry = resolve_backup(store, environment, backup_id, latest)
    major = entry.manifest["database"].get("major_version") or 7
    name = f"meetq-restore-test-{uuid.uuid4().hex[:8]}"
    console.line(f"Starting temporary MongoDB {major} container {name}...")
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::27017", f"mongo:{major}"],
        check=True, capture_output=True, text=True,
    )
    try:
        port = subprocess.run(["docker", "port", name, "27017/tcp"], check=True, capture_output=True, text=True).stdout.strip().rsplit(":", 1)[-1]
        target = DatabaseTarget(hosts=f"127.0.0.1:{port}", database="restore_test")
        deadline = time.monotonic() + 60
        while True:
            try:
                inspect_database(target, with_counts=False)
                break
            except DatabaseError:
                if time.monotonic() > deadline:
                    raise BackupError("Temporary MongoDB did not start.", EXIT_RESTORE)
                time.sleep(1)
        runner = ToolRunner(settings.use_docker, "host" if not settings.use_docker else settings.docker_network, settings.docker_image)
        if runner.use_docker and runner.docker_network != "host":
            target = DatabaseTarget(hosts=f"localhost:{port}", database="restore_test")
        request = RestoreRequest(
            source_environment=environment,
            target=target,
            target_environment="test",
            backup_id=entry.backup_id,
            yes=True,
            jobs=settings.restore_jobs,
        )
        report = run_restore(settings, request, store=store, runner=runner, console=console)
        assert report is not None
        console.ok("Restore drill passed")
        return report
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
