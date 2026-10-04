"""Background jobs (run inside the gateway process).

  recordings  every ~3s   reconcile egress jobs, auto-stop when a room ends
  archive     every ~20s  finalize ended meetings, retry failed uploads
  cleanup     hourly      delete archives whose expires_at has passed

Each tick takes a short Redis lease so only one gateway instance runs a job at a
time; every job is idempotent, so a crash mid-tick is repaired on the next one.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, List, Optional

from server.service.archive.archive_service import ArchiveService
from server.service.archive.recording_service import RecordingService

logger = logging.getLogger(__name__)

_LEASE_KEY = "brseai:v1:worker:{name}"


class ArchiveWorker:
    def __init__(
        self,
        redis: Any,
        recordings: RecordingService,
        archives: ArchiveService,
        *,
        recording_interval: float,
        archive_interval: float,
        cleanup_interval: float,
    ) -> None:
        self.redis = redis
        self.recordings = recordings
        self.archives = archives
        self.intervals = {
            "recordings": recording_interval,
            "archive": archive_interval,
            "cleanup": cleanup_interval,
        }
        self._tasks: List[asyncio.Task] = []

    def start(self) -> None:
        jobs = {
            "recordings": self.recordings.reconcile_once,
            "archive": self._archive_tick,
            "cleanup": self.archives.cleanup_expired,
        }
        for name, job in jobs.items():
            self._tasks.append(asyncio.create_task(self._loop(name, job), name=f"archive-worker-{name}"))

    async def _archive_tick(self) -> None:
        await self.archives.finalize_ended_meetings()
        await self.archives.settle_processing()

    async def _lease(self, name: str, interval: float) -> bool:
        ttl = max(5, int(interval * 2))
        try:
            return bool(await self.redis.set(_LEASE_KEY.format(name=name), "1", ex=ttl, nx=True))
        except Exception:
            logger.warning("worker lease unavailable job=%s", name, exc_info=True)
            return False

    async def _release(self, name: str) -> None:
        try:
            await self.redis.delete(_LEASE_KEY.format(name=name))
        except Exception:
            pass

    async def _loop(self, name: str, job: Callable[[], Awaitable[Any]]) -> None:
        interval = self.intervals[name]
        # Cleanup runs once shortly after start-up, then on its interval.
        await asyncio.sleep(min(interval, 10.0))
        while True:
            if await self._lease(name, interval):
                try:
                    await job()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("archive worker job failed job=%s", name)
                finally:
                    await self._release(name)
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
