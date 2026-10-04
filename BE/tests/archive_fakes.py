"""In-memory stand-ins for S3 storage and LiveKit Egress (no AWS / LiveKit in unit tests)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from server.service.archive.egress import (
    JOB_ACTIVE,
    JOB_COMPLETE,
    JOB_ENDING,
    JOB_FAILED,
    JOB_STARTING,
    RecordingJob,
    RecordingProviderError,
)
from server.service.archive.retention import utcnow
from server.service.archive.storage import StorageError, StoredObject


class MemoryStorage:
    def __init__(self, bucket: str = "meetq-archive-test") -> None:
        self.bucket = bucket
        self.objects: Dict[str, bytes] = {}
        self.tags: Dict[str, Dict[str, str]] = {}
        self.fail_puts = 0
        self.presigned: List[str] = []

    async def ensure_private_bucket(self) -> None:
        return None

    async def put_json(self, key: str, payload: Any, *, tags: Optional[Dict[str, str]] = None) -> StoredObject:
        if self.fail_puts:
            self.fail_puts -= 1
            raise StorageError("s3 put_object failed: EndpointConnectionError")
        body = json.dumps(payload, ensure_ascii=False, default=str).encode()
        self.objects[key] = body
        self.tags[key] = dict(tags or {})
        return StoredObject(key=key, size=len(body))

    def put_media(self, key: str, size: int) -> None:
        self.objects[key] = b"\0" * size

    async def head(self, key: str) -> Optional[StoredObject]:
        body = self.objects.get(key)
        return StoredObject(key=key, size=len(body)) if body is not None else None

    async def list_keys(self, prefix: str) -> List[str]:
        return [key for key in self.objects if key.startswith(prefix)]

    async def delete_prefix(self, prefix: str) -> int:
        keys = await self.list_keys(prefix)
        for key in keys:
            self.objects.pop(key, None)
        return len(keys)

    def presigned_get_url(self, key: str, *, expires_in: int, download_name: Optional[str] = None) -> str:
        url = f"https://s3.test/{self.bucket}/{key}?X-Amz-Expires={expires_in}" + ("&dl=1" if download_name else "")
        self.presigned.append(url)
        return url

    def json(self, key: str) -> Any:
        return json.loads(self.objects[key])


class FakeEgress:
    """Controllable egress: tests decide each job's state."""

    def __init__(self) -> None:
        self.jobs: Dict[str, RecordingJob] = {}
        self.start_calls: List[Dict[str, str]] = []
        self.stop_calls: List[str] = []
        self.start_state = JOB_ACTIVE
        self.fail_start = False
        self.storage: Optional[MemoryStorage] = None
        self.keys: Dict[str, str] = {}

    async def start(self, *, room_name: str, object_key: str, layout: str) -> RecordingJob:
        self.start_calls.append({"room_name": room_name, "object_key": object_key, "layout": layout})
        if self.fail_start:
            raise RecordingProviderError("recording_provider_unavailable", "egress not connected")
        job_id = f"EG_{len(self.start_calls)}"
        job = RecordingJob(job_id=job_id, state=self.start_state, started_at=utcnow() if self.start_state == JOB_ACTIVE else None)
        self.jobs[job_id] = job
        self.keys[job_id] = object_key
        return job

    def set_state(self, job_id: str, state: str, **fields: Any) -> None:
        job = self.jobs[job_id]
        values = {**job.__dict__, "state": state, **fields}
        if state == JOB_ACTIVE and values.get("started_at") is None:
            values["started_at"] = utcnow()
        self.jobs[job_id] = RecordingJob(**values)

    def complete(self, job_id: str, *, size: int = 4_000_000, duration: float = 42.0) -> None:
        if self.storage is not None:
            self.storage.put_media(self.keys[job_id], size)
        self.set_state(job_id, JOB_COMPLETE, ended_at=utcnow(), size_bytes=size, duration_seconds=duration)

    async def stop(self, job_id: str) -> Optional[RecordingJob]:
        self.stop_calls.append(job_id)
        job = self.jobs.get(job_id)
        if job and job.state in (JOB_STARTING, JOB_ACTIVE):
            self.set_state(job_id, JOB_ENDING, ended_at=utcnow())
        return self.jobs.get(job_id)

    async def get(self, job_id: str) -> Optional[RecordingJob]:
        return self.jobs.get(job_id)

    async def aclose(self) -> None:
        return None


__all__ = ["MemoryStorage", "FakeEgress", "JOB_FAILED", "JOB_ACTIVE", "JOB_STARTING"]
