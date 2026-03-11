"""
src/common/audio.py
Microphone capture and speaker playback using sounddevice.

AudioInput  — abstract base class for all audio input sources.
MicInput    — local microphone input (implements AudioInput).
DeviceLoopbackInput — captures from any sounddevice input device (e.g.
              BlackHole / Loopback / VB-Cable / Stereo Mix).
MicCapture  — legacy thin wrapper kept for compatibility.
SpeakerPlayer — streams PCM16 chunks to speaker in real time.
"""
from __future__ import annotations

import abc
import queue
import threading
from dataclasses import dataclass, field
from typing import Generator, Iterator, Optional

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
# AudioInput abstraction
# ---------------------------------------------------------------------------

@dataclass
class AudioMetadata:
    """Metadata that any AudioInput implementation must expose."""
    sample_rate: int
    channels: int
    speaker_id: Optional[str] = field(default=None)


class AudioInput(abc.ABC):
    """
    Common contract for all audio input sources consumed by RealtimeClient.

    Implementations: MicInput (local mic), DeviceLoopbackInput (any sounddevice
    input device, e.g. BlackHole/Loopback virtual devices for meeting capture).

    Usage:
        inp = MicInput(device=0, sample_rate=16000)
        inp.start()
        for chunk in inp.stream_frames():
            # chunk is PCM16 bytes (~20ms worth)
            ...
        inp.stop()
    """

    @property
    @abc.abstractmethod
    def metadata(self) -> AudioMetadata:
        ...

    @abc.abstractmethod
    def start(self) -> None:
        """Open the audio input and begin buffering frames."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Stop buffering and release the audio input."""

    @abc.abstractmethod
    def stream_frames(self) -> Iterator[bytes]:
        """Yield PCM16 byte chunks until stop() is called."""


# ---------------------------------------------------------------------------
# MicInput — local microphone, implements AudioInput
# ---------------------------------------------------------------------------

class MicInput(AudioInput):
    """
    Local microphone input that satisfies the AudioInput contract.

    Internally uses sounddevice.InputStream with a thread-safe queue so
    stream_frames() can be iterated from the audio thread.
    """

    def __init__(
        self,
        device: Optional[int] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        chunk_ms: int = CHUNK_MS,
    ) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._chunk_frames = int(sample_rate * chunk_ms / 1000)
        self._q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=200)
        self._stream: Optional[sd.InputStream] = None
        self._stop_event = threading.Event()

    @property
    def metadata(self) -> AudioMetadata:
        return AudioMetadata(sample_rate=self._sample_rate, channels=DEFAULT_CHANNELS)

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            import sys
            print(f"[audio] sounddevice status: {status}", file=sys.stderr)
        pcm = indata.copy() if indata.dtype == np.int16 else (indata * 32767).astype(np.int16)
        try:
            self._q.put_nowait(pcm.tobytes())
        except queue.Full:
            pass

    def start(self) -> None:
        self._stop_event.clear()
        self._stream = sd.InputStream(
            device=self._device,
            samplerate=self._sample_rate,
            channels=DEFAULT_CHANNELS,
            dtype=DTYPE,
            blocksize=self._chunk_frames,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def stream_frames(self) -> Iterator[bytes]:
        while not self._stop_event.is_set():
            try:
                chunk = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            if chunk is None:
                break
            yield chunk


# ---------------------------------------------------------------------------
# DeviceLoopbackInput — any sounddevice input device, implements AudioInput
# ---------------------------------------------------------------------------

class DeviceLoopbackInput(AudioInput):
    """
    Captures audio from any sounddevice input device by index.

    Route audio to a virtual audio device (BlackHole, Loopback,
    VB-Cable, Stereo Mix, etc.) then point --input-device at it.

    Usage:
        # List devices: python app.py --list-input-devices
        # Pick the virtual device index shown, e.g. 4 for BlackHole 2ch
        inp = DeviceLoopbackInput(device=4, sample_rate=16000)
        inp.start()
        for chunk in inp.stream_frames():
            process(chunk)
        inp.stop()

    NOTE: Production use requires participant consent and legal review.
    """

    def __init__(
        self,
        device: int,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        chunk_ms: int = CHUNK_MS,
    ) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._chunk_frames = int(sample_rate * chunk_ms / 1000)
        self._q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=200)
        self._stream: Optional[sd.InputStream] = None
        self._stop_event = threading.Event()

    @property
    def metadata(self) -> AudioMetadata:
        return AudioMetadata(sample_rate=self._sample_rate, channels=DEFAULT_CHANNELS)

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            import sys
            print(f"[loopback] sounddevice status: {status}", file=sys.stderr)
        if indata.shape[1] > 1:
            # Mix down to mono
            mono = indata.mean(axis=1, keepdims=True)
        else:
            mono = indata
        pcm = mono.copy() if mono.dtype == np.int16 else (mono * 32767).astype(np.int16)
        try:
            self._q.put_nowait(pcm.tobytes())
        except queue.Full:
            pass

    def start(self) -> None:
        self._stop_event.clear()
        dev_info = sd.query_devices(self._device)
        channels = min(int(dev_info["max_input_channels"]), 2)  # up to stereo, then mix to mono
        self._stream = sd.InputStream(
            device=self._device,
            samplerate=self._sample_rate,
            channels=channels,
            dtype=DTYPE,
            blocksize=self._chunk_frames,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def stream_frames(self) -> Iterator[bytes]:
        while not self._stop_event.is_set():
            try:
                chunk = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            if chunk is None:
                break
            yield chunk


# ---------------------------------------------------------------------------
# MicCapture (legacy — kept for compatibility; prefer MicInput for new code)
# ---------------------------------------------------------------------------

class MicCapture:
    """
    Legacy mic capture class — kept for backwards compatibility.
    New code should use MicInput (implements AudioInput contract).

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
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self._channels = 1          # resolved to device minimum in start()
        # Queue holds numpy int16 arrays; sentinel None = stop
        self._q: queue.Queue = queue.Queue(maxsize=500)
        self._stream: Optional[sd.OutputStream] = None
        self._thread: Optional[threading.Thread] = None
        self._active = threading.Event()

    def _to_device_channels(self, mono: np.ndarray) -> np.ndarray:
        """Upmix a flat mono int16 array to the device's channel count."""
        if self._channels <= 1:
            return mono
        return np.column_stack([mono] * self._channels)

    def start(self) -> None:
        """Open the output stream and start the playback thread."""
        if self._thread and self._thread.is_alive():
            return
        # Query the device's minimum supported output channel count.
        # Many speakers/headphones only accept stereo (2ch) and reject mono.
        if self.device is not None:
            dev_info = sd.query_devices(self.device)
            self._channels = max(1, int(dev_info["max_output_channels"]))
        else:
            # For the system default device, query it by kind
            dev_info = sd.query_devices(kind="output")
            self._channels = max(1, int(dev_info["max_output_channels"]))
        self._active.set()
        self._stream = sd.OutputStream(
            device=self.device,
            samplerate=self.sample_rate,
            channels=self._channels,
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
        arr = self._to_device_channels(arr)
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
        frames = int(self.sample_rate * 0.05)  # 50ms silence
        silence = self._to_device_channels(np.zeros(frames, dtype=np.int16))
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
