"""LiveKit Egress: server-side Room Composite recording written straight to S3.

The egress service joins the room as a hidden recorder, composites every published
track (participant audio/video, screen share, BRSE AI voice) with LiveKit's layout
template and uploads an MP4 to the archive bucket configured in egress.yaml. Video
bytes never pass through the gateway.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from server.config import Settings

logger = logging.getLogger(__name__)

# Provider-neutral job states.
JOB_STARTING = "starting"
JOB_ACTIVE = "active"
JOB_ENDING = "ending"
JOB_COMPLETE = "complete"
JOB_FAILED = "failed"


@dataclass(frozen=True)
class RecordingJob:
    job_id: str
    state: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    size_bytes: Optional[int] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None


class RecordingProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RecordingProvider(Protocol):
    async def start(self, *, room_name: str, object_key: str, layout: str) -> RecordingJob: ...

    async def stop(self, job_id: str) -> Optional[RecordingJob]: ...

    async def get(self, job_id: str) -> Optional[RecordingJob]: ...

    async def aclose(self) -> None: ...


def _from_ns(value: int) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc)


class LiveKitEgressProvider:
    def __init__(self, settings: Settings) -> None:
        url = settings.livekit_ws_url_internal
        self.url = url.replace("wss://", "https://").replace("ws://", "http://")
        self.api_key = settings.livekit_api_key
        self.api_secret = settings.livekit_api_secret
        self._client: Any = None

    def _api(self) -> Any:
        if self._client is None:
            from livekit import api

            self._client = api.LiveKitAPI(url=self.url, api_key=self.api_key, api_secret=self.api_secret)
        return self._client

    @staticmethod
    def _job(info: Any) -> RecordingJob:
        from livekit import api

        status = info.status
        if status == api.EGRESS_STARTING:
            state = JOB_STARTING
        elif status == api.EGRESS_ACTIVE:
            state = JOB_ACTIVE
        elif status == api.EGRESS_ENDING:
            state = JOB_ENDING
        elif status in (api.EGRESS_COMPLETE, api.EGRESS_LIMIT_REACHED):
            state = JOB_COMPLETE
        else:  # EGRESS_FAILED, EGRESS_ABORTED
            state = JOB_FAILED
        size = duration = None
        files = list(info.file_results) or ([info.file] if info.HasField("file") else [])
        if files:
            size = int(files[0].size or 0) or None
            duration = (files[0].duration or 0) / 1_000_000_000 or None
        return RecordingJob(
            job_id=info.egress_id,
            state=state,
            started_at=_from_ns(info.started_at),
            ended_at=_from_ns(info.ended_at),
            size_bytes=size,
            duration_seconds=duration,
            error=info.error or None,
        )

    async def start(self, *, room_name: str, object_key: str, layout: str) -> RecordingJob:
        from livekit import api

        request = api.RoomCompositeEgressRequest(
            room_name=room_name,
            layout=layout,
            file_outputs=[
                # No upload config here: the egress service uses the bucket and
                # credentials from its own config, so no secrets travel in requests.
                api.EncodedFileOutput(file_type=api.EncodedFileType.MP4, filepath=object_key, disable_manifest=True)
            ],
        )
        try:
            info = await self._api().egress.start_room_composite_egress(request)
        except Exception as exc:
            raise RecordingProviderError("recording_provider_unavailable", f"egress start failed: {exc}") from exc
        return self._job(info)

    async def stop(self, job_id: str) -> Optional[RecordingJob]:
        from livekit import api

        try:
            info = await self._api().egress.stop_egress(api.StopEgressRequest(egress_id=job_id))
            return self._job(info)
        except Exception as exc:
            # Already ending/complete: the current state is what matters.
            logger.info("egress stop returned an error (likely already stopped) egress_id=%s: %s", job_id, exc)
            return await self.get(job_id)

    async def get(self, job_id: str) -> Optional[RecordingJob]:
        from livekit import api

        response = await self._api().egress.list_egress(api.ListEgressRequest(egress_id=job_id))
        items = list(response.items)
        return self._job(items[0]) if items else None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
