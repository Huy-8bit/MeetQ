# TASKS

Implementation tracking aligned with current repository state.

## Completed

### TASK-01: Realtime Core Interpreter
**Status:** DONE
**Acceptance criteria:**
- [x] WebSocket realtime session established with OpenAI Realtime model.
- [x] Audio streamed as `input_audio_buffer.append` chunks.
- [x] Translated text streamed to terminal.
- [x] Ctrl+C shutdown path implemented.

### TASK-02: Realtime Voice Output + Barge-In
**Status:** DONE
**Acceptance criteria:**
- [x] `response.audio.delta` decoded and played when speaker is enabled.
- [x] `response.audio.done` triggers output flush.
- [x] New `speech_started` during assistant output sends `response.cancel`.
- [x] Player restart logic implemented for interruption.

### TASK-03: Input Abstraction and Device Loopback
**Status:** DONE
**Acceptance criteria:**
- [x] `AudioInput` abstraction exists.
- [x] `MicInput` and `DeviceLoopbackInput` implemented.
- [x] Realtime path accepts injected `AudioInput`.
- [x] CLI supports `--input`, `--input-device`, `--input-rate`, `--list-input-devices`.

### TASK-04: Language Routing Controls
**Status:** DONE
**Acceptance criteria:**
- [x] `--src`, `--tgt`, `--pairs`, `--meeting-mode` supported.
- [x] Auto-detect heuristic for `vi/en/ja` implemented.
- [x] Locked routing mode implemented.
- [x] Dynamic `session.update` on routing change implemented.

### TASK-05: Fallback Pipeline
**Status:** DONE
**Acceptance criteria:**
- [x] Fixed-length recording implemented.
- [x] WAV saved to `recordings/`.
- [x] OpenAI transcription + chat translation flow implemented.
- [x] CLI supports `--seconds`, model overrides, language flags.

### TASK-06: Meet Bot Join Lifecycle
**Status:** DONE (internal MVP)
**Acceptance criteria:**
- [x] Persistent-profile Chromium launch implemented.
- [x] Join button automation + retries implemented.
- [x] Waiting-room detection and timeout implemented.
- [x] Optional auto-leave timer implemented.

### TASK-07: Meet Audio Adapters
**Status:** DONE (internal MVP)
**Acceptance criteria:**
- [x] Loopback capture input adapter (`MeetAudioListenerInput`) implemented.
- [x] Virtual mic output adapter (`MeetAudioMicOutput`) implemented.
- [x] ScreenCaptureKit adapter (`SCKAudioInput`) present in code.
- [x] Device listing helper for meet mode implemented.

### TASK-08: Documentation Sync (current pass)
**Status:** DONE
**Acceptance criteria:**
- [x] README updated with runnable commands and accurate defaults.
- [x] Architecture/protocol/security docs updated to match code.
- [x] State/tasks docs updated with implemented vs pending work.

## Pending / Next

### TASK-09: Meet CLI Unification and Stability Fixes
**Status:** TODO
**Acceptance criteria:**
- [ ] `app.py --mode meet-bot` and `src/meet/main.py` expose consistent flag surface.
- [ ] Meet mode startup path works without attribute mismatches.
- [ ] End-to-end smoke run succeeds for join + translate + clean shutdown.

### TASK-10: Meet Speak-Back Validation
**Status:** TODO
**Acceptance criteria:**
- [ ] `--meet-mic-device` route verified in real meeting conditions.
- [ ] No local speaker leakage/feedback in speak-back mode.
- [ ] Barge-in behavior validated while speak-back is active.

### TASK-11: ScreenCaptureKit Hardening
**Status:** TODO
**Acceptance criteria:**
- [ ] `--sck` capture path validated on supported macOS versions.
- [ ] Error handling covers permission denial and capture startup failures.
- [ ] Documentation includes tested setup and fallback guidance.

### TASK-12: Reliability Test Matrix
**Status:** TODO
**Acceptance criteria:**
- [ ] Smoke scripts cover realtime mic/device/fallback/meet modes.
- [ ] Regression checklist executed for device index 0, sample-rate mismatch, reconnect behavior.
- [ ] Failure-mode outcomes documented (join timeout, no audio, auth failure).

### TASK-13: Privacy and Retention Controls
**Status:** TODO
**Acceptance criteria:**
- [ ] Participant notice/consent process documented for meet sessions.
- [ ] Retention policy for `recordings/` and transcripts approved.
- [ ] Logging redaction policy enforced for sensitive text.

### TASK-14: Discord Bot MVP
**Status:** DONE
**Acceptance criteria:**
- [x] Discord bot joins/leaves voice channels via `!join`/`!leave` commands.
- [x] Audio captured from voice channel via discord.py voice receive.
- [x] Audio piped to RealtimeClient for real-time translation.
- [x] Translated text posted to Discord text channel.
- [x] TTS speak-back into voice channel supported.
- [x] Auto-leave when all users leave the voice channel.
- [x] CLI support via `python app.py --mode discord`.

### TASK-15: Discord Bot Hardening
**Status:** TODO
**Acceptance criteria:**
- [ ] Slash command support (`/join`, `/leave`, `/lang`) alongside prefix commands.
- [ ] Translation text debouncing for high-frequency output.
- [ ] Voice disconnect reconnection handling.
- [ ] Multi-server concurrent session testing.
- [ ] Rate limit handling for Discord API calls.
