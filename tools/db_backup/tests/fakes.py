"""In-memory boto3 S3 client and a fake mongodump/mongorestore runner."""
from __future__ import annotations

import io
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.db_backup.db import DatabaseInfo, ToolError


class _NotFound(Exception):
    def __init__(self) -> None:
        super().__init__("Not Found")
        self.response = {"Error": {"Code": "404"}}


class FakeS3:
    def __init__(self) -> None:
        self.objects: Dict[str, bytes] = {}
        self.extra: Dict[str, Dict[str, Any]] = {}
        self.fail_upload = False
        self.fail_manifest = False
        self.calls: List[str] = []

    def upload_file(self, filename, bucket, key, ExtraArgs=None, Config=None):
        self.calls.append(f"upload:{key}")
        if self.fail_upload:
            raise ConnectionError("network down")
        self.objects[key] = Path(filename).read_bytes()
        self.extra[key] = ExtraArgs or {}

    def put_object(self, Bucket, Key, Body, **extra):
        self.calls.append(f"put:{Key}")
        if self.fail_manifest:
            raise ConnectionError("network down")
        self.objects[Key] = Body
        self.extra[Key] = extra

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _NotFound()
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _NotFound()
        return {"Body": io.BytesIO(self.objects[Key])}

    def download_file(self, bucket, key, filename, Config=None):
        if key not in self.objects:
            raise _NotFound()
        Path(filename).write_bytes(self.objects[key])

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def get_paginator(self, name):
        objects = self.objects

        class _Paginator:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in sorted(objects) if k.startswith(Prefix)]}

        return _Paginator()


class FakeRunner:
    """Pretends to be mongodump/mongorestore; records argv to prove no secrets leak."""

    use_docker = False
    docker_network = "host"

    def __init__(self, payload: bytes = b"\x1f\x8bFAKE-ARCHIVE" * 100) -> None:
        self.payload = payload
        self.commands: List[List[str]] = []
        self.fail: Optional[str] = None
        self.restore_output = "10 document(s) restored successfully. 0 document(s) failed to restore."

    def available(self, tool: str = "mongodump") -> bool:
        return True

    def version(self, tool: str = "mongodump", server_major: Optional[int] = None) -> str:
        return "100.12.2"

    def run(self, tool, args, *, target, workdir, server_major):
        self.commands.append([tool, *args])
        if self.fail == tool:
            raise ToolError(f"{tool} exited with 1", "Failed: connection refused")
        if tool == "mongodump":
            archive = next(a.split("=", 1)[1] for a in args if a.startswith("--archive="))
            Path(archive).write_bytes(self.payload)
            return "done dumping"
        if "--dryRun" in args:
            return "dry run completed"
        return self.restore_output

    def terminate(self) -> None:
        pass


def db_info(collections: int = 2, major: int = 7) -> DatabaseInfo:
    return DatabaseInfo(
        server_version=f"{major}.0.43",
        database="brseai",
        is_replica_set=False,
        collections=[{"name": f"c{i}", "type": "collection", "documents": 5, "indexes": ["_id_"]} for i in range(collections)],
        data_size=1000,
        storage_size=1000,
        index_size=100,
    )
