"""SHA-256 of large files, streamed in chunks (never loads a dump into memory)."""
from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE = 8 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
