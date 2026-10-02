from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

import numpy as np

from server.service.livekit_lines.analysis import BAND_COUNT
from server.service.livekit_lines.config import LineIsolationConfig

_FRAME_S = 0.02
# Below this a slot counts as silence for activity checks.
_SILENCE_DB = -60.0
# Slots within this range of the source's loudest slot count as its speech.
_ACTIVE_RANGE_DB = 25.0
# A slot of the checked line is "active" this far above its quietest slot.
_ACTIVE_MARGIN_DB = 10.0
# Residual alignment slack when checking that bleed stays inside its source.
_REACH_BEFORE_SLOTS = 2
# Minimum source-active slots needed to compare spectra.
_MIN_ACTIVE_SLOTS = 5
# Slots around the decided frame used for the own-voice check while holding.
_OWN_VOICE_SLOTS = 2


@dataclass(frozen=True)
class CrosstalkVerdict:
    dominated_by: Optional[str] = None
    correlation: float = 0.0
    level_gap_db: float = 0.0
    # The held line rose above the bleed level expected from its source: the
    # participant started talking themselves, so isolation must end now.
    own_voice: bool = False

    @property
    def is_bleed(self) -> bool:
        return self.dominated_by is not None


_CLEAN = CrosstalkVerdict()
_OWN_VOICE = CrosstalkVerdict(own_voice=True)


class _LineHistory:
    def __init__(self, maxlen: int) -> None:
        self.ts: Deque[float] = deque(maxlen=maxlen)
        self.level: Deque[float] = deque(maxlen=maxlen)
        self.speech: Deque[bool] = deque(maxlen=maxlen)
        self.bands: Deque[np.ndarray] = deque(maxlen=maxlen)
        self._version = 0
        self._cache_version = -1
        self._cache: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None

    def append(self, ts: float, level: float, speech: bool, bands: np.ndarray) -> None:
        self.ts.append(ts)
        self.level.append(level)
        self.speech.append(speech)
        self.bands.append(bands)
        self._version += 1

    def arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if self._cache is None or self._cache_version != self._version:
            self._cache = (
                np.fromiter(self.ts, dtype=np.float64, count=len(self.ts)),
                np.fromiter(self.level, dtype=np.float64, count=len(self.level)),
                np.fromiter(self.speech, dtype=bool, count=len(self.speech)),
                np.stack(self.bands) if self.bands else np.zeros((0, BAND_COUNT)),
            )
            self._cache_version = self._version
        return self._cache


@dataclass
class _Window:
    """One line sampled on the decision grid (optionally at several lags)."""

    level: np.ndarray
    bands: np.ndarray
    valid: np.ndarray
    speech: np.ndarray


class CrosstalkArbiter:
    """Detects acoustic bleed between the isolated per-speaker lines of a room.

    LiveKit already delivers one decoded track per participant, but a mic in a
    shared physical room also picks up nearby speakers. Bleed is the other
    speaker's own waveform seen through the room, so frame by frame it carries
    the same spectral fingerprint (pitch harmonics, formants) as the source
    line, only quieter and with a fixed room colouration. A line is treated as
    bleed of another line when, at some small lag:

    - its band spectrum tracks the source's spectrum over the window;
    - it only has energy while the source is active (plus a reverb tail);
    - it sits clearly below the source in level.

    Two people genuinely talking at once have unrelated spectra and their own
    pauses, so both lines stay open.
    """

    def __init__(self, config: LineIsolationConfig) -> None:
        self.config = config
        self._lines: Dict[str, _LineHistory] = {}
        # Acoustic loss (dB) measured from each source into each bleeding line.
        self._bleed_gap: Dict[tuple[str, str], float] = {}
        self._history_len = max(10, config.history_ms // 20)
        self._half_after_s = min(config.lookahead_ms, config.window_ms // 2) / 1000.0
        self._window_s = config.window_ms / 1000.0
        max_lag = max(0, round(config.max_lag_ms / 20))
        self._lags_s = np.arange(-max_lag, max_lag + 1, dtype=np.float64) * _FRAME_S
        self._min_source_speech = max(1, round(config.min_dominant_speech_ms / 20))
        self._tail_slots = max(0, round(config.reverb_tail_ms / 20))

    def register(self, line_id: str) -> None:
        self._lines[line_id] = _LineHistory(self._history_len)

    def unregister(self, line_id: str) -> None:
        self._lines.pop(line_id, None)
        for pair in [pair for pair in self._bleed_gap if line_id in pair]:
            self._bleed_gap.pop(pair, None)

    def observe(
        self,
        line_id: str,
        ts: float,
        level_db: float,
        speech: bool,
        bands_db: Optional[np.ndarray] = None,
    ) -> None:
        history = self._lines.get(line_id)
        if history is None:
            return
        if bands_db is None:
            bands_db = np.full(BAND_COUNT, level_db)
        history.append(ts, level_db, speech, bands_db)

    def decide(self, line_id: str, ts: float, *, held_by: Optional[str] = None) -> CrosstalkVerdict:
        """Verdict for the frame of `line_id` stamped `ts`.

        Entering isolation needs every bleed check to pass at the strict
        correlation threshold. Once isolated (`held_by`), the line stays
        isolated against that source at the looser hold threshold, so bleed is
        muted as a whole utterance instead of being chopped into fragments.
        """
        own_history = self._lines.get(line_id)
        if own_history is None or len(self._lines) < 2 or len(own_history.ts) < 2:
            return _CLEAN

        grid = np.arange(
            ts - (self._window_s - self._half_after_s),
            ts + self._half_after_s + 1e-9,
            _FRAME_S,
        )
        own = _sample(own_history, grid[None, :])
        if np.count_nonzero(own.valid) < 0.7 * grid.size:
            return _CLEAN
        own_level = own.level[0][own.valid[0]]
        if own_level.size == 0 or float(np.max(own_level)) < _SILENCE_DB:
            return _CLEAN  # nothing on this line worth muting

        if held_by is not None:
            held = self._compare(
                own,
                grid,
                held_by,
                self.config.hold_correlation_threshold,
                expected_gap=self._bleed_gap.get((line_id, held_by)),
            )
            if held.is_bleed or held.own_voice:
                return held

        # Cheap pre-filter: bleed is always clearly quieter than its source, so
        # only lines whose peak beats ours by the dominance margin can qualify.
        own_peak = float(np.max(own_level))
        reach_start = grid[0] + self._lags_s[0]
        reach_end = grid[-1] + self._lags_s[-1]
        best = _CLEAN
        for other_id, other_history in self._lines.items():
            if other_id == line_id:
                continue
            other_peak, other_speech = _window_stats(other_history, reach_start, reach_end)
            if other_speech < self._min_source_speech:
                continue
            if other_peak - own_peak < self.config.dominance_db:
                continue
            verdict = self._compare(own, grid, other_id, self.config.correlation_threshold)
            if verdict.is_bleed and verdict.correlation > best.correlation:
                best = verdict
        if best.dominated_by is not None:
            pair = (line_id, best.dominated_by)
            previous = self._bleed_gap.get(pair)
            self._bleed_gap[pair] = (
                best.level_gap_db if previous is None else 0.8 * previous + 0.2 * best.level_gap_db
            )
        return best

    def _compare(
        self,
        own: _Window,
        grid: np.ndarray,
        source_id: str,
        correlation_threshold: float,
        *,
        expected_gap: Optional[float] = None,
    ) -> CrosstalkVerdict:
        history = self._lines.get(source_id)
        if history is None or len(history.ts) < 2:
            return _CLEAN
        source = _sample(history, grid[None, :] + self._lags_s[:, None])
        if int(np.count_nonzero(source.speech.any(axis=0))) < self._min_source_speech:
            return _CLEAN
        if expected_gap is not None and self._own_voice_present(own, source, grid, expected_gap):
            return _OWN_VOICE

        correlations = _spectral_correlations(own, source)
        best_lag = int(np.argmax(correlations))
        best_corr = float(correlations[best_lag])
        if best_corr < correlation_threshold:
            return _CLEAN

        level_gap = self._containment_gap(own, source, best_lag)
        if level_gap is None or level_gap < self.config.dominance_db:
            return _CLEAN
        return CrosstalkVerdict(
            dominated_by=source_id,
            correlation=best_corr,
            level_gap_db=level_gap,
        )

    def _own_voice_present(
        self,
        own: _Window,
        source: _Window,
        grid: np.ndarray,
        expected_gap: float,
    ) -> bool:
        """True when the line is clearly louder than bleed alone would make it."""
        center = int(np.argmin(np.abs(grid - (grid[-1] - self._half_after_s))))
        lo = max(0, center - _OWN_VOICE_SLOTS)
        hi = min(grid.size, center + _OWN_VOICE_SLOTS + 1)
        own_valid = own.valid[0, lo:hi]
        if not np.any(own_valid):
            return False
        own_level = own.level[0, lo:hi][own_valid]
        # Loudest bleed the source could cause at any searched lag.
        source_level = np.where(source.valid[:, lo:hi], source.level[:, lo:hi], -np.inf).max(axis=0)
        expected = source_level[own_valid] - expected_gap
        excess = own_level - np.maximum(expected, _SILENCE_DB)
        return bool(
            float(np.median(excess)) >= self.config.own_voice_margin_db
            and float(np.max(own_level)) > _SILENCE_DB
        )

    def _containment_gap(self, own: _Window, source: _Window, lag: int) -> Optional[float]:
        """Median level gap if the line only has energy while the source talks."""
        valid = own.valid[0] & source.valid[lag]
        own_level = own.level[0][valid]
        source_level = source.level[lag][valid]
        if own_level.size < _MIN_ACTIVE_SLOTS:
            return None
        source_active = _source_active(source_level)
        own_active = own_level >= max(float(np.min(own_level)) + _ACTIVE_MARGIN_DB, _SILENCE_DB)
        if not np.any(own_active) or not np.any(source_active):
            return None
        # Bleed cannot carry energy while its source is silent (beyond a short
        # reverb tail): an independent talker is active where the source is quiet.
        reach = _dilate(source_active, before=_REACH_BEFORE_SLOTS, after=self._tail_slots)
        if float(np.mean(reach[own_active])) < self.config.containment_threshold:
            return None
        both = own_active & source_active
        if not np.any(both):
            return None
        return float(np.median(source_level[both] - own_level[both]))


def _sample(history: _LineHistory, times: np.ndarray) -> _Window:
    """Nearest-frame sampling of a line history at `times` (shape: lags x slots)."""
    ts, level, speech, bands = history.arrays()
    idx = np.clip(np.searchsorted(ts, times), 1, len(ts) - 1)
    left = idx - 1
    nearest = np.where(np.abs(ts[left] - times) <= np.abs(ts[idx] - times), left, idx)
    valid = np.abs(ts[nearest] - times) <= _FRAME_S * 0.6
    return _Window(
        level=level[nearest],
        bands=bands[nearest],
        valid=valid,
        speech=speech[nearest] & valid,
    )


def _source_active(level: np.ndarray) -> np.ndarray:
    if level.size == 0:
        return np.zeros(0, dtype=bool)
    return (level >= float(np.max(level)) - _ACTIVE_RANGE_DB) & (level > _SILENCE_DB)


def _window_stats(history: _LineHistory, start: float, end: float) -> tuple[float, int]:
    """Peak level and speech-frame count of a line between `start` and `end`."""
    ts, level, speech, _ = history.arrays()
    lo = int(np.searchsorted(ts, start, side="left"))
    hi = int(np.searchsorted(ts, end, side="right"))
    if hi <= lo:
        return float("-inf"), 0
    return float(np.max(level[lo:hi])), int(np.count_nonzero(speech[lo:hi]))


def _spectral_correlations(own: _Window, source: _Window) -> np.ndarray:
    """Per-lag correlation of band spectra over the slots where the source is active.

    Per-band means are removed first, which cancels a constant room / mic
    colouration and the overall level difference between the two lines.
    """
    valid = own.valid & source.valid  # lags x slots
    masked_level = np.where(valid, source.level, -np.inf)
    peak = masked_level.max(axis=1, keepdims=True)
    active = valid & (source.level >= peak - _ACTIVE_RANGE_DB) & (source.level > _SILENCE_DB)
    counts = active.sum(axis=1)
    weights = active[:, :, None].astype(np.float64)
    safe = np.maximum(counts, 1)[:, None, None]

    own_bands = own.bands  # 1 x slots x bands, broadcast over lags
    own_mean = (own_bands * weights).sum(axis=1, keepdims=True) / safe
    source_mean = (source.bands * weights).sum(axis=1, keepdims=True) / safe
    own_c = (own_bands - own_mean) * weights
    source_c = (source.bands - source_mean) * weights
    numerator = np.einsum("lsb,lsb->l", own_c, source_c)
    denom = np.sqrt(np.einsum("lsb,lsb->l", own_c, own_c) * np.einsum("lsb,lsb->l", source_c, source_c))
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.where(denom > 0, numerator / denom, -1.0)
    return np.where(counts >= _MIN_ACTIVE_SLOTS, corr, -1.0)


def _dilate(mask: np.ndarray, *, before: int, after: int) -> np.ndarray:
    """Extend True runs `after` slots later and `before` slots earlier."""
    out = mask.copy()
    for shift in range(1, min(after, mask.size - 1) + 1):
        out[shift:] |= mask[:-shift]
    for shift in range(1, min(before, mask.size - 1) + 1):
        out[:-shift] |= mask[shift:]
    return out
