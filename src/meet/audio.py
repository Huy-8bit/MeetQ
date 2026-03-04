"""
src/meet/audio.py
Audio routing components for Google Meet bot mode.

SCKAudioInput (recommended — no extra drivers needed)
    Captures system/app audio using macOS ScreenCaptureKit (built-in, macOS 13+).
    No virtual audio device (BlackHole, Loopback, etc.) required.
    Captures all system audio or optionally a specific app (e.g. Chrome).
    Requires: pyobjc-framework-ScreenCaptureKit, pyobjc-framework-CoreMedia.

MeetAudioListenerInput (legacy — requires virtual audio device)
    Captures meeting audio from a virtual loopback input device.
    Chrome plays meeting audio -> OS routes it to a virtual loopback device
    (e.g. BlackHole 2ch) -> this class reads it and feeds the interpreter.

MeetAudioMicOutput
    Plays TTS/translated audio into a virtual output device that is
    configured as Chrome's microphone input.
    Interpreter TTS -> this class -> virtual output device
    -> OS routes it to Chrome mic input -> participants hear translation.

Virtual audio device setup (macOS) — only needed for MeetAudioListenerInput:
    1. Install BlackHole 2ch (https://existential.audio/blackhole/)
       or Loopback (https://rogueamoeba.com/loopback/)
    2. In System Settings -> Sound:
       - Set Chrome's output to BlackHole 2ch  (or use Loopback route)
       - Set Chrome's input to a second virtual device for bot output
    3. Run: python app.py --list-audio-devices  to find indexes
    4. Use:
       --meet-speaker-device <blackhole_input_idx>  (capture from this)
       --meet-mic-device     <virt_output_idx>      (play TTS into this)

Both classes implement the standard AudioInput / playback interfaces so they
plug into RealtimeClient and the existing SpeakerPlayer pattern.
"""
from __future__ import annotations

import ctypes
import queue
import sys
import threading
from typing import Iterator, Optional

import numpy as np
import sounddevice as sd

from src.common.audio import (
    AudioInput,
    AudioMetadata,
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    DTYPE,
    CHUNK_MS,
)
from src.common.logging_utils import get_logger

logger = get_logger("meet.audio")


# ---------------------------------------------------------------------------
# MeetAudioListenerInput
# ---------------------------------------------------------------------------

class MeetAudioListenerInput(AudioInput):
    """
    Captures audio from a selected sounddevice INPUT device.

    Use this to read the meeting audio that Chrome is playing through a
    virtual loopback device (e.g. BlackHole 2ch input side).

    The captured frames are PCM16 mono at the requested sample_rate.
    If the device is stereo, frames are averaged to mono before yielding.

    Safety:
        - This device should only receive Chrome's SPEAKER output.
        - If sample_rate doesn't match the device's native rate, sounddevice
          will either resample or raise; use --meet-sample-rate to match the
          device's native rate (typically 44100 or 48000).
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
        self._q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=300)
        self._stream: Optional[sd.InputStream] = None
        self._stop_event = threading.Event()
        self._channels = DEFAULT_CHANNELS  # resolved in start()

    @property
    def metadata(self) -> AudioMetadata:
        return AudioMetadata(sample_rate=self._sample_rate, channels=DEFAULT_CHANNELS)

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            print(f"[meet-listener] sounddevice status: {status}", file=sys.stderr)
        if indata.shape[1] > 1:
            mono = indata.mean(axis=1, keepdims=True)
        else:
            mono = indata
        pcm = mono.copy() if mono.dtype == np.int16 else (mono * 32767).astype(np.int16)
        try:
            self._q.put_nowait(pcm.tobytes())
        except queue.Full:
            pass  # drop oldest implicitly (new frames are more relevant)

    def start(self) -> None:
        self._stop_event.clear()
        dev_info = sd.query_devices(self._device)
        self._channels = min(int(dev_info["max_input_channels"]), 2)
        logger.info(
            f"[MeetAudioListenerInput] Opening device={self._device} "
            f"({dev_info['name']!r}) channels={self._channels} rate={self._sample_rate}"
        )
        self._stream = sd.InputStream(
            device=self._device,
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype=DTYPE,
            blocksize=self._chunk_frames,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
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
# MeetAudioMicOutput
# ---------------------------------------------------------------------------

class MeetAudioMicOutput:
    """
    Plays translated TTS audio into a selected sounddevice OUTPUT device.

    Configure that output device as Chrome's microphone input (via your
    virtual audio router) so meeting participants hear the translated speech.

    Interface mirrors SpeakerPlayer so it can be used as a drop-in
    replacement in the RealtimeClient audio playback path.

    Typical setup:
        macOS: Loopback app creates a virtual device that connects
               MeetAudioMicOutput playback -> Chrome mic input.

    Usage:
        out = MeetAudioMicOutput(device=5, sample_rate=24000)
        out.start()
        out.push(pcm_bytes)   # raw PCM16 bytes from response.audio.delta
        out.flush()           # 50ms silence pad at end of response
        out.stop()            # immediate stop / barge-in
        out.restart()         # stop then start (barge-in)
    """

    def __init__(
        self,
        device: int,
        sample_rate: int = 24000,   # Realtime API TTS output is 24kHz PCM16
    ) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._channels = 1          # resolved to device minimum in start()
        self._q: queue.Queue = queue.Queue(maxsize=500)
        self._stream: Optional[sd.OutputStream] = None
        self._thread: Optional[threading.Thread] = None
        self._active = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        dev_info = sd.query_devices(self._device)
        # Use the device's minimum supported output channel count (at least 1).
        # Many headphones/speakers only support stereo (2ch) and reject mono.
        self._channels = max(1, int(dev_info["max_output_channels"]))
        logger.info(
            f"[MeetAudioMicOutput] Opening device={self._device} "
            f"({dev_info['name']!r}) channels={self._channels} rate={self._sample_rate}"
        )
        self._active.set()
        self._stream = sd.OutputStream(
            device=self._device,
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="int16",
            blocksize=0,
        )
        self._stream.start()
        self._thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._thread.start()

    def _to_device_channels(self, mono: np.ndarray) -> np.ndarray:
        """Upmix a flat mono int16 array to the device's channel count."""
        if self._channels <= 1:
            return mono
        # Duplicate mono to each channel: shape (frames, channels)
        return np.column_stack([mono] * self._channels)

    def push(self, pcm_bytes: bytes) -> None:
        if not self._active.is_set():
            return
        arr = np.frombuffer(pcm_bytes, dtype=np.int16)
        arr = self._to_device_channels(arr)
        try:
            self._q.put_nowait(arr)
        except queue.Full:
            pass

    def flush(self) -> None:
        """Insert 50ms silence so the last syllable isn't clipped."""
        frames = int(self._sample_rate * 0.05)
        silence = np.zeros(frames, dtype=np.int16)
        silence = self._to_device_channels(silence)
        try:
            self._q.put_nowait(silence)
        except queue.Full:
            pass

    def stop(self) -> None:
        self._active.clear()
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        try:
            self._q.put_nowait(None)
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
        self.stop()
        self.start()

    def _playback_loop(self) -> None:
        while self._active.is_set():
            try:
                chunk = self._q.get(timeout=0.05)
            except queue.Empty:
                continue
            if chunk is None:
                break
            if self._stream is not None and self._active.is_set():
                try:
                    self._stream.write(chunk)
                except Exception:
                    break


# ---------------------------------------------------------------------------
# SCKAudioInput — macOS ScreenCaptureKit audio capture (no drivers needed)
# ---------------------------------------------------------------------------

def _check_sck_available() -> bool:
    """Return True if ScreenCaptureKit pyobjc bindings are importable."""
    try:
        import ScreenCaptureKit  # noqa: F401
        import CoreMedia  # noqa: F401
        return True
    except ImportError:
        return False


# Module-level ObjC delegate class — created once on first use.
# Must be at module scope: pyobjc registers ObjC classes globally and
# defining them inside functions can silently skip callback registration.
_SCKDelegateClass = None

def _get_sck_delegate_class():
    """Lazily create and cache the ObjC delegate class for SCK callbacks."""
    global _SCKDelegateClass
    if _SCKDelegateClass is not None:
        return _SCKDelegateClass
    import objc
    from Foundation import NSObject
    import ScreenCaptureKit as SCK

    SCStreamOutputProtocol = objc.protocolNamed("SCStreamOutput")
    audio_type = SCK.SCStreamOutputTypeAudio

    class _SCKDelegate(NSObject, protocols=[SCStreamOutputProtocol]):
        """Receives SCStream audio sample buffers and forwards PCM16 to a queue."""

        def initWithExtractor_queue_stopEvent_(self, extractor, q, stop_event):
            self = objc.super(_SCKDelegate, self).init()
            if self is None:
                return None
            self._extractor = extractor
            self._q = q
            self._stop_event = stop_event
            return self

        def stream_didOutputSampleBuffer_ofType_(self, stream, sampleBuffer, outputType):
            if outputType != audio_type or self._stop_event.is_set():
                return
            chunk = self._extractor(sampleBuffer)
            if chunk is not None:
                try:
                    self._q.put_nowait(chunk)
                except queue.Full:
                    pass

    _SCKDelegateClass = _SCKDelegate
    return _SCKDelegate


class SCKAudioInput(AudioInput):
    """
    Captures system audio via macOS ScreenCaptureKit (built-in, macOS 13+).

    No virtual audio device (BlackHole, Loopback, etc.) is required.
    Uses the native SCStream API to tap all system output audio, then
    delivers 20ms PCM16 mono chunks at 16kHz to the interpreter pipeline.

    Requirements:
        - macOS 13 Ventura or later
        - pip install pyobjc-framework-ScreenCaptureKit pyobjc-framework-CoreMedia
        - Screen Recording permission granted in System Settings -> Privacy

    Usage:
        inp = SCKAudioInput(sample_rate=16000)
        inp.start()
        for chunk in inp.stream_frames():
            process(chunk)   # PCM16 bytes, ~20ms each
        inp.stop()

    Optional: pass app_bundle_id to capture only one app's audio, e.g.:
        SCKAudioInput(app_bundle_id="com.google.Chrome")
    """

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        chunk_ms: int = CHUNK_MS,
        app_bundle_id: Optional[str] = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._chunk_frames = int(sample_rate * chunk_ms / 1000)
        self._app_bundle_id = app_bundle_id
        self._q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=400)
        self._stop_event = threading.Event()
        self._stream = None
        self._loop_thread: Optional[threading.Thread] = None
        self._delegate = None

        # CoreMedia ctypes function pointers (resolved in start())
        self._cm_get_data_buffer = None
        self._cm_get_length = None
        self._cm_copy_bytes = None

    def _init_cm_lib(self) -> None:
        """Load CoreMedia C functions via ctypes for low-level buffer access."""
        lib = ctypes.CDLL("/System/Library/Frameworks/CoreMedia.framework/CoreMedia")

        lib.CMSampleBufferGetDataBuffer.restype = ctypes.c_void_p
        lib.CMSampleBufferGetDataBuffer.argtypes = [ctypes.c_void_p]

        lib.CMBlockBufferGetDataLength.restype = ctypes.c_uint64
        lib.CMBlockBufferGetDataLength.argtypes = [ctypes.c_void_p]

        lib.CMBlockBufferCopyDataBytes.restype = ctypes.c_int32
        lib.CMBlockBufferCopyDataBytes.argtypes = [
            ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_void_p
        ]

        self._cm_get_data_buffer = lib.CMSampleBufferGetDataBuffer
        self._cm_get_length = lib.CMBlockBufferGetDataLength
        self._cm_copy_bytes = lib.CMBlockBufferCopyDataBytes

    def _extract_pcm16(self, sample_buffer_obj) -> Optional[bytes]:
        """
        Extract raw float32 PCM from a CMSampleBufferRef and return as PCM16 bytes.

        SCK delivers float32 interleaved samples at the configured sample_rate.
        We convert to int16 to match the PCM16 format expected by the pipeline.
        """
        try:
            ptr = ctypes.c_void_p(sample_buffer_obj.__c_void_p__().value)

            block_buf = self._cm_get_data_buffer(ptr)
            if not block_buf:
                return None

            total_len = self._cm_get_length(block_buf)
            if total_len == 0:
                return None

            buf = (ctypes.c_uint8 * total_len)()
            status = self._cm_copy_bytes(block_buf, 0, total_len, buf)
            if status != 0:
                return None

            f32 = np.frombuffer(bytes(buf), dtype=np.float32)
            if len(f32) == 0:
                return None

            # Average multi-channel to mono if needed
            if self._chunk_frames > 0 and len(f32) > self._chunk_frames:
                ch = len(f32) // self._chunk_frames
                if ch > 1 and len(f32) % ch == 0:
                    f32 = f32.reshape(-1, ch).mean(axis=1)

            np.clip(f32, -1.0, 1.0, out=f32)
            return (f32 * 32767).astype(np.int16).tobytes()
        except Exception:
            return None

    def _run_capture_loop(self) -> None:
        """Background thread: runs NSRunLoop and owns the SCStream lifecycle."""
        import time as _time
        from Foundation import NSRunLoop, NSDate
        import ScreenCaptureKit as SCK

        # Use module-level delegate class (pyobjc requires ObjC classes to be
        # defined at module scope for correct runtime registration).
        DelegateCls = _get_sck_delegate_class()
        delegate = DelegateCls.alloc().initWithExtractor_queue_stopEvent_(
            self._extract_pcm16, self._q, self._stop_event
        )
        self._delegate = delegate  # keep strong reference

        # Enumerate displays for content filter
        content_holder: list = []
        content_done = threading.Event()

        def on_content(content, err):
            content_holder.append(content if not err else None)
            content_done.set()

        SCK.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
            True, True, on_content
        )

        loop = NSRunLoop.currentRunLoop()
        deadline = _time.time() + 3.0
        while not content_done.is_set() and _time.time() < deadline:
            loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))

        content = content_holder[0] if content_holder else None
        if content is None:
            logger.error(
                "[SCKAudioInput] Failed to get shareable content. "
                "Grant Screen Recording permission in System Settings -> Privacy."
            )
            try:
                self._q.put_nowait(None)
            except queue.Full:
                pass
            return

        displays = content.displays()
        if not displays:
            logger.error("[SCKAudioInput] No displays found")
            try:
                self._q.put_nowait(None)
            except queue.Full:
                pass
            return

        display = displays[0]

        # Build content filter — optionally scoped to a single app
        if self._app_bundle_id:
            apps = content.applications()
            target = [a for a in apps if str(a.bundleIdentifier()) == self._app_bundle_id]
            if target:
                filt = SCK.SCContentFilter.alloc().initWithDisplay_includingApplications_exceptingWindows_(
                    display, target, []
                )
                logger.info(f"[SCKAudioInput] Capturing audio from app: {self._app_bundle_id}")
            else:
                logger.warning(
                    f"[SCKAudioInput] App {self._app_bundle_id!r} not found — "
                    "falling back to all system audio"
                )
                filt = SCK.SCContentFilter.alloc().initWithDisplay_excludingApplications_exceptingWindows_(
                    display, [], []
                )
        else:
            filt = SCK.SCContentFilter.alloc().initWithDisplay_excludingApplications_exceptingWindows_(
                display, [], []
            )
            logger.info("[SCKAudioInput] Capturing all system audio")

        config = SCK.SCStreamConfiguration.alloc().init()
        config.setCapturesAudio_(True)
        config.setSampleRate_(self._sample_rate)
        config.setChannelCount_(1)
        config.setExcludesCurrentProcessAudio_(True)

        stream = SCK.SCStream.alloc().initWithFilter_configuration_delegate_(filt, config, None)
        stream.addStreamOutput_type_sampleHandlerQueue_error_(
            delegate, SCK.SCStreamOutputTypeAudio, None, None
        )
        self._stream = stream

        start_done = threading.Event()
        start_err: list = []

        def on_start(err):
            if err:
                start_err.append(str(err))
            start_done.set()

        stream.startCaptureWithCompletionHandler_(on_start)

        deadline = _time.time() + 5.0
        while not start_done.is_set() and _time.time() < deadline:
            loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))

        if start_err:
            logger.error(f"[SCKAudioInput] Stream start failed: {start_err[0]}")
            try:
                self._q.put_nowait(None)
            except queue.Full:
                pass
            return

        logger.info(
            f"[SCKAudioInput] Streaming | rate={self._sample_rate}Hz "
            f"| chunk={self._chunk_frames} frames (~20ms)"
        )

        # Pump run loop until stop() is called
        while not self._stop_event.is_set():
            loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))

        stop_done = threading.Event()
        stream.stopCaptureWithCompletionHandler_(lambda e: stop_done.set())
        deadline = _time.time() + 3.0
        while not stop_done.is_set() and _time.time() < deadline:
            loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))

        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    @property
    def metadata(self) -> AudioMetadata:
        return AudioMetadata(sample_rate=self._sample_rate, channels=DEFAULT_CHANNELS)

    def start(self) -> None:
        if not _check_sck_available():
            raise RuntimeError(
                "ScreenCaptureKit not available.\n"
                "Install: pip install pyobjc-framework-ScreenCaptureKit pyobjc-framework-CoreMedia\n"
                "Requires macOS 13 Ventura or later."
            )
        self._stop_event.clear()
        self._init_cm_lib()
        self._loop_thread = threading.Thread(target=self._run_capture_loop, daemon=True)
        self._loop_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=5.0)
            self._loop_thread = None

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
# Device listing helper
# ---------------------------------------------------------------------------

def list_all_audio_devices() -> list[dict]:
    """Return all sounddevice devices with both input and output info."""
    devices = sd.query_devices()
    result = []
    for idx, dev in enumerate(devices):
        result.append({
            "index": idx,
            "name": dev["name"],
            "max_input_channels": dev["max_input_channels"],
            "max_output_channels": dev["max_output_channels"],
            "default_samplerate": int(dev["default_samplerate"]),
        })
    return result


def print_all_audio_devices() -> None:
    """Print a formatted table of all audio devices."""
    devs = list_all_audio_devices()
    if not devs:
        print("No audio devices found.")
        return
    print(f"{'Idx':>4}  {'Name':<40}  {'In':>3}  {'Out':>3}  {'DefaultHz':>10}")
    print("-" * 70)
    for d in devs:
        print(
            f"{d['index']:>4}  {d['name']:<40}  "
            f"{d['max_input_channels']:>3}  {d['max_output_channels']:>3}  "
            f"{d['default_samplerate']:>10}"
        )
