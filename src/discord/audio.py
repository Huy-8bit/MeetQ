"""
src/discord/audio.py
Discord audio input adapter that implements the AudioInput contract.

This adapter receives audio from Discord voice channels via discord-ext-voice-recv,
converts it from 48kHz stereo to 16kHz mono PCM16, and feeds it to RealtimeClient
in 20ms chunks.
"""
from __future__ import annotations

import asyncio
import queue
import threading
from typing import Iterator, Optional

import numpy as np

from src.common.audio import AudioInput, AudioMetadata

# Discord constants
DISCORD_SAMPLE_RATE = 48000  # Discord uses 48kHz
DISCORD_CHANNELS = 2          # Discord uses stereo
TARGET_SAMPLE_RATE = 16000    # Realtime API expects 16kHz
TARGET_CHANNELS = 1           # Realtime API expects mono
CHUNK_MS = 20                 # 20ms chunks
CHUNK_FRAMES = int(TARGET_SAMPLE_RATE * CHUNK_MS / 1000)  # 320 frames at 16kHz


class DiscordAudioInput(AudioInput):
    """
    Discord voice channel audio input adapter.
    
    Receives PCM audio from Discord voice recv sink, converts from 48kHz stereo
    to 16kHz mono, and yields 20ms chunks for RealtimeClient consumption.
    
    Usage:
        audio_input = DiscordAudioInput()
        audio_input.start()
        
        # In Discord voice receive callback:
        audio_input.feed_audio(pcm_data, sample_rate=48000, channels=2)
        
        # RealtimeClient consumes:
        for chunk in audio_input.stream_frames():
            # chunk is 16kHz mono PCM16 bytes
            ...
        
        audio_input.stop()
    """

    def __init__(self) -> None:
        """Initialize the Discord audio input adapter."""
        self._sample_rate = TARGET_SAMPLE_RATE
        self._channels = TARGET_CHANNELS
        self._chunk_frames = CHUNK_FRAMES
        
        # Queue for converted audio chunks ready for streaming
        self._q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=500)
        
        # Buffer for accumulating resampled audio to align on 20ms boundaries
        self._buffer: bytearray = bytearray()
        self._chunk_size_bytes = CHUNK_FRAMES * 2  # 2 bytes per sample (PCM16)
        
        self._stop_event = threading.Event()
        self._started = False

    @property
    def metadata(self) -> AudioMetadata:
        """Return audio metadata for this input source."""
        return AudioMetadata(
            sample_rate=self._sample_rate,
            channels=self._channels,
            speaker_id=None,  # Mixed audio from multiple Discord users
        )

    def start(self) -> None:
        """Start accepting audio input."""
        self._stop_event.clear()
        self._started = True

    def stop(self) -> None:
        """Stop accepting audio and signal end of stream."""
        self._stop_event.set()
        self._started = False
        
        # Signal end of stream
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def stream_frames(self) -> Iterator[bytes]:
        """
        Yield PCM16 byte chunks (16kHz mono, 20ms each) until stopped.
        
        Blocks on queue.get() with timeout to allow clean shutdown.
        """
        while not self._stop_event.is_set():
            try:
                chunk = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            
            if chunk is None:
                break
            
            yield chunk

    def feed_audio(
        self,
        pcm_data: bytes,
        sample_rate: int = DISCORD_SAMPLE_RATE,
        channels: int = DISCORD_CHANNELS,
    ) -> None:
        """
        Feed raw PCM audio from Discord voice recv.
        
        This method converts the audio from Discord's format (48kHz stereo)
        to the format expected by RealtimeClient (16kHz mono), then chunks
        it into 20ms segments.
        
        Args:
            pcm_data: Raw PCM16 audio bytes from Discord
            sample_rate: Source sample rate (default: 48000)
            channels: Source channel count (default: 2 for stereo)
        """
        if not self._started or self._stop_event.is_set():
            return
        
        try:
            # Convert bytes to numpy array
            audio = np.frombuffer(pcm_data, dtype=np.int16)
            
            # Convert stereo to mono if needed
            if channels == 2:
                # Reshape to (frames, 2) and average the channels
                audio = audio.reshape(-1, 2)
                audio = audio.mean(axis=1).astype(np.int16)
            
            # Resample from 48kHz to 16kHz if needed
            if sample_rate != TARGET_SAMPLE_RATE:
                audio = self._resample(audio, sample_rate, TARGET_SAMPLE_RATE)
            
            # Convert back to bytes and add to buffer
            resampled_bytes = audio.tobytes()
            self._buffer.extend(resampled_bytes)
            
            # Extract complete 20ms chunks from buffer
            while len(self._buffer) >= self._chunk_size_bytes:
                chunk = bytes(self._buffer[:self._chunk_size_bytes])
                del self._buffer[:self._chunk_size_bytes]
                
                # Put chunk in queue for stream_frames()
                try:
                    self._q.put_nowait(chunk)
                except queue.Full:
                    # Drop oldest chunk if queue is full to avoid blocking
                    try:
                        self._q.get_nowait()
                        self._q.put_nowait(chunk)
                    except (queue.Empty, queue.Full):
                        pass
        
        except Exception as e:
            # Log error but don't crash on bad audio packets
            import sys
            print(f"[DiscordAudioInput] Error processing audio: {e}", file=sys.stderr)

    @staticmethod
    def _resample(audio: np.ndarray, src_rate: int, tgt_rate: int) -> np.ndarray:
        """
        Simple linear resampling from src_rate to tgt_rate.
        
        For production use, consider using scipy.signal.resample for better quality,
        but this simple approach works well for voice and avoids additional dependencies.
        """
        if src_rate == tgt_rate:
            return audio
        
        # Calculate new length
        duration = len(audio) / src_rate
        new_length = int(duration * tgt_rate)
        
        # Linear interpolation
        x_old = np.linspace(0, len(audio) - 1, len(audio))
        x_new = np.linspace(0, len(audio) - 1, new_length)
        resampled = np.interp(x_new, x_old, audio).astype(np.int16)
        
        return resampled
