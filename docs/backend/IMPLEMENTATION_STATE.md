# Backend Implementation State

## Last Updated
- Time: 2026-04-29T23:18:13+07:00
- Agent: Codex
- Branch: main

## Current Mode
- CODE-ONLY
- Testing deferred: yes

## Completed Runtime Work
- [x] FND-001 - Platform Dependency And Env Scaffolding
- [x] FND-002 - Shared Server Package
- [x] FND-003 - Test Bootstrap And Fixtures (Testing deferred)
- [x] GTW-001 - Room JWT Auth And LiveKit Token Builder
- [x] GTW-002 - Redis Room Store
- [x] GTW-003 - Room Service Domain Logic
- [x] GTW-004 - REST Routes
- [x] GTW-005 - WebSocket Hub And Endpoint
- [x] GTW-006 - Interpreter Event Consumer
- [x] INT-001 - LiveKit Room Runtime
- [x] INT-002 - LiveKitAudioInput Adapter
- [x] INT-003 - Gateway Event Publisher
- [x] INT-004 - Room Interpreter Manager
- [x] INT-005 - Redis Interpreter Daemon
- [x] INT-006 - Interpreter Entrypoint
- [x] Infra configuration (`docker-compose.yml`, `ops/livekit/livekit.yaml`)

## In Progress
- [ ] Deferred verification only
- Current objective: next turn should run end-to-end LiveKit/OpenAI verification for deterministic meeting routing plus translated voice publish path
- Files being edited:
  - `BE/server/interpreter/interpreter_client.py`
  - `BE/server/interpreter/audio_input.py`
  - `BE/server/interpreter/output_router.py`
  - `BE/server/interpreter/room_manager.py`

## Remaining Runtime Work
- none

## Files Created
- `docker-compose.yml`
- `ops/livekit/livekit.yaml`
- `BE/server/gateway/__init__.py`
- `BE/server/gateway/app_state.py`
- `BE/server/gateway/auth.py`
- `BE/server/gateway/livekit_tokens.py`
- `BE/server/gateway/room_store.py`
- `BE/server/gateway/room_service.py`
- `BE/server/gateway/api_health.py`
- `BE/server/gateway/api_rooms.py`
- `BE/server/gateway/dependencies.py`
- `BE/server/gateway/main.py`
- `BE/server/gateway/ws_hub.py`
- `BE/server/gateway/ws_endpoint.py`
- `BE/server/gateway/event_consumer.py`
- `BE/server/interpreter/__init__.py`
- `BE/server/interpreter/livekit_runtime.py`
- `BE/server/interpreter/event_publisher.py`
- `BE/server/interpreter/output_router.py`
- `BE/server/interpreter/room_manager.py`
- `BE/server/interpreter/daemon.py`
- `BE/server/interpreter/main.py`

## Files Modified
- `BE/requirements.txt`
- `BE/.env.example`
- `BE/.dockerignore`
- `BE/.gitignore`
- `BE/Dockerfile`
- `BE/README.md`
- `BE/server/config.py`
- `BE/server/gateway/livekit_tokens.py`
- `BE/server/interpreter/audio_input.py`
- `BE/server/interpreter/interpreter_client.py`
- `BE/server/interpreter/output_router.py`
- `BE/server/interpreter/room_manager.py`
- `BE/server/interpreter/livekit_runtime.py`

## Latest Fix
- Objective: fix Meeting Platform interpreter runtime so browser listeners receive stable translated transcript events plus usable translated LiveKit audio, without falling back to CLI auto-lock behavior.
- Root cause confirmed in code:
  - `BE/server/interpreter/interpreter_client.py` previously forced `enable_speaker=False`, while `BE/src/realtime/client.py` used that flag to decide whether OpenAI should emit audio; this was already fixed by overriding interpreter session setup to still request `modalities=["text","audio"]` while keeping local speaker playback disabled.
  - `BE/server/interpreter/room_manager.py` still routed meeting sessions like CLI mode with `src_lang="auto"` semantics, so speaker source language was inferred/locked heuristically instead of using room participant state.
  - The same runtime pinned an old `target_lang` and logged "keeping existing runtime until media reconnect", which silently preserved wrong routing after participant language changes.
  - `BE/server/interpreter/output_router.py` built interpreter track names from runtime `src_lang`; when that value was `"auto"`, FE track parsing ignored the audio track because FE only accepts `vi|en|ja`.
  - `BE/server/interpreter/output_router.py` could still capture into stale/unpublished LiveKit audio sources during listener remove, late audio delta arrival, or track reset races, producing `InvalidState - failed to capture frame`.
  - `BE/server/interpreter/room_manager.py` started audio ingestion too early relative to the realtime websocket sender path, and `BE/server/interpreter/audio_input.py` logged a warning for every overflowed chunk, creating heavy `Audio buffer full ... dropping oldest chunk` spam.
- Approach chosen:
  - Keep CLI/base runtime untouched in `BE/src/`; constrain fixes to `BE/server/interpreter/*`.
  - Treat meeting runtime as deterministic routing: speaker `src_lang` now comes directly from participant language in room state, and target language comes from active listeners with a different concrete language.
  - Recompute routing immediately on participant join, leave, or language update; if `(speaker, src_lang, tgt_lang)` changes, rebuild router state and push a fresh interpreter `session.update` immediately instead of waiting for media reconnect.
  - Fail clearly for unsupported multi-target cases in this turn instead of silently pinning the wrong target; publish interpreter error/status instead of routing incorrectly.
  - Only expose `audio_track_name` after the LiveKit track is actually published and usable; transcript partial/final payloads still flow even if voice publish fails, and track failures publish explicit `interpreter.error` plus `interpreter.status=error`.
  - Harden `OutputRouter` against late deltas and teardown races by tracking active listener states, skipping capture on stale/unpublished tracks, clearing queues on barge-in, and recreating listener tracks on capture failure.
  - Delay `LiveKitAudioInput.start()` until the base realtime sender thread starts, keep the underlying `AudioStream` alive across routing-only reconfiguration, and throttle overflow warnings to interval-based summaries instead of per-chunk spam.
- Files changed for this fix:
  - `BE/server/interpreter/interpreter_client.py`
  - `BE/server/interpreter/audio_input.py`
  - `BE/server/interpreter/output_router.py`
  - `BE/server/interpreter/room_manager.py`

## Deferred Testing
- Test execution has been fully deferred in this turn by instruction.
- The following tests/smoke tests must be run in the next turn:
  - 2-participant manual room verification: confirm translated transcript and translated LiveKit audio track are both delivered to the listener in a `vi <-> en` or `vi <-> ja` room
  - Listener language change verification: confirm runtime rebuild updates `target_lang` immediately and no longer logs target pinning until reconnect
  - Capture lifecycle verification: confirm no `InvalidState - failed to capture frame` appears in normal happy path
  - Backpressure verification: confirm `Audio buffer full ...` warnings are rare or absent in normal room startup
  - `cd BE && PYTHONPATH=. pytest -q tests/test_interpreter_audio_adapter.py`
  - `cd BE && pytest tests/`
  - `docker compose config`
  - `docker compose up redis livekit gateway interpreter`
  - `python -m server.interpreter.main`
  - Docker Compose bring-up and health checks.

## Verification Run This Turn
- Commands executed:
  - `python3 -m py_compile BE/server/interpreter/interpreter_client.py BE/server/interpreter/output_router.py BE/server/interpreter/room_manager.py BE/server/interpreter/audio_input.py`
- Result:
  - Python syntax check passed for modified interpreter files
- Not executed in this turn:
  - `docker compose up ...`
  - real room join with two participants
  - confirmation from logs that translated transcript/audio reaches FE end-to-end
  - live confirmation that `InvalidState` capture failures and input buffer overflow warnings are gone in happy path

## Open Risks
- Multi-target-language fanout for one active speaker is still not implemented; current behavior is to fail clearly with `interpreter_unavailable` instead of routing to the wrong target.
- The no-close stream reuse path in `LiveKitAudioInput.stop(close_stream=False)` now supports routing-only runtime rebuilds, but it still needs live validation against repeated participant language flips.
- `InterpreterRealtimeClient` now has a deterministic meeting path and a CLI-style auto path in the same wrapper; live verification is still needed to confirm no unexpected regression in reconnect/barging behavior.
- `OutputRouter` now recreates listener tracks on capture failure, but the exact recovery behavior under real LiveKit disconnect/reconnect timing remains unverified in this turn.

## Resume Instructions
- Start with live verification of the deterministic meeting path, not CLI demo flow
- Bring up `docker compose up redis livekit gateway interpreter`
- Join 2 participants with different languages and confirm:
  - transcript partial/final events appear in FE with concrete `speaker.source_language`
  - FE receives/picks up `interp::{speaker_id}::{listener_id}::{src_lang}::{tgt_lang}` audio tracks where `src_lang` and `tgt_lang` are concrete `vi|en|ja`
  - listener hears translated voice on browser
- Then change one listener language and confirm backend rebuilds routing immediately instead of keeping the old target until media reconnect
- If voice is still missing, inspect interpreter logs for `response.audio.delta` / `response.audio.done`, then inspect LiveKit publish logs for listener track resets or capture failures before changing routing logic again
