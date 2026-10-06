"""Provider-level moderation through the LiveKit server API.

Muting is enforced by LiveKit (the target's published microphone track is muted on the
SFU), not just by an icon in the UI. LiveKit lets the publisher unmute again, which is
the intended policy: hosts can mute anyone below them, nobody can force a mic *on*.
Removing disconnects the target's media session from the LiveKit room.

Both calls are best effort with a short timeout: the gateway also tells the target's
client to mute / leave, so a slow SFU never blocks the action.
"""
from __future__ import annotations

import asyncio
import logging

from server.config import Settings
from server.service.admin.livekit_inspector import livekit_http_url

logger = logging.getLogger(__name__)

LIVEKIT_MODERATION_TIMEOUT_SECONDS = 3.0


class LiveKitModerator:
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
            timeout=aiohttp.ClientTimeout(total=LIVEKIT_MODERATION_TIMEOUT_SECONDS),
        )

    async def mute_microphone(self, room_id: str, identity: str) -> bool:
        """Mute every microphone track the identity publishes. True when LiveKit confirmed."""
        from livekit import api
        from livekit.protocol import models

        client = self._client()
        try:
            participant = await asyncio.wait_for(
                client.room.get_participant(api.RoomParticipantIdentity(room=room_id, identity=identity)),
                timeout=LIVEKIT_MODERATION_TIMEOUT_SECONDS,
            )
            for track in participant.tracks:
                if track.source != models.TrackSource.MICROPHONE or track.muted:
                    continue
                await asyncio.wait_for(
                    client.room.mute_published_track(
                        api.MuteRoomTrackRequest(room=room_id, identity=identity, track_sid=track.sid, muted=True)
                    ),
                    timeout=LIVEKIT_MODERATION_TIMEOUT_SECONDS,
                )
            # Every microphone track is muted on the SFU now (or there was none live).
            return True
        except Exception as exc:
            logger.warning("livekit mute failed room_id=%s identity=%s: %s", room_id, identity, type(exc).__name__)
            return False
        finally:
            await client.aclose()

    async def remove_participant(self, room_id: str, identity: str) -> bool:
        from livekit import api

        client = self._client()
        try:
            await asyncio.wait_for(
                client.room.remove_participant(api.RoomParticipantIdentity(room=room_id, identity=identity)),
                timeout=LIVEKIT_MODERATION_TIMEOUT_SECONDS,
            )
            return True
        except Exception as exc:
            # Already gone from LiveKit (e.g. media never connected) is fine: the room
            # token is revoked by removing the participant from room state.
            logger.info("livekit remove failed room_id=%s identity=%s: %s", room_id, identity, type(exc).__name__)
            return False
        finally:
            await client.aclose()
