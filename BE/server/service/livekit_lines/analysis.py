from __future__ import annotations

import math

import numpy as np

SILENCE_DB = -100.0


def pcm16_level_db(pcm: bytes | bytearray | memoryview) -> float:
    """RMS level of interleaved PCM16 audio in dBFS."""
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return SILENCE_DB
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    if rms < 1.0:
        return SILENCE_DB
    return 20.0 * math.log10(rms / 32768.0)


class LineVad:
    """Energy VAD with an adaptive noise floor, onset debounce and hangover."""

    def __init__(
        self,
        *,
        abs_min_db: float,
        margin_db: float,
        onset_frames: int,
        hangover_frames: int,
    ) -> None:
        self.abs_min_db = abs_min_db
        self.margin_db = margin_db
        self.onset_frames = max(1, onset_frames)
        self.hangover_frames = max(0, hangover_frames)
        self.noise_floor_db = -65.0
        self.speaking = False
        self._above = 0
        self._below = 0

    def update(self, level_db: float) -> bool:
        if level_db < self.noise_floor_db:
            self.noise_floor_db = 0.7 * self.noise_floor_db + 0.3 * level_db
        elif not self.speaking:
            # Slow rise (~1 dB/s at 20 ms frames) so steady noise is absorbed.
            self.noise_floor_db += 0.02
        self.noise_floor_db = max(self.noise_floor_db, -90.0)

        threshold = max(self.abs_min_db, self.noise_floor_db + self.margin_db)
        if level_db >= threshold:
            self._above += 1
            self._below = 0
            if self._above >= self.onset_frames:
                self.speaking = True
        else:
            self._above = 0
            self._below += 1
            if self._below > self.hangover_frames:
                self.speaking = False
        return self.speaking


class LineClock:
    """Turns bursty frame arrival times into a smooth per-line timeline."""

    def __init__(self, *, resync_s: float = 0.25, gain: float = 0.05) -> None:
        self.resync_s = resync_s
        self.gain = gain
        self._last: float | None = None

    def stamp(self, now: float, duration_s: float) -> float:
        if self._last is None:
            ts = now
        else:
            expected = self._last + duration_s
            drift = now - expected
            ts = now if abs(drift) > self.resync_s else expected + self.gain * drift
            # Keep the timeline strictly increasing for nearest-frame lookups.
            ts = max(ts, self._last + 1e-3)
        self._last = ts
        return ts


# Speech band layout for the spectral fingerprint (log-spaced, 150 Hz - 4 kHz).
_BAND_EDGES_HZ = np.geomspace(150.0, 4000.0, 17)
BAND_COUNT = len(_BAND_EDGES_HZ) - 1
_band_plans: dict[tuple[int, int], tuple[int, np.ndarray, np.ndarray]] = {}


def _band_plan(samples: int, sample_rate: int) -> tuple[int, np.ndarray, np.ndarray]:
    key = (samples, sample_rate)
    plan = _band_plans.get(key)
    if plan is None:
        n_fft = 1 << max(0, samples - 1).bit_length()
        freqs = np.fft.rfftfreq(n_fft, 1.0 / sample_rate)
        bins = np.digitize(freqs, _BAND_EDGES_HZ) - 1
        bins[(freqs < _BAND_EDGES_HZ[0]) | (freqs >= _BAND_EDGES_HZ[-1])] = -1
        plan = (n_fft, np.hanning(samples), bins)
        _band_plans[key] = plan
    return plan


def pcm16_band_levels_db(pcm: bytes | bytearray | memoryview, sample_rate: int, channels: int = 1) -> np.ndarray:
    """Per-band log energy of one PCM16 frame (first channel)."""
    samples = np.frombuffer(pcm, dtype=np.int16)
    if channels > 1:
        samples = samples[::channels]
    if samples.size < 16 or sample_rate <= 0:
        return np.full(BAND_COUNT, SILENCE_DB)
    n_fft, window, bins = _band_plan(samples.size, sample_rate)
    power = np.abs(np.fft.rfft(samples.astype(np.float64) * window, n_fft)) ** 2
    valid = bins >= 0
    energy = np.bincount(bins[valid], weights=power[valid], minlength=BAND_COUNT)
    return 10.0 * np.log10(energy + 1.0)
