import asyncio
import threading
import time
from types import SimpleNamespace

import livekit.rtc as rtc

from server.interpreter.audio_input import LiveKitAudioInput


def _pcm_chunk(sample_value: int, samples: int) -> bytes:
    return int(sample_value).to_bytes(2, byteorder="little", signed=True) * samples


def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


class LoopThread:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._started = threading.Event()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self._started.set()
        self.loop.run_forever()

    def __enter__(self):
        self._thread.start()
        self._started.wait(timeout=1.0)
        return self.loop

    def __exit__(self, exc_type, exc, tb) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=1.0)
        self.loop.close()


class FakeAudioStream:
    def __init__(self, frames: list[bytes], delay: float = 0.0) -> None:
        self._frames = frames
        self._delay = delay
        self.index = 0
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed or self.index >= len(self._frames):
            raise StopAsyncIteration
        if self._delay:
            await asyncio.sleep(self._delay)

        payload = self._frames[self.index]
        self.index += 1
        return SimpleNamespace(
            frame=rtc.AudioFrame(
                data=payload,
                sample_rate=16000,
                num_channels=1,
                samples_per_channel=len(payload) // 2,
            )
        )

    async def aclose(self) -> None:
        self.closed = True


class BlockingAudioStream:
    def __init__(self) -> None:
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        while not self.closed:
            await asyncio.sleep(0.01)
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


def test_livekit_audio_input_yields_native_20ms_frames():
    frames = [_pcm_chunk(1, 320), _pcm_chunk(2, 320)]

    with LoopThread() as loop:
        stream = FakeAudioStream(frames)
        audio_input = LiveKitAudioInput("speaker-1", stream, loop=loop)

        audio_input.start()
        chunks = list(audio_input.stream_frames())

    assert chunks == frames
    assert audio_input.metadata.sample_rate == 16000
    assert audio_input.metadata.channels == 1
    assert audio_input.metadata.speaker_id == "speaker-1"


def test_livekit_audio_input_rechunks_irregular_frames():
    parts = [_pcm_chunk(1, 80), _pcm_chunk(2, 240), _pcm_chunk(3, 320)]
    raw = b"".join(parts)

    with LoopThread() as loop:
        stream = FakeAudioStream(parts)
        audio_input = LiveKitAudioInput("speaker-2", stream, loop=loop)

        audio_input.start()
        chunks = list(audio_input.stream_frames())

    assert chunks == [raw[:640], raw[640:1280]]


def test_livekit_audio_input_stop_pushes_sentinel():
    with LoopThread() as loop:
        stream = BlockingAudioStream()
        audio_input = LiveKitAudioInput("speaker-3", stream, loop=loop)

        audio_input.start()
        audio_input.stop()
        started_at = time.monotonic()
        chunks = list(audio_input.stream_frames())
        elapsed = time.monotonic() - started_at
        _wait_until(lambda: stream.closed)

    assert chunks == []
    assert elapsed < 0.5


def test_livekit_audio_input_drops_oldest_when_queue_full():
    frames = [_pcm_chunk(i, 320) for i in range(1, 5)]

    with LoopThread() as loop:
        stream = FakeAudioStream(frames)
        audio_input = LiveKitAudioInput(
            "speaker-4",
            stream,
            loop=loop,
            queue_maxsize=2,
        )

        audio_input.start()
        _wait_until(lambda: stream.index == len(frames))
        chunks = list(audio_input.stream_frames())

    assert chunks == frames[-2:]
