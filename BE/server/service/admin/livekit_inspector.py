"""Read-only LiveKit server API access for the admin portal.

Only track *metadata* is read (published / muted). The admin portal never
subscribes to participant audio or video.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from server.config import Settings

logger = logging.getLogger(__name__)

LIVEKIT_ADMIN_TIMEOUT_SECONDS = 2.5


def livekit_http_url(ws_url: str) -> str:
    url = (ws_url or "").strip()
    if url.startswith("wss://"):
        return "https://" + url[len("wss://"):]
    if url.startswith("ws://"):
        return "http://" + url[len("ws://"):]
    return url


def _track_state(tracks: list, source: str) -> str:
    matching = [track for track in tracks if track["source"] == source]
    if not matching:
        return "off"
    return "muted" if all(track["muted"] for track in matching) else "on"


class LiveKitInspector:
    def __init__(self, settings: Settings) -> None:
        self.url = livekit_http_url(settings.livekit_ws_url_internal)
        self.api_key = settings.livekit_api_key
        self.api_secret = settings.livekit_api_secret

    def _client(self):
        import aiohttp
        from livekit import api

        return api.LiveKitAPI(
            self.url,
            self.api_key,
            self.api_secret,
            timeout=aiohttp.ClientTimeout(total=LIVEKIT_ADMIN_TIMEOUT_SECONDS),
        )

    async def ping(self) -> bool:
        from livekit import api

        client = self._client()
        try:
            await asyncio.wait_for(
                client.room.list_rooms(api.ListRoomsRequest()),
                timeout=LIVEKIT_ADMIN_TIMEOUT_SECONDS,
            )
            return True
        except Exception as exc:
            logger.info("admin livekit ping failed: %s", type(exc).__name__)
            return False
        finally:
            await client.aclose()

    async def participant_media(self, room_id: str) -> Optional[Dict[str, Dict[str, Any]]]:
        """identity -> media state, or None when LiveKit cannot be reached."""
        from livekit import api
        from livekit.protocol import models

        client = self._client()
        try:
            response = await asyncio.wait_for(
                client.room.list_participants(api.ListParticipantsRequest(room=room_id)),
                timeout=LIVEKIT_ADMIN_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.info("admin livekit participant lookup failed room_id=%s: %s", room_id, type(exc).__name__)
            return None
        finally:
            await client.aclose()

        result: Dict[str, Dict[str, Any]] = {}
        for participant in response.participants:
            tracks = [
                {
                    "source": models.TrackSource.Name(track.source),
                    "muted": bool(track.muted),
                }
                for track in participant.tracks
            ]
            result[participant.identity] = {
                "connection": models.ParticipantInfo.State.Name(participant.state).lower(),
                "microphone": _track_state(tracks, "MICROPHONE"),
                "camera": _track_state(tracks, "CAMERA"),
                "screen_share": "on" if any(track["source"] == "SCREEN_SHARE" for track in tracks) else "off",
                "joined_at_ms": int(participant.joined_at_ms or 0) or None,
            }
        return result
