"""One backup/restore at a time per host + temp dir.

`flock` locks are released by the kernel when the process exits, so a crashed or
killed run never leaves a stale lock behind.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Optional


class LockBusyError(Exception):
    pass


class OperationLock:
    def __init__(self, directory: Path, name: str = "db-backup.lock") -> None:
        self.path = directory / name
        self._fd: Optional[int] = None

    def acquire(self) -> "OperationLock":
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise LockBusyError("Another backup or restore is already running.")
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd
        return self

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self) -> "OperationLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()
