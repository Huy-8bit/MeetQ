# TASKS

Implementation tracking for core brseAI interpreter.

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

### TASK-06: Platform Code Cleanup
**Status:** DONE (2026-03-09)
**Acceptance criteria:**
- [x] Google Meet and Discord platform-specific code removed.
- [x] Dependencies cleaned (playwright, discord.py, PyNaCl, etc.).
- [x] Documentation updated to reflect core-only focus.
- [x] Tests cleaned and passing.

## Pending / Next

### TASK-07: Cross-Platform Testing
**Status:** TODO
**Acceptance criteria:**
- [ ] Smoke scripts cover realtime mic/device/fallback modes.
- [ ] Regression checklist executed for device index 0, sample-rate mismatch, reconnect behavior.
- [ ] Failure-mode outcomes documented (no audio, auth failure).
- [ ] Tests validated on macOS and Linux.

### TASK-08: Error Handling Improvements
**Status:** TODO
**Acceptance criteria:**
- [ ] Graceful handling of OpenAI API errors.
- [ ] Clear error messages for device access issues.
- [ ] Reconnection logic for dropped WebSocket connections.

### TASK-09: Performance Optimization
**Status:** TODO
**Acceptance criteria:**
- [ ] Audio buffer management optimized.
- [ ] Memory usage profiled and optimized.
- [ ] Latency measurements documented.

