# STATE

## Current Status (2026-03-09)

### Phase 1 - Core Interpreter
- Realtime mic interpreter: implemented.
- Realtime device-input interpreter (`--input device`): implemented.
- Fallback clip pipeline: implemented.
- Language routing options (`--src`, `--tgt`, `--pairs`, `--meeting-mode`): implemented.

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| M1 Phase 1 realtime interpreter | DONE | Mic + device input + dynamic language routing |
| M2 Fallback interpreter path | DONE | WAV recording + transcription + translation |

## Known Implementation Caveats

- Fallback mode always persists WAV clips in `recordings/`.

## Resume Checklist

1. Use `python app.py --mode realtime` for core interpreter smoke tests.
2. Use `python app.py --mode realtime --input device --input-device <idx> --no-speaker` for loopback tests.
3. Use `python app.py --mode fallback` for fallback tests.

## File Map

```text
brseAI/
├── app.py
├── README.md
├── requirements.txt
├── Dockerfile
├── docs/
│   ├── architecture.md
│   ├── realtime_protocol.md
│   ├── security.md
│   ├── TASKS.md
│   └── STATE.md
├── src/
│   ├── common/
│   │   ├── audio.py
│   │   ├── lang.py
│   │   └── logging_utils.py
│   ├── realtime/
│   │   ├── client.py
│   │   └── main.py
│   └── fallback/
│       ├── pipeline.py
│       └── main.py
├── tests/
│   └── test_realtime_observability.py
├── recordings/
└── logs/
```

## Change Log

- 2026-03-03: Phase 1 realtime + fallback interpreter path completed.
- 2026-03-03: Language routing and meeting-mode behavior added (`locked`/`auto`, pair filters).
- 2026-03-03: Device loopback input added for realtime (`--input device`).
- 2026-03-04: Documentation synchronized to current implementation and known limitations.
- 2026-03-09: Platform-specific code (Google Meet, Discord) removed. Focus on core translation engine.

