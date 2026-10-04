import json
import multiprocessing
import os
import stat
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.db_backup import backup as backup_mod
from tools.db_backup import restore as restore_mod
from tools.db_backup.backup import BackupError, run_backup
from tools.db_backup.checksum import sha256_file
from tools.db_backup.config import ConfigError, DatabaseTarget, build_settings, mask_secrets, parse_database_url
from tools.db_backup.db import ToolRunner
from tools.db_backup.locking import LockBusyError, OperationLock
from tools.db_backup.logging_config import Console
from tools.db_backup.manifest import BackupKeys, ManifestError, build_manifest, new_backup_id, validate_manifest
from tools.db_backup.restore import RestoreRequest, guard, run_restore
from tools.db_backup.s3 import BackupStore
from tools.db_backup.tests.fakes import FakeRunner, FakeS3, db_info

PASSWORD = "s3cr3t-P@ss/word"
DB_URL = f"mongodb://backup_user:{PASSWORD.replace('@', '%40').replace('/', '%2F')}@db.internal:27017/brseai?authSource=admin"


def settings_for(tmp_path, env="prod", **extra):
    values = {
        "BACKUP_ENVIRONMENT": env,
        "DATABASE_URL": DB_URL,
        "DB_BACKUP_S3_BUCKET": "meetq-db-backups-test",
        "BACKUP_TMP_DIR": str(tmp_path / "tmp"),
        **extra,
    }
    return build_settings(values)


@pytest.fixture
def quiet():
    return Console(quiet=True)


# ── Config & secrets ───────────────────────────────────────────────────────


def test_database_url_is_parsed_and_sanitized():
    target = parse_database_url(DB_URL)
    assert target.password == PASSWORD and target.username == "backup_user" and target.database == "brseai"
    assert PASSWORD not in target.safe_url and target.safe_url == "mongodb://backup_user:***@db.internal:27017/brseai?authSource=admin"
    assert PASSWORD not in target.uri_without_password and "backup_user@" in target.uri_without_password
    assert PASSWORD not in repr(target)
    assert mask_secrets(f"error for {DB_URL}", [PASSWORD]).count("***") >= 1 and PASSWORD not in mask_secrets(f"x {PASSWORD}", [PASSWORD])


def test_app_mongodb_settings_are_reused():
    settings = build_settings({
        "BACKUP_ENVIRONMENT": "dev", "MONGODB_HOST": "mongo", "MONGODB_PORT": "27017", "MONGODB_DATABASE": "brseai",
        "MONGODB_USERNAME": "brseai", "MONGODB_PASSWORD": "pw123456", "MONGODB_AUTH_SOURCE": "brseai",
    })
    assert settings.database.hosts == "mongo:27017" and settings.database.options == {"authSource": "brseai"}


def test_environment_is_validated_and_cannot_be_mixed(tmp_path):
    assert settings_for(tmp_path, env="production").environment == "prod"
    with pytest.raises(ConfigError):
        settings_for(tmp_path, env="qa")
    with pytest.raises(ConfigError, match="does not match"):
        build_settings({"BACKUP_ENVIRONMENT": "dev"}, environment="prod")
    with pytest.raises(ConfigError):
        build_settings({})


# ── Manifest, keys, checksum ───────────────────────────────────────────────


def test_backup_id_and_key_layout_are_per_environment():
    backup_id = new_backup_id(datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc))
    assert backup_id.startswith("20261005T020000Z-") and len(backup_id) == 23
    keys = BackupKeys("database-backups", "prod", backup_id)
    assert keys.dump == f"database-backups/prod/2026/10/05/{backup_id}/database.archive.gz"
    assert keys.manifest.endswith(f"/{backup_id}/manifest.json")
    assert BackupKeys("database-backups", "dev", backup_id).folder.startswith("database-backups/dev/")
    with pytest.raises(ManifestError):
        BackupKeys("database-backups", "production-ish", backup_id)


def _manifest(**over):
    m = build_manifest(
        backup_id="20261005T020000Z-a13f92", environment="prod", trigger="manual", label="before-release",
        database={"engine": "mongodb", "version": "7.0.43", "major_version": 7, "name": "brseai", "collections": []},
        size_bytes=10, sha256="a" * 64, tools={"hostname": "h"}, started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
    )
    m.update(over)
    return m


def test_manifest_validation():
    validate_manifest(_manifest(), expected_environment="prod")
    with pytest.raises(ManifestError, match="not 'prod'"):
        validate_manifest(_manifest(environment="dev"), expected_environment="prod")
    with pytest.raises(ManifestError, match="engine"):
        validate_manifest(_manifest(database={"engine": "postgresql"}))
    with pytest.raises(ManifestError, match="complete"):
        validate_manifest(_manifest(status="uploading"))
    with pytest.raises(ManifestError):
        build_manifest(backup_id="x", environment="prod", trigger="hourly", label=None, database={}, size_bytes=1, sha256="a" * 64,
                       tools={}, started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc))


def test_sha256_is_streamed(tmp_path):
    import hashlib

    path = tmp_path / "big.bin"
    data = os.urandom(3 * 1024 * 1024 + 7)
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


# ── Locking ────────────────────────────────────────────────────────────────


def _hold_lock(directory, ready):
    OperationLock(Path(directory)).acquire()
    ready.set()
    time.sleep(60)


def test_second_run_is_refused_and_lock_survives_a_crash(tmp_path):
    with OperationLock(tmp_path):
        with pytest.raises(LockBusyError, match="already running"):
            OperationLock(tmp_path).acquire()
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    proc = ctx.Process(target=_hold_lock, args=(str(tmp_path), ready))
    proc.start()
    assert ready.wait(20)
    with pytest.raises(LockBusyError):
        OperationLock(tmp_path).acquire()
    proc.kill()  # crash: the kernel releases the flock
    proc.join()
    OperationLock(tmp_path).acquire().release()


# ── Backup flow ────────────────────────────────────────────────────────────


@pytest.fixture
def patched_db(monkeypatch):
    info = db_info()
    monkeypatch.setattr(backup_mod, "inspect_database", lambda target, with_counts=True: info)
    monkeypatch.setattr(restore_mod, "inspect_database", lambda target, with_counts=True: info)
    monkeypatch.setattr(restore_mod, "active_connections", lambda target: 0)
    return info


def test_backup_uploads_dump_then_manifest(tmp_path, patched_db, quiet):
    settings = settings_for(tmp_path)
    s3, runner = FakeS3(), FakeRunner()
    result = run_backup(settings, store=BackupStore(settings, s3), runner=runner, console=quiet, label="before-release-v2")
    assert s3.calls == [f"upload:{result.keys.dump}", f"put:{result.keys.manifest}"]  # manifest last
    manifest = json.loads(s3.objects[result.keys.manifest])
    assert manifest["backup"]["sha256"] == result.sha256 and manifest["label"] == "before-release-v2"
    assert manifest["database"]["engine"] == "mongodb" and manifest["environment"] == "prod"
    assert result.keys.dump.startswith("database-backups/prod/")
    assert s3.extra[result.keys.dump]["Tagging"] == "environment=prod&database=brseai&backup_type=manual"
    # Readability check ran before upload; nothing left on disk.
    assert any("--dryRun" in cmd for cmd in runner.commands)
    assert not list((tmp_path / "tmp").glob("meetq-db-backup-*"))
    text = json.dumps(manifest) + " ".join(" ".join(c) for c in runner.commands)
    assert PASSWORD not in text and "s3cr3t" not in text


def test_dump_failure_is_not_a_backup(tmp_path, patched_db, quiet):
    settings = settings_for(tmp_path)
    s3, runner = FakeS3(), FakeRunner()
    runner.fail = "mongodump"
    with pytest.raises(BackupError) as excinfo:
        run_backup(settings, store=BackupStore(settings, s3), runner=runner, console=quiet)
    assert excinfo.value.exit_code == 4 and s3.objects == {}


def test_unreadable_dump_is_not_uploaded(tmp_path, patched_db, quiet):
    settings = settings_for(tmp_path)
    s3, runner = FakeS3(), FakeRunner()
    runner.fail = "mongorestore"
    with pytest.raises(BackupError) as excinfo:
        run_backup(settings, store=BackupStore(settings, s3), runner=runner, console=quiet)
    assert excinfo.value.exit_code == 6 and s3.objects == {}


@pytest.mark.parametrize("failure", ["fail_upload", "fail_manifest"])
def test_upload_failures_leave_no_listed_backup(tmp_path, patched_db, quiet, failure):
    settings = settings_for(tmp_path)
    s3 = FakeS3()
    setattr(s3, failure, True)
    store = BackupStore(settings, s3)
    with pytest.raises(BackupError) as excinfo:
        run_backup(settings, store=store, runner=FakeRunner(), console=quiet)
    assert excinfo.value.exit_code == 5
    assert store.list_backups("prod") == []


def test_insufficient_disk_space_aborts_before_dump(tmp_path, monkeypatch, quiet):
    huge = db_info()
    huge.storage_size = 10**15
    monkeypatch.setattr(backup_mod, "inspect_database", lambda target, with_counts=True: huge)
    runner = FakeRunner()
    settings = settings_for(tmp_path)
    with pytest.raises(BackupError, match="Insufficient disk space"):
        run_backup(settings, store=BackupStore(settings, FakeS3()), runner=runner, console=quiet)
    assert not any(c[0] == "mongodump" for c in runner.commands)


# ── Listing, latest, environment separation, prune ─────────────────────────


def _backup(settings, s3, patched_db, quiet, when):
    store = BackupStore(settings, s3)
    original = backup_mod.new_backup_id
    backup_mod.new_backup_id = lambda now=None: new_backup_id(when)
    try:
        return run_backup(settings, store=store, runner=FakeRunner(), console=quiet)
    finally:
        backup_mod.new_backup_id = original


def test_latest_is_per_environment(tmp_path, patched_db, quiet):
    s3 = FakeS3()
    prod, dev = settings_for(tmp_path), settings_for(tmp_path, env="dev")
    old = _backup(prod, s3, patched_db, quiet, datetime(2026, 10, 3, 2, tzinfo=timezone.utc))
    new = _backup(prod, s3, patched_db, quiet, datetime(2026, 10, 5, 2, tzinfo=timezone.utc))
    newest_dev = _backup(dev, s3, patched_db, quiet, datetime(2026, 10, 6, 2, tzinfo=timezone.utc))
    store = BackupStore(prod, s3)
    assert [e.backup_id for e in store.list_backups("prod")] == [new.backup_id, old.backup_id]
    assert store.latest("prod").backup_id == new.backup_id  # never the newer dev backup
    assert store.latest("dev").backup_id == newest_dev.backup_id
    # An orphan dump without manifest is never listed.
    s3.objects[BackupKeys("database-backups", "prod", "20261007T020000Z-ffffff").dump] = b"x"
    assert store.latest("prod").backup_id == new.backup_id


def test_prune_keeps_minimum(tmp_path, patched_db, quiet, monkeypatch):
    from tools.db_backup import cli

    s3 = FakeS3()
    settings = settings_for(tmp_path, BACKUP_RETENTION_DAYS="30", MIN_BACKUPS_TO_KEEP="3")
    for days in (200, 120, 90, 60):  # all older than 30 days
        _backup(settings, s3, patched_db, quiet, datetime.now(timezone.utc) - timedelta(days=days))
    monkeypatch.setattr(cli, "BackupStore", lambda s: BackupStore(s, s3))

    class Args:
        yes = True
        dry_run = False

    cli.cmd_prune(Args(), settings, quiet)
    assert len(BackupStore(settings, s3).list_backups("prod")) == 3  # never below the minimum


# ── Restore safety ─────────────────────────────────────────────────────────


def _request(**over):
    base = dict(source_environment="prod", target=parse_database_url("mongodb://localhost:27017/brseai_restore"),
                target_environment="local", backup_id="20261005T020000Z-a13f92")
    base.update(over)
    return RestoreRequest(**base)


def test_production_target_needs_flag_and_exact_phrase(tmp_path, quiet):
    settings = settings_for(tmp_path)
    with pytest.raises(BackupError, match="--confirm-production"):
        guard(_request(target_environment="prod"), settings, 3, quiet, input_fn=lambda prompt: "RESTORE PRODUCTION")
    with pytest.raises(BackupError, match="not confirmed"):
        guard(_request(target_environment="prod", confirm_production=True), settings, 3, quiet, input_fn=lambda prompt: "yes")
    guard(_request(target_environment="prod", confirm_production=True), settings, 3, quiet, input_fn=lambda prompt: "RESTORE PRODUCTION")
    guard(_request(target_environment="prod", confirm_production=True, yes=True), settings, 3, quiet, input_fn=lambda p: "")


def test_production_url_with_local_label_is_refused(tmp_path, quiet):
    settings = settings_for(tmp_path)
    same_as_prod = _request(target=parse_database_url(DB_URL), target_environment="local")
    with pytest.raises(BackupError, match="production database"):
        guard(same_as_prod, settings, 0, quiet, input_fn=lambda p: "RESTORE")


def test_restore_into_non_empty_target_needs_clean_mode(tmp_path, patched_db, quiet):
    settings = settings_for(tmp_path)
    s3 = FakeS3()
    _backup(settings, s3, patched_db, quiet, datetime(2026, 10, 5, 2, tzinfo=timezone.utc))
    with pytest.raises(BackupError, match="already has 2 collection"):
        run_restore(settings, _request(backup_id=None, latest=True), store=BackupStore(settings, s3), runner=FakeRunner(), console=quiet)


def test_checksum_mismatch_aborts_before_restore(tmp_path, patched_db, quiet, monkeypatch):
    settings = settings_for(tmp_path)
    s3 = FakeS3()
    result = _backup(settings, s3, patched_db, quiet, datetime(2026, 10, 5, 2, tzinfo=timezone.utc))
    s3.objects[result.keys.dump] = s3.objects[result.keys.dump][:-1] + b"X"  # same size, different bytes
    empty = db_info(collections=0)
    monkeypatch.setattr(restore_mod, "inspect_database", lambda target, with_counts=True: empty)
    runner = FakeRunner()
    with pytest.raises(BackupError, match="Checksum mismatch") as excinfo:
        run_restore(settings, _request(backup_id=result.backup_id), store=BackupStore(settings, s3), runner=runner, console=quiet)
    assert excinfo.value.exit_code == 6
    assert not [c for c in runner.commands if c[0] == "mongorestore"]


def test_failed_documents_mean_failed_restore(tmp_path, patched_db, quiet, monkeypatch):
    settings = settings_for(tmp_path)
    s3 = FakeS3()
    result = _backup(settings, s3, patched_db, quiet, datetime(2026, 10, 5, 2, tzinfo=timezone.utc))
    monkeypatch.setattr(restore_mod, "inspect_database", lambda target, with_counts=True: db_info(collections=0))
    runner = FakeRunner()
    runner.restore_output = "8 document(s) restored successfully. 2 document(s) failed to restore."
    with pytest.raises(BackupError, match="2 document") as excinfo:
        run_restore(settings, _request(backup_id=result.backup_id), store=BackupStore(settings, s3), runner=runner, console=quiet)
    assert excinfo.value.exit_code == 7


def test_older_target_server_is_refused(tmp_path, patched_db, quiet, monkeypatch):
    settings = settings_for(tmp_path)
    s3 = FakeS3()
    result = _backup(settings, s3, patched_db, quiet, datetime(2026, 10, 5, 2, tzinfo=timezone.utc))
    monkeypatch.setattr(restore_mod, "inspect_database", lambda target, with_counts=True: db_info(collections=0, major=6))
    with pytest.raises(BackupError, match="version mismatch"):
        run_restore(settings, _request(backup_id=result.backup_id), store=BackupStore(settings, s3), runner=FakeRunner(), console=quiet)


def test_dry_run_changes_nothing(tmp_path, patched_db, quiet, monkeypatch):
    settings = settings_for(tmp_path)
    s3 = FakeS3()
    result = _backup(settings, s3, patched_db, quiet, datetime(2026, 10, 5, 2, tzinfo=timezone.utc))
    runner = FakeRunner()
    assert run_restore(settings, _request(backup_id=result.backup_id, mode="clean", dry_run=True),
                       store=BackupStore(settings, s3), runner=runner, console=quiet) is None
    assert runner.commands == []


# ── Password never on the command line ─────────────────────────────────────


def test_tool_runner_keeps_password_off_argv(tmp_path, monkeypatch):
    seen = {}

    def fake_exec(self, command, secrets):
        seen["argv"] = command
        config = next(a.split("=", 1)[1] for a in command if a.startswith("--config="))
        seen["config_mode"] = stat.S_IMODE(os.stat(config).st_mode)
        seen["config"] = Path(config).read_text()
        return "ok"

    monkeypatch.setattr(ToolRunner, "_exec", fake_exec)
    target = parse_database_url(DB_URL)
    ToolRunner().run("mongodump", ["--db=brseai"], target=target, workdir=tmp_path, server_major=7)
    assert PASSWORD not in " ".join(seen["argv"])
    assert seen["config_mode"] == 0o600 and PASSWORD in seen["config"]
    assert not (tmp_path / ".mongo-tools.yaml").exists()  # removed after the run
