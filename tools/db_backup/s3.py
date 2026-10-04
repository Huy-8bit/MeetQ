"""Private S3 backup store (boto3 transfer manager: multipart + retries + streaming).

A backup is valid only when both the dump and a manifest with status "complete"
exist under its folder; the manifest is always written last.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from tools.db_backup.config import Settings
from tools.db_backup.manifest import (
    DUMP_FILE,
    MANIFEST_FILE,
    BackupKeys,
    ManifestError,
    backup_time,
    environment_prefix,
)


class StoreError(Exception):
    pass


@dataclass(frozen=True)
class BackupEntry:
    backup_id: str
    environment: str
    keys: BackupKeys
    manifest: Dict[str, Any]

    @property
    def created_at(self) -> str:
        return str(self.manifest.get("created_at", ""))

    @property
    def size_bytes(self) -> int:
        return int((self.manifest.get("backup") or {}).get("size_bytes") or 0)


def _client(settings: Settings) -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.s3_endpoint_url,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 5, "mode": "standard"},
            connect_timeout=10,
            read_timeout=60,
            s3={"addressing_style": "path" if settings.s3_endpoint_url else "auto"},
        ),
    )


class BackupStore:
    def __init__(self, settings: Settings, client: Any = None) -> None:
        self.settings = settings
        self.bucket = settings.require_bucket()
        self.client = client or _client(settings)

    def keys(self, environment: str, backup_id: str) -> BackupKeys:
        return BackupKeys(self.settings.prefix, environment, backup_id)

    def _transfer_config(self) -> Any:
        from boto3.s3.transfer import TransferConfig

        return TransferConfig(multipart_threshold=64 * 1024 * 1024, multipart_chunksize=64 * 1024 * 1024, max_concurrency=4)

    def _extra(self, tags: Optional[Dict[str, str]], content_type: str) -> Dict[str, Any]:
        extra: Dict[str, Any] = {"ContentType": content_type}
        if not self.settings.s3_endpoint_url:
            extra["ServerSideEncryption"] = "AES256"  # bucket default too; explicit on AWS
        if tags:
            from urllib.parse import urlencode

            extra["Tagging"] = urlencode(tags)
        return extra

    def upload_dump(self, path: Path, keys: BackupKeys, tags: Optional[Dict[str, str]] = None) -> None:
        try:
            self.client.upload_file(
                str(path), self.bucket, keys.dump,
                ExtraArgs=self._extra(tags, "application/gzip"),
                Config=self._transfer_config(),
            )
        except Exception as exc:
            raise StoreError(f"Upload of the dump failed: {type(exc).__name__}") from exc

    def upload_manifest(self, manifest: Dict[str, Any], keys: BackupKeys, tags: Optional[Dict[str, str]] = None) -> None:
        body = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        try:
            extra = self._extra(tags, "application/json")
            self.client.put_object(Bucket=self.bucket, Key=keys.manifest, Body=body, **extra)
        except Exception as exc:
            raise StoreError(f"Upload of the manifest failed: {type(exc).__name__}") from exc

    def object_size(self, key: str) -> Optional[int]:
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise StoreError(f"Could not read {key}: {type(exc).__name__}") from exc
        return int(response["ContentLength"])

    def read_manifest(self, keys: BackupKeys) -> Dict[str, Any]:
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=keys.manifest)["Body"].read()
        except Exception as exc:
            raise StoreError(f"Backup {keys.backup_id} has no readable manifest.") from exc
        return json.loads(body)

    def download_dump(self, keys: BackupKeys, destination: Path) -> None:
        """Streams to disk; the caller verifies the SHA-256 against the manifest."""
        try:
            self.client.download_file(self.bucket, keys.dump, str(destination), Config=self._transfer_config())
        except Exception as exc:
            raise StoreError(f"Download of {keys.backup_id} failed: {type(exc).__name__}") from exc

    def _iter_keys(self, prefix: str) -> Iterator[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for item in page.get("Contents", []) or []:
                yield item["Key"]

    def list_backups(self, environment: str, *, limit: Optional[int] = None) -> List[BackupEntry]:
        """Complete backups of one environment, newest first."""
        folders: Dict[str, set] = {}
        for key in self._iter_keys(environment_prefix(self.settings.prefix, environment)):
            folder, _, name = key.rpartition("/")
            folders.setdefault(folder, set()).add(name)
        candidates = []
        for folder, names in folders.items():
            backup_id = folder.rsplit("/", 1)[-1]
            if DUMP_FILE not in names or MANIFEST_FILE not in names:
                continue  # incomplete upload: never listed
            try:
                keys = self.keys(environment, backup_id)
            except ManifestError:
                continue
            if keys.folder.rstrip("/") != folder:
                continue
            candidates.append(keys)
        candidates.sort(key=lambda k: backup_time(k.backup_id), reverse=True)
        entries: List[BackupEntry] = []
        for keys in candidates:
            try:
                manifest = self.read_manifest(keys)
            except (StoreError, ValueError):
                continue
            if manifest.get("status") != "complete" or manifest.get("environment") != environment:
                continue
            entries.append(BackupEntry(keys.backup_id, environment, keys, manifest))
            if limit and len(entries) >= limit:
                break
        return entries

    def find(self, environment: str, backup_id: str) -> BackupEntry:
        keys = self.keys(environment, backup_id)
        if self.object_size(keys.manifest) is None or self.object_size(keys.dump) is None:
            raise StoreError(f"Backup {backup_id} was not found in {environment} (or is incomplete).")
        manifest = self.read_manifest(keys)
        return BackupEntry(backup_id, environment, keys, manifest)

    def latest(self, environment: str) -> BackupEntry:
        entries = self.list_backups(environment, limit=1)
        if not entries:
            raise StoreError(f"No complete backup found for {environment}.")
        return entries[0]

    def delete_backup(self, keys: BackupKeys) -> None:
        # Manifest first: from that moment the backup is no longer listed as valid.
        for key in (keys.manifest, keys.dump):
            try:
                self.client.delete_object(Bucket=self.bucket, Key=key)
            except Exception as exc:
                raise StoreError(f"Delete of {key} failed: {type(exc).__name__}") from exc
