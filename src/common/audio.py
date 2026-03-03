"""
src/common/audio.py
Microphone capture and speaker playback using sounddevice.

MicCapture  — yields PCM16 chunks (~20ms) via a thread-safe queue.
SpeakerPlayer — streams PCM16 chunks to speaker in real time.
"""
from __future__ import annotations

import queue
import threading
from typing import Generator, Optional

import numpy as np
import sounddevice as sd


# Default capture parameters
DEFAULT_SAMPLE_RATE = 16000   # Hz  (16kHz — Realtime API accepts this)
DEFAULT_CHANNELS = 1           # mono
CHUNK_MS = 20                  # ms per chunk
DTYPE = "int16"                # 16-bit PCM


# ---------------------------------------------------------------------------
# Device listing
# ---------------------------------------------------------------------------

def list_input_devices() -> list[dict]:
    """Return a list of available input devices."""
    devices = sd.query_devices()
    result = []
    for idx, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            result.append({
                "index": idx,
                "name": dev["name"],
                "channels": dev["max_input_channels"],
                "default_samplerate": int(dev["default_samplerate"]),
            })
    return result


def list_output_devices() -> list[dict]:
    """Return a list of available output devices."""
    devices = sd.query_devices()
    result = []
    for idx, dev in enumerate(devices):
        if dev["max_output_channels"] > 0:
            result.append({
                "index": idx,
                "name": dev["name"],
                "channels": dev["max_output_channels"],
                "default_samplerate": int(dev["default_samplerate"]),
            })
    return result


def print_input_devices() -> None:
    """Print a formatted table of input devices to stdout."""
    devs = list_input_devices()
    if not devs:
        print("No input devices found.")
        return
    print(f"{'Idx':>4}  {'Name':<40}  {'Ch':>3}  {'DefaultHz':>10}")
    print("-" * 65)
    for d in devs:
        print(f"{d['index']:>4}  {d['name']:<40}  {d['channels']:>3}  {d['default_samplerate']:>10}")


def print_output_devices() -> None:
    """Print a formatted table of output devices to stdout."""
    devs = list_output_devices()
    if not devs:
        print("No output devices found.")
        return
    print(f"{'Idx':>4}  {'Name':<40}  {'Ch':>3}  {'DefaultHz':>10}")
    print("-" * 65)
    for d in devs:
        print(f"{d['index']:>4}  {d['name']:<40}  {d['channels']:>3}  {d['default_samplerate']:>10}")


# ---------------------------------------------------------------------------
# Mic capture
# ---------------------------------------------------------------------------

class MicCapture:
    """
    Captures microphone audio and exposes it as an iterable of PCM16 byte chunks.

    Usage:
        cap = MicCapture(device=0, sample_rate=16000)
        cap.start()
        for chunk in cap.iter_chunks():
            # chunk is bytes of PCM16 data (~20ms worth)
            ...
        cap.stop()
    """

    def __init__(
        self,
        device: Optional[int] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        chunk_ms: int = CHUNK_MS,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.chunk_frames = int(sample_rate * chunk_ms / 1000)
        self._q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=200)
        self._stream: Optional[sd.InputStream] = None
        self._stop_event = threading.Event()

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            import sys
            print(f"[audio] sounddevice status: {status}", file=sys.stderr)
        if indata.dtype != np.int16:
            pcm = (indata * 32767).astype(np.int16)
        else:
            pcm = indata.copy()
        try:
            self._q.put_nowait(pcm.tobytes())
        except queue.Full:
            pass  # drop frame rather than block

    def start(self) -> None:
        """Open the input stream."""
        self._stop_event.clear()
        self._stream = sd.InputStream(
            device=self.device,
            samplerate=self.sample_rate,
            channels=DEFAULT_CHANNELS,
            dtype=DTYPE,
            blocksize=self.chunk_frames,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        """Close the input stream and signal the generator to stop."""
        self._stop_event.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def iter_chunks(self) -> Generator[bytes, None, None]:
        """Generator that yields PCM16 byte chunks from the mic."""
        while not self._stop_event.is_set():
            try:
                chunk = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            if chunk is None:
                break
            yield chunk

    def __enter__(self) -> "MicCapture":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# Speaker playback
# ---------------------------------------------------------------------------

_PLAYBACK_QUEUE_SENTINEL = None  # signals drain+stop


class SpeakerPlayer:
    """
    Streams PCM16 audio chunks to the speaker in real time.

    Usage:
        player = SpeakerPlayer(device=None, sample_rate=24000)
        player.start()
        player.push(pcm_bytes)   # call for each audio.delta chunk
        player.flush()           # call on response.audio.done for clean tail
        player.stop()            # immediate stop (barge-in / shutdown)
    """

    def __init__(
        self,
        device: Optional[int] = None,
        sample_rate: int = 24000,   # Realtime API audio output is 24kHz PCM16
        channels: int = 1,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        # Queue holds numpy int16 arrays; sentinel None = stop
        self._q: queue.Queue = queue.Queue(maxsize=500)
        self._stream: Optional[sd.OutputStream] = None
        self._thread: Optional[threading.Thread] = None
        self._active = threading.Event()

    def start(self) -> None:
        """Open the output stream and start the playback thread."""
        if self._thread and self._thread.is_alive():
            return
        self._active.set()
        self._stream = sd.OutputStream(
            device=self.device,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=0,  # let sounddevice choose optimal block size
        )
        self._stream.start()
        self._thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._thread.start()

    def push(self, pcm_bytes: bytes) -> None:
        """Enqueue raw PCM16 bytes for playback. Non-blocking; drops if full."""
        if not self._active.is_set():
            return
        arr = np.frombuffer(pcm_bytes, dtype=np.int16)
        try:
            self._q.put_nowait(arr)
        except queue.Full:
            pass

    def flush(self) -> None:
        """
        Signal end of current response chunk stream.
        Inserts a small silence pad so the last syllable isn't cut off.
        Non-blocking — playback continues draining in the background.
        """
        silence = np.zeros(int(self.sample_rate * 0.05), dtype=np.int16)  # 50ms silence
        try:
            self._q.put_nowait(silence)
        except queue.Full:
            pass

    def stop(self) -> None:
        """
        Immediately stop playback and clear the queue (barge-in / shutdown).
        Safe to call from any thread.
        """
        self._active.clear()
        # Drain the queue
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        # Wake up the thread so it exits
        try:
            self._q.put_nowait(_PLAYBACK_QUEUE_SENTINEL)
        except queue.Full:
            pass
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def restart(self) -> None:
        """Stop then immediately start again (used after barge-in interrupt)."""
        self.stop()
        self.start()

    def _playback_loop(self) -> None:
        """Background thread: pulls chunks from queue and writes to stream."""
        while self._active.is_set():
            try:
                chunk = self._q.get(timeout=0.05)
            except queue.Empty:
                continue
            if chunk is _PLAYBACK_QUEUE_SENTINEL:
                break
            if self._stream is not None and self._active.is_set():
                try:
                    self._stream.write(chunk)
                except Exception:
                    break


# ---------------------------------------------------------------------------
# Blocking clip recorder (fallback mode)
# ---------------------------------------------------------------------------

def record_clip(
    seconds: float,
    device: Optional[int] = None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> bytes:
    """
    Record a fixed-length audio clip and return raw PCM16 bytes.
    Blocks for `seconds` seconds.
    """
    frames = int(sample_rate * seconds)
    recording = sd.rec(
        frames,
        samplerate=sample_rate,
        channels=DEFAULT_CHANNELS,
        dtype=DTYPE,
        device=device,
    )
    sd.wait()
    return recording.tobytes()
