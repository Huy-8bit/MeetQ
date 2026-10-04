"""meetq-db: MongoDB logical backup & restore to private S3.

  python -m tools.db_backup backup   [--environment prod] [--label before-release] [--trigger scheduled]
  python -m tools.db_backup list     [--environment prod] [--limit 20]
  python -m tools.db_backup info     <backup_id>
  python -m tools.db_backup download <backup_id> [--output DIR]
  python -m tools.db_backup verify   --backup-id ID | --latest
  python -m tools.db_backup restore  --backup-id ID | --latest --target-database-url URL [--target-env local] ...
  python -m tools.db_backup restore-test --backup-id ID | --latest
  python -m tools.db_backup prune    [--yes]
  python -m tools.db_backup cleanup-local [--older-than-hours 24]

Exit codes: 0 ok · 1 unexpected · 2 validation · 3 another run active · 4 dump ·
5 upload/download · 6 verification · 7 restore · 130 interrupted.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from tools.db_backup import TOOL_VERSION
from tools.db_backup.backup import EXIT_LOCKED, EXIT_VALIDATION, EXIT_VERIFY, BackupError, run_backup
from tools.db_backup.config import (
    TARGET_ENVIRONMENTS,
    ConfigError,
    Settings,
    build_settings,
    load_env_file,
    normalize_environment,
    parse_database_url,
)
from tools.db_backup.db import ToolRunner, make_work_dir
from tools.db_backup.locking import LockBusyError, OperationLock
from tools.db_backup.logging_config import Console, configure, human_size
from tools.db_backup.manifest import TRIGGERS, ManifestError, backup_time, validate_manifest
from tools.db_backup.notify import notify_failure
from tools.db_backup.restore import RestoreRequest, download_verified, resolve_backup, restore_test, run_restore
from tools.db_backup.s3 import BackupStore, StoreError

EXIT_INTERRUPTED = 130


class _Interrupted(BaseException):
    pass


def _on_signal(signum, _frame):
    raise _Interrupted(signal.Signals(signum).name)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meetq-db", description="MeetQ MongoDB logical backup & restore (private S3).")
    parser.add_argument("--version", action="version", version=f"meetq-db {TOOL_VERSION}")
    parser.add_argument("--env-file", default=None, help="Optional KEY=VALUE file (default: .env.backup if present).")
    parser.add_argument("--environment", "--env", dest="environment", help="Backup environment: dev, staging or prod.")
    parser.add_argument("--use-docker", action="store_true", help="Run mongodump/mongorestore in the official mongo image.")
    parser.add_argument("--docker-network", default=None, help="Docker network for --use-docker (default: host).")
    parser.add_argument("--quiet", action="store_true", help="Only print the result (for schedulers).")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup", help="Create a backup and upload it to S3.")
    backup.add_argument("--label", help="Free label, e.g. before-release-v2.")
    backup.add_argument("--trigger", choices=TRIGGERS[:2], default="manual")
    backup.add_argument("--keep-local", action="store_true", help="Keep the local dump after upload.")

    listing = sub.add_parser("list", help="List complete backups (newest first).")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--json", action="store_true")

    info = sub.add_parser("info", help="Show a backup manifest.")
    info.add_argument("backup_id")

    download = sub.add_parser("download", help="Download a backup and verify its checksum.")
    download.add_argument("backup_id")
    download.add_argument("--output", default=".", help="Directory for database.archive.gz + manifest.json.")

    verify = sub.add_parser("verify", help="Download a backup, check SHA-256 and that it is a readable archive.")
    _select(verify)

    restore = sub.add_parser("restore", help="Restore a backup into a target database.")
    _select(restore)
    restore.add_argument("--target-database-url", default=None, help="Target (default: RESTORE_DATABASE_URL). Never DATABASE_URL.")
    restore.add_argument("--target-env", default=None, choices=list(TARGET_ENVIRONMENTS) + ["production"],
                         help="What the target is (default: local). 'prod' enables production safeguards.")
    restore.add_argument("--mode", choices=["empty", "clean"], default="empty",
                         help="empty (default): target must have no collections. clean: drop and replace restored collections.")
    restore.add_argument("--dry-run", action="store_true", help="Validate everything and print the plan; change nothing.")
    restore.add_argument("--yes", action="store_true", help="Skip interactive confirmation (production also needs --confirm-production).")
    restore.add_argument("--confirm-production", action="store_true")
    restore.add_argument("--pre-restore-backup", action="store_true", default=None, help="Back up the target first.")
    restore.add_argument("--skip-pre-restore-backup", action="store_true")
    restore.add_argument("--allow-version-mismatch", action="store_true")
    restore.add_argument("--jobs", type=int, default=None, help="Parallel collections (default: RESTORE_JOBS or 4).")

    drill = sub.add_parser("restore-test", help="Restore into a throw-away Docker MongoDB and verify it.")
    _select(drill)

    prune = sub.add_parser("prune", help="Delete backups older than BACKUP_RETENTION_DAYS (keeps MIN_BACKUPS_TO_KEEP).")
    prune.add_argument("--yes", action="store_true")
    prune.add_argument("--dry-run", action="store_true")

    cleanup = sub.add_parser("cleanup-local", help="Remove stale local temp dirs created by this tool.")
    cleanup.add_argument("--older-than-hours", type=float, default=24)
    return parser


def _select(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--backup-id")
    group.add_argument("--latest", action="store_true")


def _settings(args: argparse.Namespace) -> Settings:
    env: Dict[str, str] = dict(os.environ)
    env_file = Path(args.env_file) if args.env_file else Path(".env.backup")
    if args.env_file and not env_file.is_file():
        raise ConfigError(f"Env file {env_file} not found.")
    load_env_file(env_file, env)
    # boto3 reads AWS settings from the process environment: pass through the
    # non-empty AWS_* values from the env file (real environment variables still win).
    for key in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION", "AWS_DEFAULT_REGION"):
        if env.get(key) and not os.environ.get(key):
            os.environ[key] = env[key]
        elif key in os.environ and not os.environ[key]:
            del os.environ[key]  # an empty AWS_PROFILE breaks the credential chain
    settings = build_settings(env, environment=args.environment)
    if args.use_docker:
        settings.use_docker = True
    if args.docker_network:
        settings.docker_network = args.docker_network
    settings._env = env  # type: ignore[attr-defined]  # for RESTORE_DATABASE_URL
    return settings


def cmd_backup(args, settings: Settings, console: Console) -> int:
    with OperationLock(settings.tmp_dir):
        result = run_backup(settings, trigger=args.trigger, label=args.label, console=console,
                            keep_local=True if args.keep_local else None)
    if args.quiet:
        print(f"backup ok {result.backup_id} {result.size_bytes} {result.sha256}")
    return 0


def cmd_list(args, settings: Settings, console: Console) -> int:
    entries = BackupStore(settings).list_backups(settings.environment, limit=args.limit)
    if args.json:
        print(json.dumps([e.manifest for e in entries], indent=2))
        return 0
    if not entries:
        print(f"No complete backups for {settings.environment}.")
        return 0
    print(f"{'BACKUP ID':<26} {'CREATED (UTC)':<17} {'SIZE':>9}  {'ENV':<7} {'TRIGGER':<11} LABEL")
    for entry in entries:
        created = backup_time(entry.backup_id).strftime("%Y-%m-%d %H:%M")
        m = entry.manifest
        print(f"{entry.backup_id:<26} {created:<17} {human_size(entry.size_bytes):>9}  {entry.environment:<7} {m.get('trigger', ''):<11} {m.get('label') or ''}")
    return 0


def cmd_info(args, settings: Settings, console: Console) -> int:
    entry = BackupStore(settings).find(settings.environment, args.backup_id)
    print(json.dumps(entry.manifest, indent=2, sort_keys=True))
    return 0


def cmd_download(args, settings: Settings, console: Console) -> int:
    store = BackupStore(settings)
    entry = resolve_backup(store, settings.environment, args.backup_id, False)
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    workdir = make_work_dir(settings.tmp_dir, "download")
    try:
        path = download_verified(store, entry, workdir, console)
        destination = output / f"meetq-{settings.environment}-{entry.backup_id}.archive.gz"
        shutil.move(str(path), destination)
        (output / f"meetq-{settings.environment}-{entry.backup_id}.manifest.json").write_text(json.dumps(entry.manifest, indent=2))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    console.ok(f"Saved {destination}")
    console.warn("This file contains database data. Store it securely and delete it when no longer needed.")
    return 0


def cmd_verify(args, settings: Settings, console: Console) -> int:
    store = BackupStore(settings)
    entry = resolve_backup(store, settings.environment, args.backup_id, args.latest)
    runner = ToolRunner(settings.use_docker, settings.docker_network, settings.docker_image)
    workdir = make_work_dir(settings.tmp_dir, "verify")
    try:
        path = download_verified(store, entry, workdir, console)
        target = settings.database
        if target is not None and runner.available("mongorestore"):
            from tools.db_backup.db import ToolError, tail

            archive = f"/work/{path.name}" if runner.use_docker else str(path)
            source_db = entry.manifest["database"]["name"]
            try:
                runner.run("mongorestore", [f"--archive={archive}", "--gzip", "--dryRun", f"--nsInclude={source_db}.*"],
                           target=target, workdir=workdir, server_major=entry.manifest["database"].get("major_version"))
            except ToolError as exc:
                raise BackupError(f"Archive is not readable: {exc}\n{tail(exc.output)}", EXIT_VERIFY) from exc
            console.ok("Archive readable (mongorestore --dryRun)")
        else:
            console.line("  (Archive readability check skipped: no DATABASE_URL or mongorestore. Use restore-test for a full drill.)")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    console.ok(f"Backup {entry.backup_id} verified")
    return 0


def cmd_restore(args, settings: Settings, console: Console) -> int:
    env = getattr(settings, "_env", {})
    url = args.target_database_url or env.get("RESTORE_DATABASE_URL")
    if not url:
        raise ConfigError("Pass --target-database-url or set RESTORE_DATABASE_URL. DATABASE_URL is never used as a restore target.")
    target = parse_database_url(url)
    target_env = normalize_environment(args.target_env or "local", allowed=TARGET_ENVIRONMENTS + ("production",), what="target environment")
    target_env = "prod" if target_env == "production" else target_env
    request = RestoreRequest(
        source_environment=settings.environment,
        target=target,
        target_environment=target_env,
        backup_id=args.backup_id,
        latest=args.latest,
        mode=args.mode,
        dry_run=args.dry_run,
        yes=args.yes,
        confirm_production=args.confirm_production,
        pre_restore_backup=args.pre_restore_backup,
        skip_pre_restore_backup=args.skip_pre_restore_backup,
        allow_version_mismatch=args.allow_version_mismatch,
        jobs=args.jobs or settings.restore_jobs,
    )
    with OperationLock(settings.tmp_dir):
        run_restore(settings, request, console=console)
    return 0


def cmd_restore_test(args, settings: Settings, console: Console) -> int:
    with OperationLock(settings.tmp_dir):
        restore_test(settings, environment=settings.environment, backup_id=args.backup_id, latest=args.latest, console=console)
    return 0


def cmd_prune(args, settings: Settings, console: Console) -> int:
    """Application-level retention that never deletes the newest MIN_BACKUPS_TO_KEEP backups."""
    store = BackupStore(settings)
    entries = store.list_backups(settings.environment)
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
    keep = entries[: settings.min_backups_to_keep]
    candidates = [e for e in entries[settings.min_backups_to_keep:] if backup_time(e.backup_id) < cutoff]
    console.line(f"{len(entries)} backups in {settings.environment}; keeping the newest {len(keep)}; "
                 f"{len(candidates)} older than {settings.retention_days} days to delete.")
    for entry in candidates:
        console.line(f"  - {entry.backup_id} ({human_size(entry.size_bytes)})")
    if not candidates or args.dry_run:
        return 0
    if not args.yes:
        if not sys.stdin.isatty() or input("Type DELETE to delete these backups: ").strip() != "DELETE":
            raise BackupError("Prune not confirmed. Nothing was deleted.", EXIT_VALIDATION)
    for entry in candidates:
        store.delete_backup(entry.keys)
        console.ok(f"Deleted {entry.backup_id}")
    return 0


def cmd_cleanup_local(args, settings: Settings, console: Console) -> int:
    """Only this tool's own directories (meetq-db-backup-*) under BACKUP_TMP_DIR."""
    base = settings.tmp_dir
    if not base.is_dir():
        console.line("Nothing to clean.")
        return 0
    cutoff = time.time() - args.older_than_hours * 3600
    removed = 0
    for path in base.glob("meetq-db-backup-*"):
        if path.is_dir() and path.stat().st_mtime < cutoff:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    console.ok(f"Removed {removed} stale temporary director{'y' if removed == 1 else 'ies'} from {base}")
    return 0


COMMANDS = {
    "backup": cmd_backup,
    "list": cmd_list,
    "info": cmd_info,
    "download": cmd_download,
    "verify": cmd_verify,
    "restore": cmd_restore,
    "restore-test": cmd_restore_test,
    "prune": cmd_prune,
    "cleanup-local": cmd_cleanup_local,
}


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    configure(args.verbose)
    console = Console(quiet=args.quiet)
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    settings: Optional[Settings] = None
    try:
        settings = _settings(args)
        return COMMANDS[args.command](args, settings, console)
    except ConfigError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return EXIT_VALIDATION
    except LockBusyError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return EXIT_LOCKED
    except BackupError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        if settings is not None and args.command == "backup":
            notify_failure(settings, f"MeetQ database backup FAILED ({settings.environment}): {str(exc).splitlines()[0]}")
        return exc.exit_code
    except (StoreError, ManifestError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return EXIT_VALIDATION if isinstance(exc, ManifestError) else 5
    except _Interrupted as exc:
        print(f"✗ Interrupted ({exc}). Temporary files were removed; the lock is released.", file=sys.stderr)
        return EXIT_INTERRUPTED
