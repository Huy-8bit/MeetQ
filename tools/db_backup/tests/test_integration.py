"""Backup → delete → restore against a real MongoDB in Docker, through the real CLI.

Needs: Docker, mongodump/mongorestore (or DB_BACKUP_IT_USE_DOCKER=1) and an S3-compatible
endpoint for a throw-away bucket (the local stack's S3 on http://localhost:9000 by
default). Never points at a production bucket. Skipped when the prerequisites are missing.

  tools/db_backup/.venv/bin/python -m pytest tools/db_backup/tests/test_integration.py -v
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

pymongo = pytest.importorskip("pymongo")
boto3 = pytest.importorskip("boto3")

ROOT = Path(__file__).resolve().parents[3]
S3_ENDPOINT = os.environ.get("DB_BACKUP_IT_S3_ENDPOINT", "http://localhost:9000")
S3_KEY = os.environ.get("DB_BACKUP_IT_S3_ACCESS_KEY", "meetq-local")
S3_SECRET = os.environ.get("DB_BACKUP_IT_S3_SECRET_KEY", "meetq-local-secret")
BUCKET = "meetq-db-backups-integration-test"
PASSWORD = "it-Pa$$w0rd-" + uuid.uuid4().hex[:6]


def _have(cmd):
    return shutil.which(cmd) is not None


def _s3_reachable():
    try:
        client = boto3.client("s3", endpoint_url=S3_ENDPOINT, aws_access_key_id=S3_KEY, aws_secret_access_key=S3_SECRET, region_name="us-east-1")
        client.list_buckets()
        return client
    except Exception:
        return None


pytestmark = pytest.mark.skipif(
    not _have("docker") or not (_have("mongodump") or os.environ.get("DB_BACKUP_IT_USE_DOCKER")),
    reason="needs Docker and the MongoDB Database Tools",
)


@pytest.fixture(scope="module")
def s3():
    client = _s3_reachable()
    if client is None:
        pytest.skip(f"no S3-compatible endpoint at {S3_ENDPOINT}")
    try:
        client.create_bucket(Bucket=BUCKET)
    except Exception:
        pass
    yield client
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET):
        for item in page.get("Contents", []) or []:
            client.delete_object(Bucket=BUCKET, Key=item["Key"])


@pytest.fixture(scope="module")
def mongo():
    name = f"meetq-backup-it-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::27017",
         "-e", "MONGO_INITDB_ROOT_USERNAME=root", "-e", f"MONGO_INITDB_ROOT_PASSWORD={PASSWORD}", "mongo:7"],
        check=True, capture_output=True,
    )
    try:
        port = subprocess.run(["docker", "port", name, "27017/tcp"], check=True, capture_output=True, text=True).stdout.strip().rsplit(":", 1)[-1]
        url = f"mongodb://root:{PASSWORD.replace('$', '%24')}@127.0.0.1:{port}/meetq_it?authSource=admin"
        client = pymongo.MongoClient(url, serverSelectionTimeoutMS=2000)
        deadline = time.time() + 90
        while True:
            try:
                client.admin.command("ping")
                break
            except Exception:
                if time.time() > deadline:
                    raise
                time.sleep(1)
        yield {"url": url, "client": client, "port": port}
        client.close()
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def seed(db):
    db.create_collection("accounts", validator={"$jsonSchema": {"required": ["email"]}})
    db.accounts.create_index("email", unique=True, name="uniq_email")
    db.accounts.insert_many([{"_id": i, "email": f"user{i}@example.com", "active": i % 2 == 0} for i in range(1, 501)])
    db.orders.create_index([("account_id", 1), ("created", -1)], name="by_account_created")
    db.orders.insert_many([{"account_id": (i % 500) + 1, "total": i * 1.5, "created": i} for i in range(2000)])
    db.sessions.create_index("expires_at", expireAfterSeconds=3600, name="ttl_sessions")
    db.sessions.insert_one({"token": "t1", "expires_at": None})
    db.counters.insert_one({"_id": "order_number", "seq": 2042})  # sequence-style counter
    db.command({"create": "active_accounts", "viewOn": "accounts", "pipeline": [{"$match": {"active": True}}]})


def cli(env, *args, input_text=None):
    result = subprocess.run(
        [sys.executable, "-m", "tools.db_backup", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, input=input_text, timeout=600,
    )
    return result


@pytest.fixture
def env(tmp_path, mongo, s3):
    values = dict(os.environ)
    for key in [k for k in values if k.startswith(("AWS_", "DB_BACKUP", "BACKUP_", "DATABASE_URL", "RESTORE_", "MONGODB_"))]:
        values.pop(key)
    values.update({
        "BACKUP_ENVIRONMENT": "dev",
        "DATABASE_URL": mongo["url"],
        "DB_BACKUP_S3_BUCKET": BUCKET,
        "DB_BACKUP_S3_PREFIX": f"it-{uuid.uuid4().hex[:6]}",
        "DB_BACKUP_S3_ENDPOINT_URL": S3_ENDPOINT,
        "AWS_ACCESS_KEY_ID": S3_KEY,
        "AWS_SECRET_ACCESS_KEY": S3_SECRET,
        "AWS_REGION": "us-east-1",
        "BACKUP_TMP_DIR": str(tmp_path / "work"),
        "BACKUP_USE_DOCKER": "true" if os.environ.get("DB_BACKUP_IT_USE_DOCKER") else "false",
    })
    return values


def test_backup_restore_roundtrip(env, mongo, s3):
    client = mongo["client"]
    client.drop_database("meetq_it")
    seed(client.meetq_it)

    backup = cli(env, "backup", "--label", "integration")
    assert backup.returncode == 0, backup.stdout + backup.stderr
    assert PASSWORD not in backup.stdout + backup.stderr
    backup_id = next(line.strip() for line in backup.stdout.splitlines() if line.strip()[:8].isdigit() and "Z-" in line)

    listing = cli(env, "list")
    assert backup_id in listing.stdout and "integration" in listing.stdout

    # Disaster: the database is gone.
    client.drop_database("meetq_it")
    assert "meetq_it" not in client.list_database_names()

    restore = cli(env, "restore", "--latest", "--target-database-url", mongo["url"], "--target-env", "local")
    assert restore.returncode == 0, restore.stdout + restore.stderr
    assert "Restore completed" in restore.stdout and "✓ checksum" in restore.stdout
    assert PASSWORD not in restore.stdout + restore.stderr

    db = client.meetq_it
    assert db.accounts.count_documents({}) == 500 and db.orders.count_documents({}) == 2000
    assert db.counters.find_one({"_id": "order_number"})["seq"] == 2042
    indexes = db.accounts.index_information()
    assert indexes["uniq_email"]["unique"] is True
    with pytest.raises(pymongo.errors.DuplicateKeyError):
        db.accounts.insert_one({"email": "user1@example.com"})
    assert db.sessions.index_information()["ttl_sessions"]["expireAfterSeconds"] == 3600
    assert "by_account_created" in db.orders.index_information()
    assert db.active_accounts.count_documents({}) == 250  # view restored and working
    options = db.accounts.options()
    assert "validator" in options
    with pytest.raises(pymongo.errors.WriteError):
        db.accounts.insert_one({"no_email": True})
    # References still line up (order → account).
    assert db.accounts.find_one({"_id": db.orders.find_one({"created": 1999})["account_id"]}) is not None

    # Default mode refuses to restore over existing data…
    again = cli(env, "restore", "--backup-id", backup_id, "--target-database-url", mongo["url"])
    assert again.returncode == 2 and "already has" in again.stderr
    # …clean mode replaces it after explicit confirmation.
    db.orders.delete_many({})
    clean = cli(env, "restore", "--backup-id", backup_id, "--target-database-url", mongo["url"], "--mode", "clean", "--yes")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert db.orders.count_documents({}) == 2000

    # Restore into a different database name on the same server.
    other = mongo["url"].replace("/meetq_it?", "/meetq_copy?")
    copy = cli(env, "restore", "--backup-id", backup_id, "--target-database-url", other)
    assert copy.returncode == 0, copy.stdout + copy.stderr
    assert client.meetq_copy.orders.count_documents({}) == 2000


def test_restore_drill_and_verify(env, mongo, s3):
    client = mongo["client"]
    client.drop_database("meetq_it")
    seed(client.meetq_it)
    assert cli(env, "backup").returncode == 0
    verify = cli(env, "verify", "--latest")
    assert verify.returncode == 0, verify.stdout + verify.stderr
    drill = cli(env, "restore-test", "--latest")
    assert drill.returncode == 0, drill.stdout + drill.stderr
    assert "Restore drill passed" in drill.stdout


def test_corrupt_backup_is_never_restored(env, mongo, s3):
    client = mongo["client"]
    client.drop_database("meetq_it")
    seed(client.meetq_it)
    assert cli(env, "backup").returncode == 0
    prefix = f"{env['DB_BACKUP_S3_PREFIX']}/dev/"
    dump_key = next(o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)["Contents"] if o["Key"].endswith(".archive.gz"))
    body = s3.get_object(Bucket=BUCKET, Key=dump_key)["Body"].read()
    s3.put_object(Bucket=BUCKET, Key=dump_key, Body=body[:-1] + bytes([body[-1] ^ 1]))
    client.drop_database("meetq_restore_target")
    restore = cli(env, "restore", "--latest", "--target-database-url", mongo["url"].replace("/meetq_it?", "/meetq_restore_target?"))
    assert restore.returncode == 6 and "Checksum mismatch" in restore.stderr
    assert "meetq_restore_target" not in client.list_database_names()


def test_concurrent_backup_is_refused(env, mongo, s3, tmp_path):
    from tools.db_backup.locking import OperationLock

    with OperationLock(Path(env["BACKUP_TMP_DIR"])):
        busy = cli(env, "backup")
    assert busy.returncode == 3 and "already running" in busy.stderr


def test_wrong_environment_flag_is_refused(env):
    result = cli(env, "--environment", "prod", "backup")
    assert result.returncode == 2 and "does not match" in result.stderr
