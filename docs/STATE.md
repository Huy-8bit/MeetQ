# STATE

## Current Status

- Phase 1 local mic interpreter: complete and working.
- Phase 2 Google Meet Listener: planned; documentation package completed.
- No Phase 2 runtime implementation merged yet.

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| Phase 1: Local mic realtime interpreter | COMPLETE | Realtime + fallback modes are implemented |
| Phase 2: Google Meet Listener design | COMPLETE | Spec and planning docs created |
| Phase 2: Google Meet Listener implementation | PLANNED | Awaiting path decision and compliance gate |

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
│   └── fallback/
├── recordings/
└── logs/
```

## Active Planning Docs

- `docs/phase2_google_meet.md`: Phase 2 main design and operational spec.
- `docs/architecture.md`: updated architecture with `AudioInput`, `MicInput`, and `MeetInput`.
- `docs/next_steps_google_meet.md`: execution plan and milestone gates.

## How To Resume

1. Read `docs/phase2_google_meet.md` and `docs/next_steps_google_meet.md`.
2. Start from first planned Phase 2 task in `docs/TASKS.md` (`TASK-15`).
3. Keep capability claims conservative until official access is validated.

## Log

- 2026-03-03: Phase 1 implementation completed (mic realtime + fallback).
- 2026-03-03: Meeting mode and language routing enhancements completed.
- 2026-03-03: Phase 2 documentation package added (`phase2_google_meet.md` + related doc updates).
