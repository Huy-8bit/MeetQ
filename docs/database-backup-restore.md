# Database backup & restore

`tools/db_backup` is a standalone CLI that takes **logical backups of the MeetQ MongoDB database** and stores them in a private S3 bucket. It can list, verify and download them, and restore one into any target database with safety checks. It runs from a laptop, a VM/EC2 or the Docker host, and does not depend on the web application.

> **Logical backup, not PITR.** Each backup is a `mongodump` of one database at the time it runs. Restoring brings the data back to that backup, not to an arbitrary moment. See [Future: point-in-time recovery](#future-point-in-time-recovery).

## Database discovered

| | |
| --- | --- |
| Engine | MongoDB **7.0** (`mongo:7`), standalone server (no replica set), `--auth` |
| Database | `brseai` (`MONGODB_DATABASE`) |
| Connection | `MONGODB_URL`, or `MONGODB_HOST/PORT/DATABASE/USERNAME/PASSWORD/AUTH_SOURCE` (gateway settings) |
| Native tools | MongoDB Database Tools 100.x: `mongodump` / `mongorestore` (in the `mongo:7` image; `brew install mongodb-database-tools` on macOS) |
| Not backed up | Redis (live room state with TTLs, rebuilt by the app), S3 meeting archives (they live in S3 and have their own retention) |

## Architecture

```text
MongoDB ──mongodump --archive --gzip──► temp file (BACKUP_TMP_DIR)
                                           │
                     mongorestore --dryRun (must be readable)
                                           │
                           SHA-256 (streamed) + manifest
                                           │
                 S3: database.archive.gz ──then── manifest.json (completion marker)
                                           │
                           verify object size, delete temp file

Restore:
S3 manifest ─► plan + safety checks ─► download (streamed) ─► SHA-256 == manifest?
   ─► (pre-restore backup of the target) ─► mongorestore ─► verify collections, indexes, counts
```

| Topic | Behaviour |
| --- | --- |
| Format | `mongodump --archive --gzip`: one compressed file, selective/renaming restore, parallel collections. No `--drop` or other destructive option is baked in; the restore command decides |
| Consistency | `mongodump` reads with snapshot reads per collection. On this **standalone** server the collections are not captured at one single instant (that needs `--oplog` on a replica set). For a quiet copy, take the backup at a low-traffic time. The tool never `SELECT`s/finds documents itself |
| Verification | Backup counts only after `mongorestore --dryRun` reads the archive, the SHA-256 is recorded, both uploads succeed and the S3 size matches. Restore refuses any file whose SHA-256 differs from the manifest |
| Secrets | The password goes to `mongodump`/`mongorestore` through a `--config` file (mode 0600, deleted after use), never through argv, so it doesn't appear in `ps` or shell history. Logs show `mongodb://user:***@host/db`. The manifest contains no URL, password or AWS key |
| Large databases | Dump, checksum, upload and download are all streamed. Nothing is loaded into memory. S3 transfers use boto3 multipart |
| Concurrency | `flock` on `$BACKUP_TMP_DIR/db-backup.lock`: a second backup or restore exits with code 3 ("Another backup or restore is already running."). The kernel releases the lock if the process dies |
| Signals | SIGINT/SIGTERM stop the child `mongodump`/`mongorestore`, remove temp files and release the lock (exit 130) |
| Disk | Before dumping, the tool requires free space ≥ 1.2 × (storage + index size). Otherwise: "Insufficient disk space. Estimated backup requirement … Available …" |

### S3 layout

```text
s3://<DB_BACKUP_S3_BUCKET>/<DB_BACKUP_S3_PREFIX>/<environment>/<YYYY>/<MM>/<DD>/<backup_id>/
    database.archive.gz
    manifest.json
```

The backup ID looks like `20261005T020000Z-a13f92` (UTC time plus a random suffix). The environment prefix (`dev`, `staging`, `prod`) comes only from the validated environment, so `--environment dev` can never write under `prod/`. A folder without a `complete` manifest is ignored by `list`, `latest` and `restore`.

Objects are tagged `environment`, `database` and `backup_type` (`manual` | `scheduled` | `pre_restore`), with no secrets.

### Manifest

```json
{
  "manifest_version": 1,
  "status": "complete",
  "backup_id": "20261005T020000Z-a13f92",
  "created_at": "2026-10-05T02:00:00Z",
  "completed_at": "2026-10-05T02:01:42Z",
  "environment": "prod",
  "trigger": "scheduled",
  "label": null,
  "database": {
    "engine": "mongodb", "version": "7.0.43", "major_version": 7, "name": "brseai", "topology": "standalone",
    "collections": [{"name": "rooms", "type": "collection", "documents": 1532, "indexes": ["_id_", "..."]}],
    "data_size_bytes": 7340032
  },
  "backup": {"format": "mongodump-archive-gzip", "file": "database.archive.gz", "size_bytes": 842000000,
             "sha256": "…", "logical": true, "point_in_time": false},
  "tool": {"name": "meetq-db-backup", "version": "1.0.0", "dump_tool": "mongodump 100.12.2",
           "hostname": "meetq-prod-1", "git_commit": "26ff6ff…", "docker": false}
}
```

MeetQ has no schema-migration table, so no `schema_version` is recorded. `git_commit` shows which app version wrote the data.

## Requirements

- Python ≥ 3.10. The scripts create `tools/db_backup/.venv` with `pymongo` and `boto3` on first run.
- `mongodump`/`mongorestore` (MongoDB Database Tools 100.x), **or** Docker with `--use-docker`, which runs them in `mongo:<server major>`.
- AWS credentials from the normal chain (`AWS_PROFILE`, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN`, or an EC2/ECS role).

## Configuration

```bash
cp .env.backup.example .env.backup   # git-ignored
chmod 600 .env.backup
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `BACKUP_ENVIRONMENT` | — | `dev`, `staging` or `prod` (`production` is accepted). `--environment` must match it if both are set |
| `DATABASE_URL` | — | Source database, e.g. `mongodb://backup_user:…@127.0.0.1:27017/brseai?authSource=admin`. Fallback: the app's `MONGODB_*` |
| `RESTORE_DATABASE_URL` | — | Restore target if `--target-database-url` isn't given. `DATABASE_URL` is **never** used as a target |
| `DB_BACKUP_S3_BUCKET` / `DB_BACKUP_S3_PREFIX` | — / `database-backups` | Where backups go |
| `AWS_REGION`, `AWS_PROFILE` | — | AWS settings (normal chain) |
| `BACKUP_TMP_DIR` | `/tmp/meetq-db-backup` | Temp dumps (own subdirectories only) |
| `KEEP_LOCAL_BACKUP` | `false` | Keep the local dump after upload |
| `BACKUP_RETENTION_DAYS` / `MIN_BACKUPS_TO_KEEP` | `30` / `3` | Used by `prune` |
| `RESTORE_JOBS` | `4` | `mongorestore --numParallelCollections` |
| `BACKUP_USE_DOCKER` / `BACKUP_DOCKER_NETWORK` | `false` / `host` | Run the tools in Docker |
| `BACKUP_NOTIFY_TELEGRAM` + `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` | `false` | Message the existing MeetQ Telegram chat when a backup fails |
| `DB_BACKUP_S3_ENDPOINT_URL` | — | S3-compatible endpoint, for local testing only |

### Database users

Use dedicated users rather than the root account:

```javascript
// mongosh (as an admin) on the production server
db.getSiblingDB("admin").createUser({ user: "backup_user", pwd: passwordPrompt(), roles: [{ role: "backup", db: "admin" }] })
db.getSiblingDB("admin").createUser({ user: "restore_user", pwd: passwordPrompt(), roles: [{ role: "restore", db: "admin" }] })
```

- The built-in `backup` role covers `mongodump` of `brseai`, including `system.views`; it can't write.
- `restore` is needed only on the database you restore into.
- In production, MongoDB is published on **127.0.0.1:27017 only** (see `docker-compose.prod.yml`), so the host-side tool can connect while nothing outside the server can.

## AWS setup (once)

The dedicated bucket comes from Terraform in `infra/terraform/db-backups`. It is separate from the meeting-archive bucket because access, lifecycle and retention differ. It has:
- public access blocked (all four settings), ACLs disabled, SSE-S3, and a deny on non-TLS requests;
- no versioning;
- per-environment expiry (dev/staging 14 days, prod 30) and abort of incomplete multipart uploads after 1 day.

```bash
cd infra/terraform/db-backups
cp env/main.tfvars.example env/main.tfvars
terraform init
terraform plan  -var-file=env/main.tfvars
terraform apply -var-file=env/main.tfvars
aws iam create-access-key --user-name meetq-db-backup-writer   # on the backup host only
aws iam create-access-key --user-name meetq-db-backup-reader   # optional: restore-only laptops
```

| Principal | Permissions (scoped to `<prefix>/<env>/*`) |
| --- | --- |
| `meetq-db-backup-writer` (scheduler, manual backups) | `ListBucket` (prefix), `PutObject`, `PutObjectTagging`, `GetObject`, `AbortMultipartUpload`, `ListMultipartUploadParts`; plus `DeleteObject` only with `allow_prune = true` |
| `meetq-db-backup-reader` (restore only) | `ListBucket` (prefix), `GetObject` |
| EC2/ECS role | Attach the writer policy via `writer_role_names` instead of an access key |

Transport is TLS (the bucket denies plain HTTP). At rest, data is protected by SSE-S3. Client-side encryption is a possible later addition.

## Quick start

```bash
cp .env.backup.example .env.backup          # set DATABASE_URL, bucket, AWS profile, environment
./scripts/db-backup.sh                       # manual backup
./scripts/db-backup-list.sh                  # list backups
./scripts/db-restore.sh --latest --target-database-url "$LOCAL_DATABASE_URL"   # restore latest to local
```

### Laptop workflow

```bash
AWS_PROFILE=meetq-prod ./scripts/db-backup.sh --environment prod --label before-release-v2
./scripts/db-backup-list.sh --environment prod
./scripts/db-restore.sh --backup-id 20261005T020000Z-a13f92 --environment prod \
  --target-database-url "$LOCAL_DATABASE_URL"            # --target-env defaults to local
```

The laptop needs network access to the database (VPN or SSH tunnel, e.g. `ssh -L 27017:127.0.0.1:27017 prod-host`). A production backup restored on a laptop **contains production data**: keep it on an encrypted disk and drop it when done. No sanitization is applied.

### Commands

| Command | Purpose |
| --- | --- |
| `backup [--label X] [--trigger manual\|scheduled] [--keep-local]` | Dump, verify, checksum, upload |
| `list [--limit 20] [--json]` | Complete backups of the environment, newest first |
| `info <id>` | Print the manifest |
| `download <id> [--output DIR]` | Download + verify the SHA-256 |
| `verify --backup-id ID \| --latest` | Download, check SHA-256 and archive readability |
| `restore …` | See below |
| `restore-test --backup-id ID \| --latest` | Restore drill into a throw-away `mongo:<major>` container, verify, remove |
| `prune [--dry-run] [--yes]` | Delete backups older than `BACKUP_RETENTION_DAYS`, never the newest `MIN_BACKUPS_TO_KEEP` |
| `cleanup-local [--older-than-hours 24]` | Remove stale `meetq-db-backup-*` dirs in `BACKUP_TMP_DIR` (nothing else) |

Global options: `--environment`, `--env-file`, `--use-docker`, `--docker-network`, `--quiet`, `--verbose`.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | ok |
| 2 | configuration/validation |
| 3 | another run active |
| 4 | dump failed |
| 5 | upload/download failed |
| 6 | verification (checksum, readability, size) |
| 7 | restore failed |
| 130 | interrupted |

## Automatic backups (server)

```bash
sudo ./scripts/install-backup-schedule.sh      # systemd timer, daily 02:00 (BACKUP_ON_CALENDAR to change)
systemctl list-timers meetq-db-backup.timer   # next run
systemctl status meetq-db-backup.service      # last result
journalctl -u meetq-db-backup.service         # logs (JSON lines, no secrets)
sudo systemctl start meetq-db-backup.service  # run now
```

The unit (`deploy/systemd/`) reads `.env.backup`, runs `scripts/db-backup.sh --quiet --trigger scheduled`, then removes stale temp directories. A failed backup makes the service fail (non-zero exit), and Telegram is notified if that's enabled. Without systemd, use `./scripts/install-backup-schedule.sh --print-cron`; nothing is installed silently:

```cron
0 2 * * * cd /opt/meetq && ./scripts/db-backup.sh --quiet --trigger scheduled >> /var/log/meetq-db-backup.log 2>&1
```

## Restore

```bash
./scripts/db-restore.sh --backup-id ID|--latest [--environment prod] \
  --target-database-url URL [--target-env local|test|dev|staging|prod|custom] \
  [--mode empty|clean] [--dry-run] [--pre-restore-backup] [--yes] [--confirm-production]
```

1. Finds the backup in the **source environment only** (`--latest` never picks a dev backup when restoring prod).
2. Validates the manifest: complete, engine `mongodb`, format, environment.
3. Connects to the target and checks the version: target major ≥ source major, unless `--allow-version-mismatch`.
4. Prints the **Restore Plan**; `--dry-run` stops here.
5. Confirmation:
   - `clean` over existing data asks you to type `RESTORE` (or pass `--yes`).
   - A **production** target needs `--confirm-production` **and** typing `RESTORE PRODUCTION`, or `--yes` together with `--confirm-production`.
   - A target that is the configured production `DATABASE_URL` but labelled non-prod is refused.
6. Downloads and verifies the SHA-256 (abort on mismatch).
7. Pre-restore backup of the target (trigger `pre_restore`). This is the default for production; `--skip-pre-restore-backup` prints a strong warning.
8. Runs `mongorestore --nsFrom <source>.* --nsTo <target>.* --stopOnError [--drop]`. Any failed document fails the restore.
9. Verifies: connection, every collection and view, every index, document counts ≥ the manifest's counts.

Modes:
- `empty` (default): the target must have no collections.
- `clean`: drop each collection in the backup, then restore it. Collections not in the backup are left untouched.

The tool never drops a whole database and never kills connections. If other clients are connected, it warns you to stop the app first.

## Disaster recovery

1. Provision a new MongoDB 7 server (or `docker compose up mongo` on a new host) and create `restore_user`.
2. Find the latest valid backup: `./scripts/db-backup-list.sh --environment prod`.
3. Check it: `python -m tools.db_backup --environment prod verify --latest` (or `restore-test --latest`).
4. Restore:
   ```bash
   ./scripts/db-restore.sh --latest --environment prod --target-database-url "$NEW_DB_URL" \
     --target-env prod --confirm-production --skip-pre-restore-backup
   ```
   Pre-restore backup is skipped here because the new database is empty.
5. Check the verification report (collections, indexes, counts).
6. Point the app at the new database (`MONGODB_URL` / `MONGODB_HOST` in `.env.production`).
7. Start the application.

Run `restore-test --latest` regularly. A backup is only worth something once it has been restored.

## Retention

- S3 lifecycle (Terraform `retention_days`) expires old backups per environment: the simple default, prod 30 days.
- Lifecycle can't guarantee a minimum number of backups. If backups stop for longer than the period, the last ones expire too. Where that matters, set `retention_days.prod = 0` and run `prune` (keeps `MIN_BACKUPS_TO_KEEP`, needs `allow_prune = true`) from the scheduler.

## Security

- No credentials in Git: `.env.backup` and `*.tfvars` are git-ignored. Access keys are created out of band, never by Terraform.
- Private bucket (all public-access blocks, `BucketOwnerEnforced`), SSE-S3, TLS-only bucket policy, least-privilege IAM per prefix.
- No secrets in logs, argv, the manifest or S3 tags.
- Backups are never stored in Git or kept on the application disk (temp files are removed, also after failures).

## Tests

```bash
tools/db_backup/.venv/bin/python -m pip install -r tools/db_backup/requirements-dev.txt
tools/db_backup/.venv/bin/python -m pytest tools/db_backup/tests -v
```

- `test_unit.py` uses a fake S3 and a fake runner. It covers config, password masking, manifest/key layout, environment separation, latest selection, streamed checksums, locking (including crash release), the production guard, dry run, checksum mismatch, failed documents, version mismatch, disk space, upload failures and prune minimum.
- `test_integration.py` runs a real `mongo:7` container with auth, the real CLI and the local S3-compatible service (`http://localhost:9000` from `make dev`; never a production bucket). It seeds collections, a unique index, TTL index, compound index, a counter (sequence) document, a view, a schema validator and cross-collection references. Then:
  - backup → drop database → restore → everything is checked;
  - default mode refuses to restore over data, and clean mode replaces it;
  - restore into a different database name works;
  - `verify` and `restore-test` pass;
  - a tampered dump is refused (exit 6) with nothing written;
  - a concurrent run is refused (exit 3) and a mismatched environment exits 2.

  It also passes with `DB_BACKUP_IT_USE_DOCKER=1` (tools in Docker).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `mongodump is not installed` | `brew install mongodb-database-tools` / `apt install mongodb-database-tools`, or `--use-docker` |
| `not authorized … system.views` | Use a user with the `backup` role |
| `MongoDB version mismatch` | Restore into a server with the same or a newer major version |
| `Checksum mismatch. ABORT.` | The object was modified or corrupted. Use another backup |
| `Another backup or restore is already running.` | Wait. The lock is freed automatically if the other process died |
| `Insufficient disk space` | Point `BACKUP_TMP_DIR` at a larger disk |
| Exit 5 on upload | Check AWS credentials, `AWS_REGION` and the bucket policy (TLS) |

## Future: point-in-time recovery

PITR would need a replica set plus continuous oplog capture (or a managed service with PITR, e.g. MongoDB Atlas): a base backup plus oplog replay up to a chosen timestamp. That is out of scope; this tool covers dump → S3 → restore.
