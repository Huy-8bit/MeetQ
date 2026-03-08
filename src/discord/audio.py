"""
src/discord/audio.py
Audio routing components for Discord voice-channel interpreter bot.

Uses ``discord-ext-voice-recv`` for receiving voice audio.
All dependencies are pure-Python wheels — only ``libopus`` is required as
a system library (PyNaCl wheel bundles libsodium; no FFmpeg needed).

DiscordAudioInput
    Implements the common AudioInput interface.
    Receives PCM audio from Discord voice receive (via voice_recv AudioSink)
    and delivers 20 ms PCM16 mono 16 kHz chunks to the interpreter pipeline.

DiscordAudioOutput
    Sends translated TTS PCM16 audio back into the Discord voice channel
    via a discord.py AudioSource.
    Interface mirrors SpeakerPlayer (push / flush / stop / restart) so it
    can be used as a drop-in replacement in RealtimeClient.
"""
from __future__ import annotations

import queue
import threading
from typing import Iterator, Optional

import numpy as np

try:
    import discord
    from discord.ext.voice_recv import AudioSink as VoiceRecvAudioSink
    from discord.ext.voice_recv import VoiceData, VoiceRecvClient
except ImportError:
    raise ImportError(
        "discord.py[voice] and discord-ext-voice-recv are required.\n"
        "  pip install 'discord.py[voice]' discord-ext-voice-recv"
    )

from src.common.audio import (
    AudioInput,
    AudioMetadata,
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    CHUNK_MS,
)
from src.common.logging_utils import get_logger

logger = get_logger("discord.audio")

# Discord voice uses 48 kHz stereo PCM16 by default (Opus decoded).
DISCORD_SAMPLE_RATE = 48000
DISCORD_CHANNELS = 2
DISCORD_FRAME_MS = 20  # 20 ms Opus frames
TARGET_SAMPLE_RATE = DEFAULT_SAMPLE_RATE  # 16 kHz mono for the interpreter


# ---------------------------------------------------------------------------
# Helper: resample + stereo-to-mono
# ---------------------------------------------------------------------------

def _resample_to_16k_mono(pcm16_bytes: bytes, src_rate: int, src_channels: int) -> bytes:
    """
    Down-mix to mono and resample to 16 kHz PCM16.
    Uses simple linear decimation — good enough for speech.
    """
    samples = np.frombuffer(pcm16_bytes, dtype=np.int16)
    if len(samples) == 0:
        return b""

    # stereo -> mono
    if src_channels == 2 and len(samples) % 2 == 0:
        samples = samples.reshape(-1, 2).mean(axis=1).astype(np.int16)

    # resample (nearest-neighbor decimation — fast, fine for voice)
    if src_rate != TARGET_SAMPLE_RATE:
        ratio = TARGET_SAMPLE_RATE / src_rate
        length = int(len(samples) * ratio)
        indices = (np.arange(length) / ratio).astype(int)
        indices = np.clip(indices, 0, len(samples) - 1)
        samples = samples[indices]

    return samples.tobytes()


# ---------------------------------------------------------------------------
# DiscordAudioSink  — discord-ext-voice-recv AudioSink
# ---------------------------------------------------------------------------

class DiscordAudioSink(VoiceRecvAudioSink):
    """
    Custom AudioSink (from discord-ext-voice-recv) that receives decoded
    PCM from all users in a voice channel and forwards it to a
    DiscordAudioInput queue.

    voice_recv delivers per-user packets; we down-mix into a single mono
    16 kHz stream for the interpreter.
    """

    def __init__(self, audio_input: "DiscordAudioInput") -> None:
        super().__init__()
        self._audio_input = audio_input

    def wants_opus(self) -> bool:
        """We want decoded PCM, not raw Opus."""
        return False

    def write(self, user, data: VoiceData) -> None:
        """Called by voice_recv for every decoded voice packet."""
        pcm = data.pcm  # raw PCM16 bytes (48 kHz stereo)
        if not pcm:
            return
        mono_16k = _resample_to_16k_mono(pcm, DISCORD_SAMPLE_RATE, DISCORD_CHANNELS)
        self._audio_input._enqueue(mono_16k)

    def cleanup(self) -> None:
        """Called when the voice client stops listening.
        Don't signal stop here — let the bot control lifecycle explicitly."""
        logger.warning("[DiscordAudioSink] cleanup() called")


# ---------------------------------------------------------------------------
# DiscordAudioInput — implements common.audio.AudioInput
# ---------------------------------------------------------------------------

class DiscordAudioInput(AudioInput):
    """
    Receives Discord voice audio and presents it via the standard AudioInput
    interface consumed by RealtimeClient.

    Lifecycle:
        1. Instantiate.
        2. Attach to voice client:
           vc.listen(DiscordAudioSink(this_input))
        3. start() — signals readiness.
        4. stream_frames() — yields 20 ms PCM16 mono 16 kHz chunks.
        5. stop() — breaks the generator.
    """

    def __init__(self, sample_rate: int = TARGET_SAMPLE_RATE, chunk_ms: int = CHUNK_MS) -> None:
        self._sample_rate = sample_rate
        self._chunk_ms = chunk_ms
        self._chunk_bytes = int(sample_rate * chunk_ms / 1000) * 2  # PCM16 = 2 bytes/sample
        self._q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=600)
        self._stop_event = threading.Event()
        self._buffer = bytearray()

    @property
    def metadata(self) -> AudioMetadata:
        return AudioMetadata(sample_rate=self._sample_rate, channels=DEFAULT_CHANNELS)

    # Called by DiscordAudioSink.write()
    def _enqueue(self, pcm_bytes: bytes) -> None:
        """Accumulate incoming audio and push complete chunks."""
        if self._stop_event.is_set():
            return
        self._buffer.extend(pcm_bytes)
        while len(self._buffer) >= self._chunk_bytes:
            chunk = bytes(self._buffer[: self._chunk_bytes])
            self._buffer = self._buffer[self._chunk_bytes :]
            try:
                self._q.put_nowait(chunk)
            except queue.Full:
                pass  # drop oldest implicitly

    def _signal_stop(self) -> None:
        self._stop_event.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def start(self) -> None:
        self._stop_event.clear()
        self._buffer.clear()
        # Drain any leftover None sentinels from previous session
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        logger.info("[DiscordAudioInput] Started (16 kHz mono PCM16)")

    def stop(self) -> None:
        self._signal_stop()
        logger.info("[DiscordAudioInput] Stopped")

    def stream_frames(self) -> Iterator[bytes]:
        logger.debug("[DiscordAudioInput] stream_frames() started")
        frame_count = 0
        while not self._stop_event.is_set():
            try:
                chunk = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            if chunk is None:
                logger.debug(f"[DiscordAudioInput] stream_frames() got None sentinel after {frame_count} frames")
                break
            frame_count += 1
            yield chunk
        logger.debug(f"[DiscordAudioInput] stream_frames() exiting (stop_event={self._stop_event.is_set()}, frames={frame_count})")


# ---------------------------------------------------------------------------
# DiscordAudioOutput — plays TTS into voice channel
# ---------------------------------------------------------------------------

class DiscordPCMSource(discord.AudioSource):
    """
    discord.py AudioSource that reads from an internal queue.
    Produces 20 ms frames of 48 kHz stereo PCM16 for Opus encoding.
    """

    FRAME_SIZE = int(DISCORD_SAMPLE_RATE * DISCORD_FRAME_MS / 1000) * DISCORD_CHANNELS  # samples
    FRAME_BYTES = FRAME_SIZE * 2  # PCM16 = 2 bytes/sample
    SILENCE = b"\x00" * FRAME_BYTES

    def __init__(self) -> None:
        self._q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=500)
        self._active = threading.Event()
        self._active.set()
        self._leftover = b""

    def read(self) -> bytes:
        """Return one 20 ms frame. Called by discord.py voice send loop."""
        if not self._active.is_set():
            return self.SILENCE

        # Build up a full frame from queued data
        needed = self.FRAME_BYTES - len(self._leftover)
        data = bytearray(self._leftover)

        while needed > 0:
            try:
                chunk = self._q.get_nowait()
            except queue.Empty:
                break
            if chunk is None:
                self._active.clear()
                break
            data.extend(chunk)
            needed = self.FRAME_BYTES - len(data)

        self._leftover = b""

        if len(data) >= self.FRAME_BYTES:
            frame = bytes(data[: self.FRAME_BYTES])
            self._leftover = bytes(data[self.FRAME_BYTES :])
            return frame
        elif len(data) > 0:
            # pad with silence
            frame = bytes(data) + b"\x00" * (self.FRAME_BYTES - len(data))
            return frame
        else:
            return self.SILENCE

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        self._active.clear()

    def enqueue(self, pcm_bytes: bytes) -> None:
        if not self._active.is_set():
            return
        try:
            self._q.put_nowait(pcm_bytes)
        except queue.Full:
            pass

    def clear(self) -> None:
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break


def _upsample_to_48k_stereo(pcm16_mono_bytes: bytes, src_rate: int) -> bytes:
    """
    Up-sample mono PCM16 from src_rate to 48 kHz stereo PCM16.
    """
    samples = np.frombuffer(pcm16_mono_bytes, dtype=np.int16)
    if len(samples) == 0:
        return b""

    # upsample
    if src_rate != DISCORD_SAMPLE_RATE:
        ratio = DISCORD_SAMPLE_RATE / src_rate
        length = int(len(samples) * ratio)
        indices = (np.arange(length) / ratio).astype(int)
        indices = np.clip(indices, 0, len(samples) - 1)
        samples = samples[indices]

    # mono -> stereo
    stereo = np.column_stack([samples, samples]).flatten().astype(np.int16)
    return stereo.tobytes()


class DiscordAudioOutput:
    """
    Plays translated TTS audio into a Discord voice channel.

    Interface mirrors SpeakerPlayer / MeetAudioMicOutput so it can be used
    as a drop-in replacement for RealtimeClient._player.

    The RealtimeClient sends 24 kHz mono PCM16 chunks (from response.audio.delta).
    This class up-samples to 48 kHz stereo and enqueues for Discord voice send.

    Usage:
        out = DiscordAudioOutput(voice_client)
        out.start()
        out.push(pcm_bytes)   # 24 kHz mono PCM16 from OpenAI
        out.flush()
        out.stop()
        out.restart()
    """

    INPUT_RATE = 24000  # OpenAI Realtime TTS output rate

    def __init__(self, voice_client) -> None:
        self._vc = voice_client
        self._source: Optional[DiscordPCMSource] = None

    def start(self) -> None:
        if self._source is not None:
            return
        self._source = DiscordPCMSource()
        # Don't call play() here — lazy-start it in push() so the AudioPlayer
        # thread doesn't interact with the listener until we actually have TTS data.
        logger.info("[DiscordAudioOutput] Prepared (will lazy-start player on first push)")

    def _ensure_playing(self) -> None:
        """Start the AudioPlayer if not already running."""
        if self._vc.is_playing():
            return
        if self._source is None:
            return
        try:
            self._vc.play(self._source, after=lambda e: logger.debug("[DiscordAudioOutput] player finished, error=%s", e))
            logger.info("[DiscordAudioOutput] Player started (48 kHz stereo)")
        except Exception as exc:
            logger.warning("[DiscordAudioOutput] Failed to start player: %s", exc)

    def push(self, pcm_bytes: bytes) -> None:
        """Accept 24 kHz mono PCM16, upsample to 48 kHz stereo, enqueue."""
        if self._source is None:
            return
        stereo_48k = _upsample_to_48k_stereo(pcm_bytes, self.INPUT_RATE)
        self._source.enqueue(stereo_48k)
        self._ensure_playing()

    def flush(self) -> None:
        """Insert 50 ms silence pad so the last syllable is not clipped."""
        if self._source is None:
            return
        frames = int(DISCORD_SAMPLE_RATE * 0.05) * DISCORD_CHANNELS
        silence = b"\x00" * (frames * 2)
        self._source.enqueue(silence)

    def stop(self) -> None:
        if self._source is not None:
            self._source.clear()
            self._source._active.clear()
        if self._vc.is_playing():
            # IMPORTANT: use stop_playing() not stop() to avoid killing the listener
            if hasattr(self._vc, 'stop_playing'):
                self._vc.stop_playing()
            else:
                self._vc.stop()
        self._source = None
        logger.info("[DiscordAudioOutput] Stopped")

    def restart(self) -> None:
        self.stop()
        self.start()
