# Phase 2 Google Meet

## Status Snapshot (2026-03-04)

Phase 2 is partially implemented for internal testing.

Implemented today:
- Playwright Meet bot lifecycle (`src/meet/bot.py`): navigate, pre-join setup, click join, waiting-room polling, leave.
- Meet audio adapters (`src/meet/audio.py`):
  - `MeetAudioListenerInput` for virtual loopback capture.
  - `MeetAudioMicOutput` for virtual mic playback.
  - `SCKAudioInput` code path for macOS ScreenCaptureKit capture.
- Meet runtime wiring (`src/meet/main.py`) into existing `RealtimeClient`.
- Shared language routing and meeting-mode behavior (`locked` / `auto`) reused from realtime path.

Not production-ready:
- Compliance controls (consent UX, retention controls, access governance).
- Robust e2e validation and automated reliability testing.
- Official Google Meet media API integration (Path A) confirmation.

## Implemented vs Planned

| Area | Implemented | Planned / Remaining |
|---|---|---|
| Meeting join automation | Yes (`MeetBot`) | Harden against UI drift, better diagnostics for selector breakage |
| Waiting-room handling | Yes (poll + timeout) | Host-policy preflight checks and explicit operator prompts |
| Meeting audio capture (loopback device) | Yes (`--meet-speaker-device`) | Cross-platform setup guides and automated preflight checks |
| Meeting audio capture (ScreenCaptureKit) | Code exists (`--sck`) | Runtime hardening + broader validation |
| Translate in realtime | Yes (reuse `RealtimeClient`) | Latency instrumentation and SLO reporting |
| Bot speak-back into meeting | Code path exists (`--meet-mic-device`) | Full e2e validation and route verification in real meetings |
| Top-level app meet CLI parity | Partial (`app.py --mode meet-bot`) | Unify parser/flags with `src/meet/main.py` |
| Official Meet API path (Path A) | No | Access feasibility + capability confirmation |
| Privacy/compliance controls | Partial docs only | Enforced consent, redaction, retention, access control |

## Current Implementation Approach

Current operational path is browser automation + local audio routing.

1. Join flow
- Launch Chromium with persistent profile directory.
- Navigate to meeting URL.
- Dismiss common popups, set display name, attempt join.
- If waiting room is detected, poll until admitted or timeout.

2. Audio ingestion
- Preferred stable path today: loopback device capture with `--meet-speaker-device`.
- Optional path in code: `--sck` for macOS ScreenCaptureKit capture.

3. Interpreter
- Feed audio into `RealtimeClient` using `AudioInput` abstraction.
- Stream translated text in terminal (`[Interp]`).
- Keep language routing with `--src`, `--tgt`, `--pairs`, `--meeting-mode`.

4. Optional audio output back to meeting
- If `--meet-mic-device` is set, a virtual output path is intended for translated TTS injection.
- If omitted, run in listen-only mode.

## Operational Assumptions

### Virtual audio routing (current internal approach)

Assumes local control of Chrome/OS device routing:
- Meeting output audio can be directed to an input-capturable virtual device.
- Bot playback can be directed to a virtual output device configured as meeting microphone input.
- Operator can manage device indices and sample-rate compatibility.

### Official Meet Media API (future / uncertain)

Assumes additional prerequisites not yet confirmed in this repo:
- Workspace/admin enablement and possibly allowlisted capabilities.
- Documented policy/legal approvals.
- Capability confirmation for receive and (if needed) send/injection behavior.

## Limitations & Risks

### Policy / Terms / Privacy

- Bot automation in meetings may violate organizational policy or platform terms depending on context.
- Meeting audio capture requires explicit participant consent and legal review before non-internal usage.
- Browser profile storage includes sensitive session state; treat profile directory as credential material.

### Automation brittleness

- Meet UI selectors can change without notice.
- Join/admit path depends on host policy and tenant-specific UI variations.
- Headless mode can be blocked or behave differently.

### Audio routing fragility

- Wrong input/output device mapping can cause silence, echo, or feedback loops.
- Sample-rate mismatches can degrade quality or fail stream open.
- Multi-app/system audio contamination is possible when capture is not app-scoped.

### Latency and quality

- End-to-end latency depends on capture buffering, network RTT, VAD boundaries, and response generation.
- Overlapping speakers and mixed-room audio reduce translation quality.
- No speaker diarization is implemented.

### Current implementation caveats

- `app.py --mode meet-bot` does not expose all meet parser flags available in `src/meet/main.py`; meet operations should currently use `python -m src.meet.main`.
- `--sck` path is present but less battle-tested than virtual loopback capture.
- Speak-back path (`--meet-mic-device`) exists in code but still requires stronger e2e validation.

## Recommended Internal-Only Run Pattern

```bash
python -m src.meet.main --setup-profile --profile-dir ~/.brseai_profile

python -m src.meet.main \
  --meeting-url https://meet.google.com/abc-defg-hij \
  --profile-dir ~/.brseai_profile \
  --meet-speaker-device <INPUT_INDEX> \
  --meeting-mode locked \
  --src auto --tgt auto
```

## Next Hardening Priorities

1. Unify meet CLI behavior between `app.py` and `src/meet/main.py`.
2. Add e2e smoke tests for join/wait/admit/audio-capture/audio-output.
3. Add preflight checks for device mapping and sample rates.
4. Instrument latency and failure metrics.
5. Implement enforceable consent + retention controls before any external deployment.
