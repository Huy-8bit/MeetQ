# TASKS

Task breakdown for the realtime interpreter MVP.

---

## TASK-01: Planning + Skeleton Docs
**Status:** DONE
**Acceptance criteria:**
- [x] docs/TASKS.md exists with all tasks
- [x] docs/STATE.md exists with initial state and assumptions

---

## TASK-02: Common — Audio Capture Module
**Status:** DONE
**File:** `src/common/audio.py`
**Acceptance criteria:**
- [x] `list_input_devices()` returns formatted device list
- [x] `MicCapture` class opens sounddevice input stream at 16kHz or 24kHz, 16-bit PCM
- [x] Yields ~20ms chunks via queue
- [x] Supports specifying device by index
- [x] Handles callback errors gracefully

---

## TASK-03: Common — Logging Utilities
**Status:** DONE
**File:** `src/common/logging_utils.py`
**Acceptance criteria:**
- [x] Timestamped structured log lines
- [x] Console + optional file handler
- [x] Functions: `get_logger(name)`, convenience wrappers
- [x] No secrets leaked in log output

---

## TASK-04: Realtime — WebSocket Client
**Status:** DONE
**File:** `src/realtime/client.py`
**Acceptance criteria:**
- [x] Opens `wss://api.openai.com/v1/realtime?model=...`
- [x] Sends `session.update` on connect with VAD + translation instructions
- [x] Streams audio chunks via `input_audio_buffer.append`
- [x] Handles all relevant server events (speech_started, speech_stopped, text deltas, errors)
- [x] Reconnect retry with exponential backoff
- [x] Prints translation deltas to stdout (no extra text)
- [x] Ctrl+C clean shutdown

---

## TASK-05: Realtime — Main Entrypoint
**Status:** DONE
**File:** `src/realtime/main.py`
**Acceptance criteria:**
- [x] Parses CLI flags: --mic, --list-mics
- [x] Wires MicCapture -> RealtimeClient
- [x] Graceful shutdown on Ctrl+C

---

## TASK-06: Fallback — Pipeline
**Status:** DONE
**File:** `src/fallback/pipeline.py`
**Acceptance criteria:**
- [x] Records N seconds from mic (default 5–10s)
- [x] Saves to `recordings/` with timestamp filename
- [x] Calls OpenAI transcription API
- [x] Calls OpenAI chat API for translation (VI->EN or EN->VI auto-detect)
- [x] Returns final translation string

---

## TASK-07: Fallback — Main Entrypoint
**Status:** DONE
**File:** `src/fallback/main.py`
**Acceptance criteria:**
- [x] Parses --seconds, --mic, --list-mics
- [x] Runs fallback pipeline
- [x] Prints final translation clearly

---

## TASK-08: App — Top-Level CLI Entrypoint
**Status:** DONE
**File:** `app.py`
**Acceptance criteria:**
- [x] --mode realtime|fallback
- [x] --input-lang auto (default)
- [x] --output-lang auto (default)
- [x] --mic <index>
- [x] --list-mics
- [x] --seconds (for fallback)
- [x] Routes to correct entrypoint

---

## TASK-09: requirements.txt + README
**Status:** DONE
**Acceptance criteria:**
- [x] requirements.txt has all needed packages with minimum versions
- [x] README has quickstart, troubleshooting, env setup

---

## TASK-10: Bugfix — Realtime text not printing to terminal
**Status:** DONE
**File:** `src/realtime/client.py`
**Root cause:** `temperature: 0.3` was below the API minimum of 0.6, causing `session.update`
to be rejected. The session fell back to default config (audio modality active), so the server
streamed `response.audio.delta` instead of `response.text.delta`.

**Acceptance criteria:**
- [x] `temperature` set to `0.8` (>= 0.6 minimum)
- [x] `session.updated` log confirms config applied (no error after this fix)
- [x] `response.text.delta` events received and printed to stdout
- [x] No `unhandled_event` log spam for known audio/lifecycle events
- [x] Fallback mode unchanged

**Regression checklist:**
- [ ] Run `python app.py --mode realtime --mic <idx>`, speak Vietnamese → English appears
- [ ] Run `python app.py --mode realtime --mic <idx>`, speak English → Vietnamese appears
- [ ] Logs show `session.updated — config applied` (no temperature error)
- [ ] Ctrl+C exits cleanly
- [ ] `python app.py --mode fallback --seconds 5` still works independently

---

## TASK-11: Voice-to-voice upgrade (speaker playback + barge-in + debug mode)
**Status:** DONE
**Files changed:**
- `src/common/audio.py` — added `SpeakerPlayer`, `list_output_devices`, `print_output_devices`
- `src/realtime/client.py` — audio playback, barge-in, debug flag, [You]/[Interp] labels
- `src/realtime/main.py` — `--speaker`, `--no-speaker`, `--speaker-device`, `--list-speakers`, `--debug`
- `app.py` — same flags wired through top-level CLI
- `docs/realtime_protocol.md` — audio events, barge-in flow, format table

**Acceptance criteria:**
- [x] `response.audio.delta` PCM16 decoded and played through SpeakerPlayer in real time
- [x] `response.audio.done` triggers 50ms silence pad (flush) for clean tail
- [x] Barge-in: `speech_started` while assistant speaking → `response.cancel` + SpeakerPlayer.restart()
- [x] `--no-speaker` disables audio, falls back to text-only (modalities: ["text"])
- [x] `--speaker-device INDEX` selects output device
- [x] `--list-speakers` lists output devices and exits
- [x] `--debug` enables verbose event logs and prints input transcripts
- [x] Normal mode shows `[You] <transcript>` and `[Interp] <translation>` only
- [x] Fallback mode unchanged
- [x] Ctrl+C cleanly stops both mic and speaker streams

**Regression checklist:**
- [ ] Speak Vietnamese → terminal shows `[You] ...` then `[Interp] <English>`, audio plays
- [ ] Speak English → terminal shows `[You] ...` then `[Interp] <Vietnamese>`, audio plays
- [ ] Start speaking mid-response → previous audio stops, new turn begins
- [ ] `--no-speaker` → text still appears, no audio playback
- [ ] `--list-speakers` lists output devices
- [ ] `--debug` shows per-event log lines
- [ ] Ctrl+C exits without errors or hung threads

---

## TASK-12: Japanese + configurable language routing
**Status:** DONE
**Files changed:**
- `src/common/lang.py` (new) — language constants, heuristic detector, instruction builder, pair validator
- `src/realtime/client.py` — src/tgt/pairs/show_input params, auto-detection + sticky, session.update on lang change
- `src/realtime/main.py` — `--src`, `--tgt`, `--pairs`, `--show-input` flags
- `src/fallback/pipeline.py` — `src_lang`/`tgt_lang` params, dynamic prompt
- `src/fallback/main.py` — `--src`, `--tgt` flags
- `app.py` — all four flags wired through both modes

**Acceptance criteria:**
- [x] Japanese → English by default (src=auto detects ja via Unicode heuristic)
- [x] Vietnamese → English by default
- [x] English → Vietnamese by default
- [x] `--src ja --tgt vi` translates Japanese → Vietnamese
- [x] `--src vi --tgt ja` translates Vietnamese → Japanese (丁寧語 tone)
- [x] `--pairs "vi<->en"` blocks ja<->en routing
- [x] `--show-input` always prints [You] transcript
- [x] Sticky language: no flip-flop if heuristic uncertain (< 2 marker chars)
- [x] Fallback mode respects --src/--tgt for dynamic prompt
- [x] No extra commentary in output

---

## TASK-13: Meeting mode (--meeting-mode locked|auto)
**Status:** DONE
**Files changed:**
- `src/realtime/client.py` — `meeting_mode` param, `_routing_locked` flag, lock-on-first-detection logic, `[MeetingMode]` banner
- `src/realtime/main.py` — `--meeting-mode` flag
- `src/fallback/pipeline.py` — `meeting_mode` param, upfront prompt for locked+explicit, banner
- `src/fallback/main.py` — `--meeting-mode` flag
- `app.py` — flag wired through both modes
- `README.md` — new examples + flags table entry

**Acceptance criteria:**
- [x] `--meeting-mode locked --src ja --tgt en`: prints `[MeetingMode] locked | src=ja tgt=en` immediately; routing never changes
- [x] `--meeting-mode locked --src auto --tgt auto`: prints "waiting for first detection", locks on first confident transcript, prints confirmed lock line
- [x] After lock, further detect_lang calls are skipped (no `session.update` sent)
- [x] `--meeting-mode auto`: behavior unchanged from TASK-12 (sticky + dynamic session.update)
- [x] Fallback mode: `locked+explicit` builds prompt before recording; shows banner
- [x] `--debug` still logs detection attempts even after lock

---

## TASK-14: Phase 2 Documentation Package
**Status:** DONE
**Files changed:**
- `docs/phase2_google_meet.md`
- `docs/architecture.md`
- `docs/next_steps_google_meet.md`
- `docs/TASKS.md`
- `docs/STATE.md`

**Acceptance criteria:**
- [x] Phase 2 main spec exists with Path A and Path B
- [x] Path A capability statements include explicit uncertainty/depends-on-access notes
- [x] Path B includes fragility, ToS, and legal-review warnings
- [x] Architecture docs include `AudioInput` -> `MicInput`/`MeetInput` model
- [x] Mermaid diagrams added: architecture, phase2 dataflow, failure/retry
- [x] Operational considerations include latency, buffering, echo, failure modes, privacy

---

## TASK-15: AudioInput Interface + DeviceLoopbackInput (Phase 2 MVP)
**Status:** DONE
**Files changed:**
- `src/common/audio.py` — added `AudioInput` ABC, `AudioMetadata` dataclass, `MicInput`, `DeviceLoopbackInput`
- `src/realtime/client.py` — accepts `audio_input: AudioInput` param; `_send_audio` uses it instead of hardcoded `MicCapture`
- `src/realtime/main.py` — new flags: `--input {mic,device}`, `--input-device`, `--input-rate`, `--list-input-devices`; safety speaker-off default for device input; echo warning
- `app.py` — same new flags wired through top-level CLI; fallback uses `--input-rate` / `--input-device`

**Acceptance criteria:**
- [x] `AudioInput` ABC with `start()`, `stream_frames()`, `stop()`, `metadata` in code
- [x] `MicInput` implements `AudioInput` (replaces MicCapture internally; MicCapture kept as legacy alias)
- [x] `DeviceLoopbackInput` implements `AudioInput` — captures from any sounddevice input (BlackHole, Loopback, VB-Cable, Stereo Mix); mixes stereo→mono automatically
- [x] `RealtimeClient` accepts `audio_input: AudioInput`; falls back to `MicInput` when not provided
- [x] `--input=mic` (default): same behavior as before
- [x] `--input=device --input-device <idx>`: routes meeting audio from virtual device into pipeline
- [x] `--input=device` defaults speaker OFF (echo prevention); explicit `--speaker` overrides
- [x] Warning printed when speaker is ON with device input
- [x] `--list-input-devices` lists all sounddevice inputs (replaces `--list-mics`; legacy `--list-mics` kept)
- [x] `--input-rate` sets capture sample rate (replaces `--sample-rate`; legacy `--sample-rate` kept for fallback mode)
- [x] Existing mic realtime mode unchanged (manual smoke test: `python app.py --mode realtime`)

---

## TASK-16: Full Meet Interpreter Bot MVP (Path B Internal)
**Status:** DONE
**Files changed:**
- `src/meet/__init__.py` (new)
- `src/meet/selectors.py` (new) — resilient DOM selector map; all Meet selectors in one place
- `src/meet/bot.py` (new) — `MeetBot` Playwright joiner; handles lobby/waiting-room/camera-off/barge-in
- `src/meet/audio.py` (new) — `MeetAudioListenerInput` (captures loopback device), `MeetAudioMicOutput` (plays TTS into virtual mic device)
- `src/meet/main.py` (new) — `meet-bot` entrypoint; wires bot + audio + interpreter
- `app.py` — added `--mode meet-bot` + all meet-bot flags
- `requirements.txt` — added `playwright>=1.44.0`
- `README.md` — new "Google Meet Bot Mode" section

**Acceptance criteria:**
- [x] `python app.py --mode meet-bot --meeting-url <url> --profile-dir <path>` joins meeting via Playwright
- [x] `--setup-profile` opens browser for first-time Google sign-in (no meeting join)
- [x] Handles waiting room: polls for admission up to `--join-timeout-seconds`
- [x] Camera OFF automatically in pre-join lobby
- [x] `MeetAudioListenerInput` captures from `--meet-speaker-device` (loopback/virtual input)
- [x] `MeetAudioMicOutput` plays TTS into `--meet-mic-device` (virtual output → Chrome mic)
- [x] `--meet-mic-device` omitted → listen-only mode (no bot TTS injected)
- [x] Safety: `--meet-sample-rate` default 48000 matches typical virtual device native rate
- [x] `[MeetBot]` status banners: joined, waiting room, admitted, stopped
- [x] `--debug` enables verbose Playwright console + audio event logs
- [x] Ctrl+C stops interpreter, audio devices, and Playwright browser cleanly
- [x] `--list-audio-devices` lists all I/O devices
- [x] `--leave-after-minutes` auto-leaves after N minutes
- [x] Existing mic realtime mode unchanged
- [x] README updated with prerequisites, virtual device setup, first-time login, examples, troubleshooting

**Regression checklist:**
- [ ] `python app.py --mode realtime` — mic realtime unchanged
- [ ] `python app.py --mode meet-bot --setup-profile --profile-dir ~/.brseai_profile` — browser opens Google sign-in
- [ ] `python app.py --mode meet-bot --meeting-url <url> --profile-dir <path> --meet-speaker-device <idx>` — bot joins, translations printed
- [ ] Bot waits for admission when in waiting room
- [ ] Ctrl+C exits cleanly without hung browser or audio threads
- [ ] `--list-audio-devices` shows all I/O devices with indexes

**Safety note:**
Internal testing only. Do NOT deploy to third-party meetings without participant
consent and legal/compliance review. See `docs/phase2_google_meet.md`.

---

## TASK-17: Official Path A Feasibility Gate
**Status:** PLANNED
**Scope:** Validate whether official Google Meet media integration is available for this org and what operations are permitted.

**Acceptance criteria:**
- [ ] Access prerequisites documented (admin, policy, org approvals)
- [ ] Confirmed capability matrix captured (receive vs send/inject)
- [ ] Any unsupported/uncertain capability explicitly marked in docs
- [ ] Go/no-go decision documented with stakeholders

---

## TASK-18: Privacy, Consent, and Retention Controls
**Status:** PLANNED
**Scope:** Operationalize compliance requirements for meeting capture.

**Acceptance criteria:**
- [ ] Participant notification text approved and documented
- [ ] Transcript storage policy (location, retention, deletion) approved
- [ ] Log redaction rules implemented and verified
- [ ] Access control model for transcript visibility documented

---

## TASK-19: Pilot Readiness Runbook
**Status:** PLANNED
**Scope:** Prepare reliable operations for controlled pilot.

**Acceptance criteria:**
- [ ] Failure playbooks exist for join failure, no-audio, permission errors, and reconnect loops
- [ ] Latency SLO and alert thresholds documented
- [ ] Echo/feedback validation checklist added to preflight
- [ ] Operator checklist validated in at least one rehearsal session

---
