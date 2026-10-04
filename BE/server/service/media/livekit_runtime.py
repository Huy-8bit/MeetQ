import asyncio
import logging
from typing import AsyncIterable, Callable, Dict, Optional

import livekit.rtc as rtc

from server.config import Settings
from server.service.gateway.livekit_tokens import generate_livekit_token
from server.service.livekit_lines import LineIsolationConfig, SpeakerLineHub
from server.meeting_modes import (
    BRSE_PARTICIPANT_DISPLAY_NAME,
    BRSE_PARTICIPANT_ID,
    build_brse_livekit_identity,
)

logger = logging.getLogger(__name__)


class LiveKitRuntime:
    def __init__(
        self,
        room_id: str,
        settings: Settings,
        on_media_connected: Callable[[str], None],
        on_media_disconnected: Callable[[str], None],
        on_audio_stream: Callable[[str, AsyncIterable[rtc.AudioFrameEvent]], None],
        output_audio_enabled: bool = True,
    ):
        self.room_id = room_id
        self.settings = settings
        self.room = rtc.Room()
        self.output_audio_enabled = output_audio_enabled
        self.on_media_connected = on_media_connected
        self.on_media_disconnected = on_media_disconnected
        self.on_audio_stream = on_audio_stream
        self._streams: Dict[str, AsyncIterable[rtc.AudioFrameEvent]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.livekit_identity = build_brse_livekit_identity(room_id)
        line_config = LineIsolationConfig.from_settings(settings)
        self.lines: Optional[SpeakerLineHub] = (
            SpeakerLineHub(room_id, line_config) if line_config.enabled else None
        )

        self.room.on("track_subscribed", self._on_track_subscribed)
        self.room.on("track_published", self._on_track_published)
        self.room.on("track_unsubscribed", self._on_track_unsubscribed)
        self.room.on("participant_disconnected", self._on_participant_disconnected)

    async def connect(self):
        self._loop = asyncio.get_running_loop()
        token = generate_livekit_token(
            room_name=self.room_id,
            participant_id=BRSE_PARTICIPANT_ID,
            participant_name=BRSE_PARTICIPANT_DISPLAY_NAME,
            language="auto",
            api_key=self.settings.livekit_api_key,
            api_secret=self.settings.livekit_api_secret,
            kind="virtual_brse",
            livekit_identity=self.livekit_identity,
            # Always allowed: the relay mode can switch to Voice + Text mid-meeting, and
            # OutputRouter only publishes a track while voice relay is on.
            can_publish=True,
        )

        await self.room.connect(self.settings.livekit_ws_url_internal, token)
        self._sync_existing_audio_tracks()
        logger.info(
            "BRSE runtime connected to LiveKit room %s output_audio_enabled=%s",
            self.room_id,
            self.output_audio_enabled,
        )

    async def disconnect(self):
        if self.lines is not None:
            await self.lines.close_all()
        await self.room.disconnect()
        logger.info("BRSE runtime disconnected from LiveKit room %s", self.room_id)

    def _on_track_subscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        if not self._is_human_microphone_audio(participant, publication):
            return

        try:
            loop = self._loop
            if loop is None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
            if loop is None:
                logger.warning("No active loop available for BRSE audio stream of %s", participant.identity)
                return

            logger.info("Subscribed to human mic track of %s", participant.identity)
            audio_stream = rtc.AudioStream.from_track(
                track=track,
                loop=loop,
                sample_rate=getattr(self.settings, "realtime_input_sample_rate", 24000),
                num_channels=1,
                frame_size_ms=20,
            )
            stream: AsyncIterable[rtc.AudioFrameEvent] = audio_stream
            if self.lines is not None:
                stream = self.lines.open_line(participant.identity, audio_stream)
            self._streams[participant.identity] = stream
            self.on_audio_stream(participant.identity, stream)
            self.on_media_connected(participant.identity)
        except Exception:
            logger.exception("Failed to bind BRSE audio stream for %s", participant.identity)

    def _on_track_published(self, *args):
        if len(args) < 2:
            return
        publication = args[0]
        participant = args[1]
        if not isinstance(participant, rtc.RemoteParticipant):
            return
        if not self._is_human_microphone_audio(participant, publication):
            return

        setter = getattr(publication, "set_subscribed", None)
        if callable(setter):
            try:
                setter(True)
            except Exception:
                logger.exception("Failed to subscribe to human audio publication for %s", participant.identity)

    def _on_track_unsubscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        if self._is_human_microphone_audio(participant, publication):
            logger.info("Unsubscribed from human mic track of %s", participant.identity)
            self._streams.pop(participant.identity, None)
            self._close_line(participant.identity)
            self.on_media_disconnected(participant.identity)

    def _on_participant_disconnected(self, participant: rtc.RemoteParticipant):
        if not participant.identity.startswith("interp::"):
            self._streams.pop(participant.identity, None)
            self._close_line(participant.identity)
            self.on_media_disconnected(participant.identity)

    def _close_line(self, identity: str) -> None:
        if self.lines is None or self.lines.get(identity) is None:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.create_task(self.lines.close_line(identity))

    def _sync_existing_audio_tracks(self) -> None:
        participants = getattr(self.room, "remote_participants", {}) or {}
        for participant in participants.values():
            if participant.identity.startswith("interp::"):
                continue
            publications = getattr(participant, "track_publications", {}) or {}
            for publication in publications.values():
                if not self._is_human_microphone_audio(participant, publication):
                    continue
                setter = getattr(publication, "set_subscribed", None)
                if callable(setter):
                    try:
                        setter(True)
                    except Exception:
                        logger.exception("Failed to subscribe existing audio publication for %s", participant.identity)

    def _is_human_microphone_audio(
        self,
        participant: rtc.RemoteParticipant,
        publication: rtc.RemoteTrackPublication,
    ) -> bool:
        if participant.identity.startswith("interp::"):
            return False
        if getattr(publication, "kind", None) != rtc.TrackKind.KIND_AUDIO:
            return False

        # Only the microphone feeds BRSE. Screen-share audio (SOURCE_SCREENSHARE_AUDIO),
        # and anything with an unknown source, is never interpreted. `source` is the
        # protobuf enum value (an int), so compare values rather than names.
        source = getattr(publication, "source", None)
        if source != rtc.TrackSource.SOURCE_MICROPHONE:
            logger.debug(
                "Ignoring non-microphone audio publication for %s source=%s",
                participant.identity,
                source,
            )
            return False
        return True
