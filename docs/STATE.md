# STATE

## Current Status

- Phase 1 local mic interpreter: complete and working.
- Phase 2 AudioInput abstraction + DeviceLoopbackInput: complete (TASK-15).
- Phase 2 Full Meet Interpreter Bot MVP: complete (TASK-16).
  - `python app.py --mode meet-bot` — joins Google Meet via Playwright, listens via loopback device, translates, optionally speaks back via virtual mic device.
  - Requires: `playwright`, virtual audio device (BlackHole/Loopback), persistent browser profile.
- Production deployment blocked pending legal/privacy review and participant consent controls.

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| Phase 1: Local mic realtime interpreter | COMPLETE | Realtime + fallback modes are implemented |
| Phase 2: Google Meet Listener design | COMPLETE | Spec and planning docs created |
| Phase 2: AudioInput abstraction + DeviceLoopbackInput | COMPLETE | `AudioInput` ABC, `MicInput`, `DeviceLoopbackInput` implemented; CLI flags added |
| Phase 2: Full Meet Interpreter Bot MVP (TASK-16) | COMPLETE | Playwright bot + virtual audio routing + TTS injection; `--mode meet-bot` |

## Key Assumptions / Constraints

- Python 3.10+ runtime remains baseline.
- Existing translation pipeline continues to use OpenAI Realtime WebSocket.
- `AudioInput` will be the shared abstraction for mic and meeting sources.
- Google Meet official media capabilities may depend on access approval, Workspace admin controls, and policy constraints.
- Audio send/injection into Meet is treated as uncertain unless explicitly confirmed during official-path discovery.
- Phase 2 default posture is receive/listen only.
- Production deployment is blocked pending legal/privacy review and participant consent controls.

## File Map

```text
brseAI/
├── app.py
├── requirements.txt
├── README.md
├── .env.example
├── docs/
│   ├── TASKS.md
│   ├── STATE.md
│   ├── architecture.md
│   ├── realtime_protocol.md
│   ├── security.md
│   ├── next_steps_google_meet.md
│   └── phase2_google_meet.md
├── src/
│   ├── common/
│   ├── realtime/
│   ├── fallback/
│   └── meet/
├── recordings/
└── logs/
```

## Active Planning Docs

- `docs/phase2_google_meet.md`: Phase 2 main design and operational spec.
- `docs/architecture.md`: updated architecture with `AudioInput`, `MicInput`, and `MeetInput`.
- `docs/next_steps_google_meet.md`: execution plan and milestone gates.

## How To Resume

1. Read `docs/phase2_google_meet.md` for compliance constraints.
2. All current MVP tasks (TASK-15, TASK-16) are DONE.
3. Next planned tasks: TASK-17 (Path A feasibility), TASK-18 (privacy/consent controls), TASK-19 (pilot runbook).
4. For bot testing: install `playwright`, set up virtual audio device, run `--setup-profile` once, then `--mode meet-bot`.

## Log

- 2026-03-03: Phase 1 implementation completed (mic realtime + fallback).
- 2026-03-03: Meeting mode and language routing enhancements completed.
- 2026-03-03: Phase 2 documentation package added (`phase2_google_meet.md` + related doc updates).
- 2026-03-03: Phase 2 MVP implemented — `AudioInput` ABC, `MicInput`, `DeviceLoopbackInput`; `RealtimeClient` accepts any `AudioInput`; `--input`, `--input-device`, `--input-rate`, `--list-input-devices` CLI flags added.
- 2026-03-03: Full Meet Interpreter Bot MVP implemented (TASK-16) — `src/meet/` package: `MeetBot` (Playwright joiner), `MeetAudioListenerInput`, `MeetAudioMicOutput`, `selectors.py`; `--mode meet-bot` in `app.py`; README updated.
