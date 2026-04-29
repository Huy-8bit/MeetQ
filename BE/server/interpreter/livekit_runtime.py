import asyncio
import logging
from typing import Callable, Optional, Dict
import livekit.rtc as rtc
from server.config import Settings
from server.gateway.livekit_tokens import generate_livekit_token

logger = logging.getLogger(__name__)

class LiveKitRuntime:
    def __init__(self, room_id: str, settings: Settings, on_media_connected: Callable[[str], None], on_media_disconnected: Callable[[str], None], on_audio_stream: Callable[[str, rtc.AudioStream], None]):
        self.room_id = room_id
        self.settings = settings
        self.room = rtc.Room()
        self.on_media_connected = on_media_connected
        self.on_media_disconnected = on_media_disconnected
        self.on_audio_stream = on_audio_stream
        self._streams: Dict[str, rtc.AudioStream] = {}

        self.room.on("track_subscribed", self._on_track_subscribed)
        self.room.on("track_unsubscribed", self._on_track_unsubscribed)
        self.room.on("participant_disconnected", self._on_participant_disconnected)

    async def connect(self):
        token = generate_livekit_token(
            room_name=self.room_id,
            participant_id=f"interp::{self.room_id}",
            participant_name="Interpreter",
            language="auto",
            api_key=self.settings.livekit_api_key,
            api_secret=self.settings.livekit_api_secret,
            kind="interpreter",
        )
        
        await self.room.connect(self.settings.livekit_ws_url_internal, token)
        logger.info(f"Interpreter connected to LiveKit room {self.room_id}")

    async def disconnect(self):
        await self.room.disconnect()
        logger.info(f"Interpreter disconnected from LiveKit room {self.room_id}")

    def _on_track_subscribed(self, track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
        if track.kind == rtc.TrackKind.KIND_AUDIO and not participant.identity.startswith("interp::"):
            logger.info(f"Subscribed to mic track of {participant.identity}")
            audio_stream = rtc.AudioStream.from_track(
                track=track,
                loop=asyncio.get_running_loop(),
                sample_rate=getattr(self.settings, "realtime_input_sample_rate", 16000),
                num_channels=1,
                frame_size_ms=20,
            )
            self._streams[participant.identity] = audio_stream
            self.on_audio_stream(participant.identity, audio_stream)
            self.on_media_connected(participant.identity)

    def _on_track_unsubscribed(self, track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
        if track.kind == rtc.TrackKind.KIND_AUDIO and not participant.identity.startswith("interp::"):
            logger.info(f"Unsubscribed from mic track of {participant.identity}")
            if participant.identity in self._streams:
                del self._streams[participant.identity]
            self.on_media_disconnected(participant.identity)

    def _on_participant_disconnected(self, participant: rtc.RemoteParticipant):
        if not participant.identity.startswith("interp::"):
            if participant.identity in self._streams:
                del self._streams[participant.identity]
            self.on_media_disconnected(participant.identity)
