from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LineIsolationConfig:
    """Tuning knobs for per-speaker line isolation.

    Defaults target browser mics with AEC/NS/AGC enabled, 20 ms frames.
    """

    enabled: bool = True
    # Frames are held this long so the crosstalk decision can see a little
    # "future" audio from other lines (bleed may arrive before its source).
    lookahead_ms: int = 120
    # Spectral fingerprint window compared between lines.
    window_ms: int = 600
    # Max relative delay searched between two lines. Bleed only happens between
    # co-located people (same LAN), so only jitter-buffer differences remain.
    max_lag_ms: int = 120
    # Band-spectrum correlation needed to start treating a line as bleed.
    correlation_threshold: float = 0.75
    # Looser correlation that keeps an already isolated line isolated.
    hold_correlation_threshold: float = 0.55
    # Share of the quiet line's active slots that must overlap the louder
    # line's active slots (bleed has no energy while its source is silent).
    containment_threshold: float = 0.85
    # While isolated, a line this far above its expected bleed level is the
    # participant's own voice and is reopened immediately.
    own_voice_margin_db: float = 6.0
    # Bleed may keep ringing this long after its source stops (room reverb).
    reverb_tail_ms: int = 160
    # Source line must be at least this much louder than the bleed line.
    dominance_db: float = 4.0
    # The dominant line needs this much speech inside the window.
    min_dominant_speech_ms: int = 100
    # Frames of clean verdicts before an isolated (muted) line is reopened.
    release_ms: int = 80
    # Bounded per-consumer buffer; oldest frames are dropped when full.
    consumer_queue_frames: int = 50
    # History kept per line for arbitration.
    history_ms: int = 2000
    # VAD
    vad_abs_min_db: float = -50.0
    vad_margin_db: float = 10.0
    vad_onset_frames: int = 2
    vad_hangover_frames: int = 15
    # Periodic per-line stats log interval (0 disables).
    stats_log_interval_s: float = 15.0

    @classmethod
    def from_settings(cls, settings: Any) -> "LineIsolationConfig":
        return cls(
            enabled=bool(getattr(settings, "livekit_line_isolation_enabled", True)),
            lookahead_ms=int(getattr(settings, "livekit_line_lookahead_ms", cls.lookahead_ms)),
            correlation_threshold=float(
                getattr(settings, "livekit_line_crosstalk_correlation", cls.correlation_threshold)
            ),
            dominance_db=float(
                getattr(settings, "livekit_line_crosstalk_dominance_db", cls.dominance_db)
            ),
        )
