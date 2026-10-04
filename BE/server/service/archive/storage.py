"""Private S3 storage for meeting archives (boto3, run in worker threads).

Objects are never public: the bucket blocks public access (Terraform) and the only
way to read an object is a short-lived presigned URL issued after authorization.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from server.config import Settings

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 4
_BASE_DELAY_SECONDS = 0.5


class StorageError(Exception):
    pass


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int


def storage_configured(settings: Settings) -> bool:
    return bool((settings.meeting_archive_bucket or "").strip())


class ArchiveStorage:
    def __init__(self, settings: Settings, *, client: Any = None, presign_client: Any = None) -> None:
        self.bucket = (settings.meeting_archive_bucket or "").strip()
        self.settings = settings
        self._client = client
        self._presign_client = presign_client

    def _make_client(self, endpoint: Optional[str]) -> Any:
        import boto3
        from botocore.config import Config

        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if self.settings.s3_force_path_style else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
        )
        return boto3.client(
            "s3",
            region_name=self.settings.aws_region or None,
            endpoint_url=endpoint or None,
            config=config,
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._make_client(self.settings.s3_endpoint_url)
        return self._client

    @property
    def presign_client(self) -> Any:
        if self._presign_client is None:
            public = self.settings.s3_public_endpoint_url
            self._presign_client = self._make_client(public) if public else self.client
        return self._presign_client

    async def _call(self, operation: str, fn, *args, **kwargs) -> Any:
        """Bounded exponential backoff around one S3 call."""
        last_error: Optional[BaseException] = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await asyncio.to_thread(fn, *args, **kwargs)
            except Exception as exc:  # botocore raises many types
                last_error = exc
                if _is_not_found(exc) or attempt == _MAX_ATTEMPTS:
                    break
                delay = _BASE_DELAY_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.2)
                logger.warning("s3 %s failed (attempt %d), retrying in %.1fs: %s", operation, attempt, delay, type(exc).__name__)
                await asyncio.sleep(delay)
        raise StorageError(f"s3 {operation} failed: {type(last_error).__name__}") from last_error

    async def ensure_private_bucket(self) -> None:
        """Local development: create the bucket and block every form of public access."""
        try:
            await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)
        except Exception:
            kwargs: Dict[str, Any] = {"Bucket": self.bucket}
            region = self.settings.aws_region
            if region and region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
            await asyncio.to_thread(self.client.create_bucket, **kwargs)
        try:
            await asyncio.to_thread(
                self.client.put_public_access_block,
                Bucket=self.bucket,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                },
            )
        except Exception:
            logger.warning("could not set public access block on local bucket", exc_info=True)

    async def put_json(self, key: str, payload: Any, *, tags: Optional[Dict[str, str]] = None) -> StoredObject:
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        kwargs: Dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": body,
            "ContentType": "application/json; charset=utf-8",
        }
        if self.settings.s3_server_side_encryption:
            kwargs["ServerSideEncryption"] = self.settings.s3_server_side_encryption
        if tags:
            kwargs["Tagging"] = "&".join(f"{quote(k)}={quote(str(v))}" for k, v in tags.items())
        await self._call("put_object", self.client.put_object, **kwargs)
        return StoredObject(key=key, size=len(body))

    async def head(self, key: str) -> Optional[StoredObject]:
        try:
            response = await self._call("head_object", self.client.head_object, Bucket=self.bucket, Key=key)
        except StorageError as exc:
            if _is_not_found(exc.__cause__):
                return None
            raise
        return StoredObject(key=key, size=int(response.get("ContentLength") or 0))

    async def list_keys(self, prefix: str) -> List[str]:
        keys: List[str] = []
        token: Optional[str] = None
        while True:
            kwargs: Dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = await self._call("list_objects_v2", self.client.list_objects_v2, **kwargs)
            keys.extend(item["Key"] for item in page.get("Contents", []) or [])
            if not page.get("IsTruncated"):
                return keys
            token = page.get("NextContinuationToken")

    async def delete_prefix(self, prefix: str) -> int:
        """Deletes every object under prefix. Idempotent: an empty prefix is success."""
        if not prefix.endswith("/"):
            raise ValueError("prefix must end with '/'")
        keys = await self.list_keys(prefix)
        deleted = 0
        for start in range(0, len(keys), 1000):
            batch = keys[start:start + 1000]
            response = await self._call(
                "delete_objects",
                self.client.delete_objects,
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )
            errors = [error for error in (response.get("Errors") or []) if error.get("Code") != "NoSuchKey"]
            if errors:
                raise StorageError(f"s3 delete_objects failed for {len(errors)} object(s)")
            deleted += len(batch)
        return deleted

    def presigned_get_url(self, key: str, *, expires_in: int, download_name: Optional[str] = None) -> str:
        params: Dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if download_name:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
        return self.presign_client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in)


def _is_not_found(exc: Optional[BaseException]) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str((response.get("Error") or {}).get("Code") or "")
        return code in {"404", "NoSuchKey", "NotFound"}
    return False
