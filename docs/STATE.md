# STATE

## Current Status (2026-03-08)

### Phase 1
- Realtime mic interpreter: implemented.
- Realtime device-input interpreter (`--input device`): implemented.
- Fallback clip pipeline: implemented.
- Language routing options (`--src`, `--tgt`, `--pairs`, `--meeting-mode`): implemented.

### Phase 2 (Google Meet)
Implemented for internal testing:
- Playwright join/waiting-room/leave bot (`src/meet/bot.py`).
- Meet audio capture adapters (`src/meet/audio.py`).
- Meet runtime wiring to `RealtimeClient` (`src/meet/main.py`).

Not yet hardened for production:
- End-to-end reliability testing and preflight checks.
- Compliance controls (consent, retention, access policy).
- Official Google Meet media API path validation.

### Phase 3 (Discord)
Implemented:
- Discord bot with voice channel join/leave lifecycle (`src/discord/bot.py`).
- Discord audio capture/output adapters (`src/discord/audio.py`).
- Discord runtime wiring to `RealtimeClient` (`src/discord/main.py`).
- Bot commands: `!join`, `!leave`, `!status`, `!lang`.
- Translation text forwarding to Discord text channel.
- TTS speak-back into voice channel.

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| M1 Phase 1 realtime interpreter | DONE | Mic + device input + dynamic language routing |
| M2 Fallback interpreter path | DONE | WAV recording + transcription + translation |
| M3 Meet bot MVP wiring | DONE (internal) | Join + capture + realtime translation path exists |
| M4 Meet hardening and compliance gate | IN PROGRESS | Stability tests, policy controls, parser unification pending |
| M5 Discord bot MVP | DONE | Voice join + capture + realtime translation + text channel output |

## Known Implementation Caveats

- `app.py --mode meet-bot` does not expose the complete meet parser surface from `src/meet/main.py`; meet operations should currently use `python -m src.meet.main`.
- ScreenCaptureKit path (`--sck`) exists but is less validated than loopback-device capture.
- Fallback mode always persists WAV clips in `recordings/`.

## Resume Checklist

1. Use `python app.py --mode realtime` for core interpreter smoke tests.
2. Use `python app.py --mode realtime --input device --input-device <idx> --no-speaker` for loopback tests.
3. Use `python -m src.meet.main ...` for meet-bot tests.
4. Use `python app.py --mode discord` or `python -m src.discord.main` for Discord tests.
5. Track remaining hardening/compliance items in `docs/TASKS.md`.

## File Map

```text
brseAI/
├── app.py
├── README.md
├── requirements.txt
├── docs/
│   ├── architecture.md
│   ├── realtime_protocol.md
│   ├── security.md
│   ├── phase2_google_meet.md
│   ├── next_steps_google_meet.md
│   ├── TASKS.md
│   └── STATE.md
├── src/
│   ├── common/
│   ├── realtime/
│   ├── fallback/
│   ├── meet/
│   └── discord/
├── recordings/
└── logs/
```

## Change Log

- 2026-03-03: Phase 1 realtime + fallback interpreter path completed.
- 2026-03-03: Language routing and meeting-mode behavior added (`locked`/`auto`, pair filters).
- 2026-03-03: Device loopback input added for realtime (`--input device`).
- 2026-03-03: Meet bot MVP modules added (`src/meet/*`) and integrated.
- 2026-03-04: Documentation synchronized to current implementation and known limitations.
- 2026-03-08: Discord voice bot implemented (Phase 3: src/discord/*).
