from __future__ import annotations

import asyncio
import logging
import queue
import threading
from concurrent.futures import Future
from typing import Iterator, Optional

import livekit.rtc as rtc

from src.common.audio import AudioInput, AudioMetadata

logger = logging.getLogger(__name__)


_CHUNK_MS = 20
_BYTES_PER_SAMPLE = 2


class LiveKitAudioInput(AudioInput):
    """
    Adapts a LiveKit rtc.AudioStream to the src.common.audio.AudioInput contract.
    The realtime engine expects a blocking `stream_frames()` iterator.
    We run an async task to pull frames from the LiveKit stream and push them to a thread-safe queue.
    """

    def __init__(
        self,
        participant_id: str,
        audio_stream: rtc.AudioStream,
        sample_rate: int = 16000,
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        channels: int = 1,
        chunk_ms: int = _CHUNK_MS,
        queue_maxsize: int = 300,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if channels <= 0:
            raise ValueError("channels must be positive")
        if chunk_ms <= 0:
            raise ValueError("chunk_ms must be positive")
        if queue_maxsize <= 0:
            raise ValueError("queue_maxsize must be positive")

        self.participant_id = participant_id
        self.audio_stream = audio_stream
        self._sample_rate = sample_rate
        self._channels = channels
        self._chunk_bytes = int(sample_rate * chunk_ms / 1000) * channels * _BYTES_PER_SAMPLE
        self._queue_capacity = queue_maxsize
        # Keep one extra slot so stop sentinel can always be enqueued.
        self._q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=queue_maxsize + 1)
        self._loop = loop
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = None
        self._pump_future: Optional[Future[None]] = None
        self._buffer = bytearray()
        self._state_lock = threading.Lock()
        self._running = False
        self._sentinel_sent = False
        self._stream_close_requested = False

    @property
    def metadata(self) -> AudioMetadata:
        return AudioMetadata(
            sample_rate=self._sample_rate,
            channels=self._channels,
            speaker_id=self.participant_id,
        )

    def start(self) -> None:
        with self._state_lock:
            if self._running:
                return
            if self._loop is None:
                try:
                    self._loop = asyncio.get_running_loop()
                except RuntimeError as exc:
                    raise RuntimeError(
                        "LiveKitAudioInput requires a running event loop to pump the AudioStream"
                    ) from exc
            if not self._loop.is_running():
                raise RuntimeError("LiveKitAudioInput loop is not running")

            self._running = True
            self._sentinel_sent = False
            self._pump_future = asyncio.run_coroutine_threadsafe(
                self._pump_stream(),
                self._loop,
            )

        logger.info(f"LiveKitAudioInput started for {self.participant_id}")

    def stop(self) -> None:
        with self._state_lock:
            future = self._pump_future
            self._pump_future = None
            was_running = self._running
            self._running = False

        if future is not None and not future.done():
            future.cancel()
        if was_running:
            self._request_stream_close()
        self._enqueue_sentinel()
        logger.info(f"LiveKitAudioInput stopped for {self.participant_id}")

    async def _pump_stream(self) -> None:
        try:
            async for frame_event in self.audio_stream:
                if not self._running:
                    break

                frame = getattr(frame_event, "frame", frame_event)
                self._buffer.extend(self._frame_to_bytes(frame))
                self._drain_buffer()
        except asyncio.CancelledError:
            logger.debug("Audio pump cancelled for %s", self.participant_id)
        except Exception:
            logger.exception("Error pumping audio stream for %s", self.participant_id)
        finally:
            with self._state_lock:
                self._running = False
                self._pump_future = None
            self._request_stream_close()
            self._enqueue_sentinel()

    def stream_frames(self) -> Iterator[bytes]:
        while True:
            try:
                chunk = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            if chunk is None:
                break
            yield chunk

    def _frame_to_bytes(self, frame: object) -> bytes:
        raw_data = getattr(frame, "data")
        if isinstance(raw_data, memoryview):
            return raw_data.cast("B").tobytes()
        return bytes(raw_data)

    def _drain_buffer(self) -> None:
        while len(self._buffer) >= self._chunk_bytes:
            chunk = bytes(self._buffer[: self._chunk_bytes])
            del self._buffer[: self._chunk_bytes]
            self._enqueue_chunk(chunk)

    def _enqueue_chunk(self, chunk: bytes) -> None:
        while self._q.qsize() >= self._queue_capacity:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
            logger.warning("Audio buffer full for %s, dropping oldest chunk", self.participant_id)
        self._q.put_nowait(chunk)

    def _enqueue_sentinel(self) -> None:
        with self._state_lock:
            if self._sentinel_sent:
                return
            self._sentinel_sent = True

        while True:
            try:
                self._q.put_nowait(None)
                return
            except queue.Full:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    return

    def _request_stream_close(self) -> None:
        with self._state_lock:
            if self._stream_close_requested:
                return
            self._stream_close_requested = True
            loop = self._loop

        aclose = getattr(self.audio_stream, "aclose", None)
        if loop is None or not loop.is_running() or not callable(aclose):
            return

        try:
            asyncio.run_coroutine_threadsafe(aclose(), loop)
        except RuntimeError:
            logger.debug("Unable to close audio stream for %s", self.participant_id)
