import asyncio

import livekit.rtc as rtc
import numpy as np
import pytest

from server.service.livekit_lines import (
    CrosstalkArbiter,
    LineIsolationConfig,
    SpeakerLine,
    SpeakerLineHub,
)
from server.service.livekit_lines.analysis import (
    BAND_COUNT,
    LineVad,
    pcm16_band_levels_db,
    pcm16_level_db,
)
from server.service.media.audio_input import LiveKitAudioInput

_SR = 24000
_FRAME = 480  # 20 ms


# --- synthetic room audio -------------------------------------------------


def _speech(rng: np.random.Generator, frames: int, level_db: float = -24.0) -> np.ndarray:
    """Voiced syllables with per-syllable pitch and formants, separated by pauses."""
    n = frames * _FRAME
    out = np.zeros(n)
    start = 0
    while start < n:
        on = int(rng.integers(5, 14)) * _FRAME
        off = int(rng.integers(2, 8)) * _FRAME
        seg = min(on, n - start)
        t = np.arange(seg) / _SR
        f0 = rng.uniform(90, 230) * (1 + 0.1 * np.sin(2 * np.pi * rng.uniform(1, 4) * t))
        phase = 2 * np.pi * np.cumsum(f0) / _SR
        formants = rng.uniform([300, 900, 2200], [900, 2200, 3200])
        sig = np.zeros(seg)
        for h in range(1, 40):
            fh = f0.mean() * h
            if fh > 5000:
                break
            sig += (sum(np.exp(-(((fh - f) / 150.0) ** 2)) for f in formants) + 0.05) * np.sin(h * phase)
        ramp = np.minimum(1, np.minimum(np.arange(seg), seg - np.arange(seg)) / (0.03 * _SR))
        out[start : start + seg] = sig * ramp * rng.uniform(0.5, 1.0)
        start += on + off
    rms = np.sqrt(np.mean(out[out != 0] ** 2))
    return out / rms * 32768 * 10 ** (level_db / 20)


def _bleed(rng: np.random.Generator, source: np.ndarray, gap_db: float, delay_ms: int) -> np.ndarray:
    """`source` as heard by another mic in the room: reverb, colouration, delay."""
    taps = int(0.4 * _SR)
    t = np.arange(taps) / _SR
    ir = rng.normal(0, 1, taps) * np.exp(-6.9 * t / 0.4) * 0.25
    ir[int(0.004 * _SR)] += 1.0
    ir = np.convolve(ir, np.r_[1.0, rng.normal(0, 0.3, 7)])
    ir /= np.sqrt(np.sum(ir**2))
    size = 1 << (len(source) + len(ir)).bit_length()
    wet = np.fft.irfft(np.fft.rfft(source, size) * np.fft.rfft(ir, size), size)[: len(source)]
    shift = int(delay_ms * _SR / 1000)
    return np.r_[np.zeros(shift), wet[: len(wet) - shift]] * 10 ** (gap_db / 20)


def _frames(rng: np.random.Generator, signal: np.ndarray) -> list[bytes]:
    pcm = np.clip(signal + rng.normal(0, 8, len(signal)), -32768, 32767).astype(np.int16)
    return [pcm[i : i + _FRAME].tobytes() for i in range(0, len(pcm) - _FRAME + 1, _FRAME)]


def _audible(signal: np.ndarray) -> np.ndarray:
    rms = np.sqrt(np.mean(signal[: len(signal) // _FRAME * _FRAME].reshape(-1, _FRAME) ** 2, axis=1))
    return 20 * np.log10(rms / 32768 + 1e-9) > -50


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Frame:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.sample_rate = _SR
        self.num_channels = 1


def _run_lines(lines: dict[str, list[bytes]], config: LineIsolationConfig | None = None):
    """Feed frames to SpeakerLines in lockstep; return per-frame isolation flags."""
    config = config or LineIsolationConfig()
    clock = _Clock()
    arbiter = CrosstalkArbiter(config)
    objs = {line_id: SpeakerLine(line_id, None, arbiter, config, clock=clock) for line_id in lines}
    flags: dict[str, list[bool]] = {line_id: [] for line_id in lines}
    for line_id, line in objs.items():
        release = line._release

        def wrapped(pending, line=line, line_id=line_id, release=release):
            release(pending)
            flags[line_id].append(line.isolated)

        line._release = wrapped
    total = len(next(iter(lines.values())))
    for i in range(total):
        clock.now += 0.02
        for line_id, frames in lines.items():
            objs[line_id].ingest(_Frame(frames[i]))
    return {line_id: np.array(v) for line_id, v in flags.items()}, objs


def _muted_share(flags: np.ndarray, audible: np.ndarray, skip: int = 40) -> float:
    mask = audible[: len(flags)].copy()
    mask[:skip] = False
    return float(flags[mask].mean())


# --- analysis -------------------------------------------------------------


def test_pcm_level_and_vad_track_speech():
    rng = np.random.default_rng(1)
    silence = _frames(rng, np.zeros(30 * _FRAME))
    talk = _frames(rng, rng.normal(0, 3000, 20 * _FRAME))
    assert pcm16_level_db(silence[0]) < -60
    assert pcm16_level_db(talk[0]) > -25

    vad = LineVad(abs_min_db=-50, margin_db=10, onset_frames=2, hangover_frames=3)
    states = [vad.update(pcm16_level_db(f)) for f in silence + talk + silence]
    assert not any(states[:30])
    assert all(states[32:50])
    assert not any(states[55:])


def test_band_levels_locate_a_tone():
    tone = (8000 * np.sin(2 * np.pi * 1000 * np.arange(_FRAME) / _SR)).astype(np.int16).tobytes()
    bands = pcm16_band_levels_db(tone, _SR)
    assert bands.shape == (BAND_COUNT,)
    edges = np.geomspace(150.0, 4000.0, BAND_COUNT + 1)
    assert int(np.argmax(bands)) == int(np.searchsorted(edges, 1000.0) - 1)


# --- crosstalk isolation --------------------------------------------------


@pytest.mark.parametrize("gap_db,delay_ms", [(-10, 0), (-16, 40), (-24, 90)])
def test_bleed_line_is_muted_and_source_line_untouched(gap_db, delay_ms):
    rng = np.random.default_rng(7)
    alice = _speech(rng, 250, -22)
    bob = _bleed(rng, alice, gap_db, delay_ms)
    flags, objs = _run_lines({"alice": _frames(rng, alice), "bob": _frames(rng, bob)})

    assert not flags["alice"].any()
    assert _muted_share(flags["bob"], _audible(bob)) > 0.95
    assert objs["bob"].isolation_events_total >= 1


def test_independent_simultaneous_speakers_stay_open():
    rng = np.random.default_rng(8)
    alice = _speech(rng, 250, -22)
    bob = _speech(rng, 250, -30)
    flags, _ = _run_lines({"alice": _frames(rng, alice), "bob": _frames(rng, bob)})
    assert not flags["alice"].any()
    assert not flags["bob"].any()


def test_speaker_talking_over_bleed_is_not_muted():
    rng = np.random.default_rng(9)
    alice = _speech(rng, 250, -22)
    bob_voice = _speech(rng, 250, -26)
    bob = bob_voice + _bleed(rng, alice, -14, 30)
    flags, _ = _run_lines({"alice": _frames(rng, alice), "bob": _frames(rng, bob)})
    assert not flags["alice"].any()
    assert _muted_share(flags["bob"], _audible(bob_voice)) < 0.05


def test_isolated_line_reopens_when_participant_starts_talking():
    rng = np.random.default_rng(10)
    alice = _speech(rng, 300, -22)
    bob_voice = np.zeros_like(alice)
    bob_voice[200 * _FRAME :] = _speech(rng, 100, -20)
    bob = _bleed(rng, alice, -16, 20) + bob_voice
    flags, _ = _run_lines({"alice": _frames(rng, alice), "bob": _frames(rng, bob)})

    assert flags["bob"][60:180].mean() > 0.9  # bleed-only stretch
    lookahead = LineIsolationConfig().lookahead_ms // 20
    speaking = _audible(bob_voice)[: len(flags["bob"]) + lookahead][lookahead:]
    speaking[: 200 + 5] = False  # allow a few frames to detect the onset
    assert flags["bob"][speaking[: len(flags["bob"])]].mean() < 0.1


# --- hub / stream lifecycle -----------------------------------------------


class _QueueSource:
    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.closed = False

    def push(self, pcm: bytes) -> None:
        frame = rtc.AudioFrame(data=pcm, sample_rate=_SR, num_channels=1, samples_per_channel=_FRAME)
        self.queue.put_nowait(rtc.AudioFrameEvent(frame=frame))

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def aclose(self) -> None:
        self.closed = True
        self.queue.put_nowait(None)


@pytest.mark.asyncio
async def test_line_stream_reiterates_after_consumer_cancel_and_closes_with_track():
    clock = _Clock()
    hub = SpeakerLineHub("rm_test", LineIsolationConfig(lookahead_ms=0), clock=clock)
    source = _QueueSource()
    stream = hub.open_line("alice", source)
    pcm = np.full(_FRAME, 1000, dtype=np.int16).tobytes()

    async def consume_one():
        event = await stream.__anext__()
        return bytes(event.frame.data.cast("B"))

    task = asyncio.create_task(consume_one())
    clock.now += 0.02
    source.push(pcm)
    assert await asyncio.wait_for(task, 1.0) == pcm

    pending = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    clock.now += 0.02
    source.push(pcm)  # no consumer attached: must not be replayed later
    await asyncio.sleep(0.01)

    task = asyncio.create_task(consume_one())
    await asyncio.sleep(0)
    clock.now += 0.02
    source.push(pcm[::-1])
    assert await asyncio.wait_for(task, 1.0) == pcm[::-1]

    await stream.aclose()  # consumer close keeps the LiveKit track open
    assert not source.closed
    await hub.close_line("alice")
    assert source.closed
    assert hub.get("alice") is None


@pytest.mark.asyncio
async def test_track_end_finishes_line_and_streams():
    hub = SpeakerLineHub("rm_test", LineIsolationConfig(lookahead_ms=0), clock=_Clock())
    source = _QueueSource()
    stream = hub.open_line("alice", source)
    source.queue.put_nowait(None)  # LiveKit stream ended
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(stream.__anext__(), 1.0)
    assert hub.get("alice") is None


@pytest.mark.asyncio
async def test_livekit_audio_input_consumes_line_stream():
    clock = _Clock()
    hub = SpeakerLineHub("rm_test", LineIsolationConfig(lookahead_ms=0), clock=clock)
    source = _QueueSource()
    stream = hub.open_line("alice", source)
    audio_input = LiveKitAudioInput("alice", stream, sample_rate=_SR, loop=asyncio.get_running_loop())
    audio_input.start()
    audio_input.set_streaming_ready(True)
    pcm = np.full(_FRAME, 1234, dtype=np.int16).tobytes()
    for _ in range(3):
        clock.now += 0.02
        source.push(pcm)
    await asyncio.sleep(0.05)
    assert audio_input._q.get_nowait() == pcm
    audio_input.stop(close_stream=True)
    await asyncio.sleep(0.01)
    assert not source.closed
    await hub.close_all()
    assert source.closed


@pytest.mark.asyncio
async def test_livekit_runtime_routes_mic_tracks_through_line_hub(fake_settings, monkeypatch):
    from types import SimpleNamespace

    from server.service.livekit_lines import SpeakerLineStream
    from server.service.media.livekit_runtime import LiveKitRuntime

    sources: list[_QueueSource] = []

    def fake_from_track(**_kwargs):
        sources.append(_QueueSource())
        return sources[-1]

    monkeypatch.setattr(rtc.AudioStream, "from_track", staticmethod(fake_from_track))
    received: dict[str, object] = {}
    runtime = LiveKitRuntime(
        room_id="rm_test",
        settings=fake_settings,
        on_media_connected=lambda _pid: None,
        on_media_disconnected=lambda _pid: None,
        on_audio_stream=lambda pid, stream: received.__setitem__(pid, stream),
    )
    runtime._loop = asyncio.get_running_loop()
    participant = SimpleNamespace(identity="pt_alice")
    publication = SimpleNamespace(kind=rtc.TrackKind.KIND_AUDIO, source=rtc.TrackSource.SOURCE_MICROPHONE)

    runtime._on_track_subscribed(object(), publication, participant)
    assert isinstance(received["pt_alice"], SpeakerLineStream)
    assert runtime.lines is not None and runtime.lines.get("pt_alice") is not None

    runtime._on_track_unsubscribed(object(), publication, participant)
    await asyncio.sleep(0.01)
    assert runtime.lines.get("pt_alice") is None
    assert sources[0].closed


@pytest.mark.asyncio
async def test_livekit_runtime_passes_raw_stream_when_isolation_disabled(fake_settings, monkeypatch):
    from types import SimpleNamespace

    from server.service.media.livekit_runtime import LiveKitRuntime

    raw = _QueueSource()
    monkeypatch.setattr(rtc.AudioStream, "from_track", staticmethod(lambda **_kwargs: raw))
    fake_settings.livekit_line_isolation_enabled = False
    received: dict[str, object] = {}
    runtime = LiveKitRuntime(
        room_id="rm_test",
        settings=fake_settings,
        on_media_connected=lambda _pid: None,
        on_media_disconnected=lambda _pid: None,
        on_audio_stream=lambda pid, stream: received.__setitem__(pid, stream),
    )
    runtime._loop = asyncio.get_running_loop()
    publication = SimpleNamespace(kind=rtc.TrackKind.KIND_AUDIO, source=rtc.TrackSource.SOURCE_MICROPHONE)
    runtime._on_track_subscribed(object(), publication, SimpleNamespace(identity="pt_alice"))
    assert runtime.lines is None
    assert received["pt_alice"] is raw


@pytest.mark.asyncio
async def test_line_fails_open_when_isolation_raises(monkeypatch):
    hub = SpeakerLineHub("rm_test", LineIsolationConfig(lookahead_ms=0), clock=_Clock())
    source = _QueueSource()
    stream = hub.open_line("alice", source)

    def boom(*_args, **_kwargs):
        raise RuntimeError("analysis bug")

    monkeypatch.setattr(hub.arbiter, "observe", boom)
    pcm = np.full(_FRAME, 777, dtype=np.int16).tobytes()
    source.push(pcm)
    event = await asyncio.wait_for(stream.__anext__(), 1.0)
    assert bytes(event.frame.data.cast("B")) == pcm
    assert hub.get("alice").ingest_failures_total == 1
    await hub.close_all()
