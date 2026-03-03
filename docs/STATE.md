# STATE

## Current Status
Meeting mode added. --meeting-mode locked (default) fixes routing after first detection;
--meeting-mode auto preserves dynamic switching. All modes: realtime + fallback.

## Key Assumptions / Decisions
- Python 3.10+
- Audio: sounddevice + numpy, 16kHz PCM16
- Chunk size: ~20ms = 320 samples at 16kHz
- Realtime transport: raw websockets (not openai SDK beta realtime) for full control
- Session instructions enforce VI<->EN translation-only output
- Fallback uses openai.audio.transcriptions.create + openai.chat.completions.create
- OPENAI_API_KEY from env only; no hardcoded secrets
- Logs: timestamped to stderr; translation output to stdout (clean, pipeable)
- Reconnect: up to 5 attempts with exponential backoff
- Recordings saved to recordings/ only in fallback mode

## File Map
```
brseAI/
├── app.py                        Main CLI entrypoint
├── requirements.txt              Python deps
├── README.md                     Quickstart + troubleshooting
├── .env.example                  Template env file
├── docs/
│   ├── TASKS.md                  Task list (this project)
│   ├── STATE.md                  This file
│   ├── architecture.md           Mermaid diagram
│   ├── realtime_protocol.md      Protocol event reference
│   ├── security.md               Security notes
│   └── next_steps_google_meet.md Google Meet extension plan
├── src/
│   ├── common/
│   │   ├── audio.py              MicCapture, list_input_devices
│   │   └── logging_utils.py      Timestamped logger
│   ├── realtime/
│   │   ├── client.py             RealtimeClient (WebSocket)
│   │   └── main.py               Realtime entrypoint
│   └── fallback/
│       ├── pipeline.py           Record + transcribe + translate
│       └── main.py               Fallback entrypoint
├── recordings/                   WAV clips (fallback mode)
└── logs/                         Log files (optional)
```

## How To Resume
1. Read docs/STATE.md (this file) and docs/TASKS.md.
2. Find first unchecked task in TASKS.md.
3. Implement it, then update STATE.md.

## Bug Fix: Realtime text not printing (2026-03-03)

### Symptoms
- `response.audio.delta` events received — no `response.text.delta` events.
- Nothing printed to terminal after speaking.
- Server error: `session.temperature` below minimum value.

### Root Cause
1. **Temperature `0.3` rejected** — Realtime API requires `temperature >= 0.6`. The
   `session.update` was rejected, so the session kept its default config which includes
   audio output modality (`["text", "audio"]`).
2. **Audio modality active** — Because session config was not applied, the server streamed
   `response.audio.delta` (audio bytes) instead of `response.text.delta`.
3. **No text events** — Our handler for `response.text.delta` never fired. Terminal stayed empty.

### Fix (src/realtime/client.py)
- `temperature`: `0.3` → `0.8` (Realtime API minimum is `0.6`)
- Added explicit no-op handlers for `response.audio.delta`, `response.audio.done`,
  `response.audio_transcript.done`, `conversation.item.created`, `rate_limits.updated`
  so they don't appear as `unhandled_event` noise in logs.
- `modalities: ["text"]` was already correct — it now takes effect since temperature is valid.

## Log
- 2026-03-03: Repo scaffold existed (docs + empty src). No application code.
- 2026-03-03: TASK-01 done: TASKS.md + STATE.md created.
- 2026-03-03: TASK-02 done: src/common/audio.py implemented.
- 2026-03-03: TASK-03 done: src/common/logging_utils.py implemented.
- 2026-03-03: TASK-04 done: src/realtime/client.py implemented.
- 2026-03-03: TASK-05 done: src/realtime/main.py implemented.
- 2026-03-03: TASK-06 done: src/fallback/pipeline.py implemented.
- 2026-03-03: TASK-07 done: src/fallback/main.py implemented.
- 2026-03-03: TASK-08 done: app.py implemented.
- 2026-03-03: TASK-09 done: requirements.txt + README updated.
- 2026-03-03: MVP COMPLETE. All tasks done.
- 2026-03-03: BUGFIX done: temperature 0.3→0.8, audio event no-ops added. Text now prints.
- 2026-03-03: TASK-11 done: Voice-to-voice upgrade — SpeakerPlayer, barge-in, --debug, [You]/[Interp] labels.
- 2026-03-03: TASK-12 done: Japanese + language routing — src/common/lang.py, --src/--tgt/--pairs/--show-input.
- 2026-03-03: TASK-13 done: Meeting mode — --meeting-mode locked|auto, routing lock, [MeetingMode] banner.
