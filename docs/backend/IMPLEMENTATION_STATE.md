# Backend Implementation State

## Last Updated

- Time: 2026-04-30T14:30:00+07:00
- Agent: Codex
- Branch: develop

## Current Mode

- CODE-ONLY
- Testing deferred: yes

---

## DONE THIS TURN: Mic Test + Translation Test Backend

### Architecture

**Mic test** — WebSocket only (no room join, no AI pipeline):

1. `POST /api/test/mic` → create session → returns `session_id` + `websocket.url`
2. FE connects `ws://host/ws/test/mic/{session_id}`
3. FE streams raw PCM16 binary frames
4. Server computes RMS + peak per chunk and emits `mic_test.level` events
5. Server emits `mic_test.silence` when RMS stays below threshold for >500 ms
6. FE or server can stop: `mic_test.stop` JSON → `mic_test.stopped` → close 1000

**Translation test** — REST create + WebSocket stream + OpenAI Realtime pipeline:

1. `POST /api/test/translation` → `{src_lang, tgt_lang}` → returns `session_id` + `websocket.url`
2. FE connects `ws://host/ws/test/translation/{session_id}`
3. FE streams raw PCM16 binary frames
4. Server pipes audio through `InterpreterRealtimeClient` in text-only mode (no LiveKit)
5. OpenAI VAD detects speech, transcribes, translates
6. Server emits `translation_test.partial` (incremental) and `translation_test.final` (per utterance)
7. Audio output: **text-only in this turn** — contract has reserved fields for future audio path

**Session store** — Redis, TTL 900 s, keys `test:mic:{id}` and `test:trans:{id}`, separate from room state.

### New Files

- `BE/server/gateway/test_session_store.py`
- `BE/server/gateway/api_test_sessions.py`
- `BE/server/gateway/ws_test_mic.py`
- `BE/server/gateway/ws_test_translation.py`
- `BE/server/interpreter/translation_test_client.py`

### Modified Files

- `BE/server/models.py` — `MicTestSession`, `TranslationTestSession`, `TestSessionStatus`, REST DTOs
- `BE/server/events.py` — `MIC_TEST_*`, `TRANSLATION_TEST_*` event type constants + `build_test_event()`
- `BE/server/gateway/app_state.py` — added `test_session_store` field
- `BE/server/gateway/main.py` — registered 3 new routers, initialized `TestSessionStore` in lifespan

### REST Contract

| Method | Path | Body | Success |
|--------|------|------|---------|
| `POST` | `/api/test/mic` | `{}` | `201 {session_id, status, created_at, expires_at, websocket}` |
| `DELETE` | `/api/test/mic/{session_id}` | — | `204` |
| `POST` | `/api/test/translation` | `{src_lang, tgt_lang}` | `201 {session_id, src_lang, tgt_lang, status, created_at, expires_at, websocket}` |
| `DELETE` | `/api/test/translation/{session_id}` | — | `204` |

### WebSocket Event Schema (FE-usable)

**Mic test** (all events carry `session_id`, `type`, `event_id`, `sent_at`):

```json
{ "type": "mic_test.started", "session_id": "ts_...", "sent_at": "...",
  "payload": { "session_id": "ts_...", "status": "active", "timestamp": "..." } }

{ "type": "mic_test.level", ...,
  "payload": { "session_id": "ts_...", "status": "active",
               "rms": 0.032, "peak": 0.045, "db": -29.8,
               "chunk_ms": 20.0, "timestamp": "..." } }

{ "type": "mic_test.silence", ...,
  "payload": { "session_id": "ts_...", "status": "active",
               "silence_ms": 600, "timestamp": "..." } }

{ "type": "mic_test.stopped", ...,
  "payload": { "session_id": "ts_...", "status": "stopped", "timestamp": "..." } }

{ "type": "mic_test.error", ...,
  "payload": { "session_id": "ts_...", "code": "...", "message": "...", "timestamp": "..." } }
```

**Translation test**:

```json
{ "type": "translation_test.started", ...,
  "payload": { "session_id": "ts_...", "src_lang": "vi", "tgt_lang": "ja",
               "status": "listening", "timestamp": "..." } }

{ "type": "translation_test.partial", ...,
  "payload": { "session_id": "ts_...", "src_lang": "vi", "tgt_lang": "ja",
               "source_text": "xin chào...", "translated_text": "こんにちは...",
               "is_final": false, "timestamp": "..." } }

{ "type": "translation_test.final", ...,
  "payload": { "session_id": "ts_...", "src_lang": "vi", "tgt_lang": "ja",
               "source_text": "Xin chào bạn.", "translated_text": "こんにちは。",
               "is_final": true, "timestamp": "..." } }

{ "type": "translation_test.error", ...,
  "payload": { "session_id": "ts_...", "code": "...", "message": "...", "timestamp": "..." } }
```

### State Lifecycle

Mic test: `created → active → stopped → (auto-expired 15 min)`

Translation test: `created → listening → translating → completed → (auto-expired 15 min)`

### Audio Output Policy (this turn)

Translation test delivers **text-only** translation. Audio output path is intentionally deferred.
Contract placeholder fields (`audio_track_name`, `audio_url`) are documented in ws_test_translation.py
comments so the contract is extensible without breaking FE in a future turn.

### Testing

Deferred per instruction. No runtime verification executed.

---

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
- Current objective: next turn should live-verify FE can render speaker-attributed source + translated transcript streams from the new websocket/schema path
- Files being edited:
  - `BE/server/models.py`
  - `BE/server/gateway/ws_endpoint.py`
  - `BE/server/gateway/event_consumer.py`
  - `BE/server/gateway/room_service.py`
  - `BE/server/gateway/room_store.py`
  - `BE/server/interpreter/event_publisher.py`
  - `BE/server/interpreter/room_manager.py`
  - `BE/server/interpreter/interpreter_client.py`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`

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
- `BE/server/gateway/room_store.py`
- `BE/server/interpreter/__init__.py`
- `BE/server/interpreter/livekit_runtime.py`
- `BE/server/interpreter/event_publisher.py`
- `BE/server/interpreter/meeting_config.py`
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
- `BE/server/gateway/event_consumer.py`
- `BE/server/gateway/livekit_tokens.py`
- `BE/server/gateway/room_service.py`
- `BE/server/gateway/ws_endpoint.py`
- `BE/server/interpreter/audio_input.py`
- `BE/server/interpreter/event_publisher.py`
- `BE/server/interpreter/interpreter_client.py`
- `BE/server/interpreter/meeting_config.py`
- `BE/server/interpreter/output_router.py`
- `BE/server/interpreter/room_manager.py`
- `BE/server/interpreter/livekit_runtime.py`
- `BE/server/models.py`
- `docs/backend/API_CONTRACT.md`
- `docs/backend/GATEWAY_DESIGN.md`

## Latest Fix
- Objective: expose live transcript events that FE can render directly by speaker, while preserving translated transcript personalization and backward compatibility.
- Root cause confirmed in code:
  - Gateway/FE contract only had listener-personalized translated transcript payloads, so web clients could not reliably render a generic "who is speaking now" transcript panel from websocket events alone.
  - Interpreter runtime published translated text after `input_audio_transcription.completed`, but it never emitted live source transcript partials from `conversation.item.input_audio_transcription.delta`.
  - Snapshot transcript storage was too minimal and non-personalized; it did not carry `kind`, `text`, `utterance_id`, nested `speaker`, or stable source-vs-translated semantics, and translated snapshots could leak transcripts intended for other listeners.
  - Speaker attribution existed implicitly in `RoomInterpreterManager`, but it was not normalized into a FE-usable transcript schema across interpreter publish -> Redis -> gateway consume -> websocket snapshot/live fan-out.
- Approach chosen:
  - Keep CLI/base runtime untouched; constrain the new speaker-transcript contract to `BE/server/interpreter/*`, `BE/server/gateway/*`, and shared Pydantic models.
  - Standardize transcript payload around FE-usable fields:
    - `transcript_id`
    - `utterance_id`
    - `kind = source | translated`
    - nested `speaker`
    - `text`
    - `src_lang`
    - `tgt_lang`
    - `is_final`
    - `created_at`
    - `audio_track_name`
  - Add live source transcript publishing from interpreter input transcription deltas/completions:
    - `conversation.item.input_audio_transcription.delta` -> `transcript.partial` with `kind = "source"`
    - `conversation.item.input_audio_transcription.completed` -> `transcript.final` with `kind = "source"`
  - Keep translated transcript listener-specific, but normalize it into the same schema with `kind = "translated"` and stable `utterance_id`.
  - Split transcript IDs by stream to avoid FE collisions when a client receives both source and translated text:
    - source: `{utterance_id}::source`
    - translated: `{utterance_id}::translated::{tgt_lang}`
  - Enrich speaker attribution at the interpreter publish source, not late in FE:
    - `RoomInterpreterManager` owns `speaker_id`, `display_name`, `src_lang`
    - `RedisEventPublisher` serializes nested `speaker`/`listener` metadata into each transcript payload
  - Personalize snapshot transcript history in gateway join / websocket snapshot:
    - always include source transcripts
    - only include translated transcripts targeted to the current participant
  - Preserve backward compatibility as much as possible by keeping legacy fields (`source_text`, `translated_text`, `listener`, `audio_track_name`) alongside the new direct-render fields.
- Files changed for this fix:
  - `BE/server/models.py`
  - `BE/server/gateway/event_consumer.py`
  - `BE/server/gateway/room_service.py`
  - `BE/server/gateway/ws_endpoint.py`
  - `BE/server/interpreter/event_publisher.py`
  - `BE/server/interpreter/interpreter_client.py`
  - `BE/server/interpreter/room_manager.py`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/GATEWAY_DESIGN.md`

## Transcript Schema
- Live websocket transcript events now expose a FE-usable shape for both `transcript.partial` and `transcript.final`:
  - `transcript_id`
  - `utterance_id`
  - `kind`
  - `speaker.participant_id`
  - `speaker.display_name`
  - `speaker.language`
  - `text`
  - `src_lang`
  - `tgt_lang`
  - `is_final`
  - `created_at`
  - `audio_track_name`
- Snapshot `recent_transcripts` now stores the same semantics in flattened + nested form:
  - flattened compatibility fields: `speaker_id`, `speaker_display_name`, `speaker_language`, `src_lang`, `source_text`, `translated_text`
  - direct-render fields: `kind`, `text`, `is_final`, `utterance_id`
  - nested compatibility fields: `speaker`, `listener`

## Speaker Attribution
- Speaker attribution is enriched at the interpreter source in `BE/server/interpreter/room_manager.py`, where each utterance is bound to:
  - `speaker_id`
  - `speaker_display_name`
  - participant-selected `src_lang`
- `BE/server/interpreter/event_publisher.py` serializes that attribution into both source and translated transcript events before they hit Redis.
- `BE/server/gateway/event_consumer.py` preserves the metadata end-to-end and uses `kind` to choose broadcast strategy:
  - source transcripts -> room broadcast
  - translated transcripts -> listener-specific websocket fan-out

## FE-Usable Fields
- FE can now render a live script panel directly from websocket payloads using:
  - `payload.speaker.display_name`
  - `payload.text`
  - `payload.kind`
  - `payload.transcript_id`
  - `payload.is_final`
  - `payload.created_at`
- If FE wants to correlate source and translated transcript for the same utterance, it can use `payload.utterance_id`.
- If FE wants translated-audio binding for the translated line, it can still use `payload.audio_track_name` and `payload.audio_output`.

## Backend Audio Model
- Room-level backend audio model now declared as `translated_audio_first`.
- Cross-language listener policy:
  - canonical remote audio path is the interpreter-published LiveKit track
  - transcript `audio_track_name` is the usable translated track when available
  - transcript/status `audio_output` declares the authoritative translated path even before the track is fully usable
- Same-language temporary policy:
  - `same_language_policy = "human_passthrough"`
  - backend does not spin up interpreter routing for same-language listeners in this turn
  - this is explicit in room `audio_routing` and event `audio_output`

## FE Contract Assumptions
- FE can treat room `audio_routing` as the canonical meeting audio policy.
- For cross-language listeners, FE should prefer interpreter audio over human remote audio.
- `transcript.partial/final.payload.audio_track_name` remains backward-compatible and only points to a usable translated track.
- `transcript.partial/final.payload.audio_output.track_name` is the deterministic canonical translated track name for that listener, even if publish is still warming up.
- `interpreter.status.payload.audio_output.tracks[]` provides the authoritative translated listener-track bindings for the current route.

## Deferred Testing
- Test execution has been fully deferred in this turn by instruction.
- The following tests/smoke tests must be run in the next turn:
  - 2-participant manual room verification: confirm FE receives room-broadcast source transcript partial/final with correct speaker attribution
  - Confirm the same utterance also produces listener-specific translated transcript partial/final with the same `utterance_id`
  - Confirm `transcript_id` stays stable across partial -> final for both source and translated streams
  - Confirm `room.snapshot` and join snapshot only include translated transcripts targeted to the current participant, while still including source transcripts for the room
  - Confirm existing FE does not break on source transcript events because legacy fields are still present
  - Confirm translated audio track still publishes and `audio_track_name` is preserved
  - `docker compose up redis livekit gateway interpreter`
  - `python -m server.interpreter.main`

## Verification Run This Turn
- Commands executed:
- none (code-only turn; verification intentionally deferred)
- Result:
  - no runtime verification executed
- Not executed in this turn:
  - `docker compose up ...`
  - real room join with two participants
  - confirmation from logs that tuned VAD/prompt reduce end-to-end latency and improve translation accuracy
  - live confirmation that capture failures, input overflow, and sender queue drops remain low in happy path

## Open Risks
- Multi-target-language fanout for one active speaker is still not implemented; current behavior is to fail clearly with `interpreter_unavailable` instead of routing to the wrong target.
- Source transcript partials currently assume OpenAI transcription deltas are append-only; if the upstream protocol emits corrective deltas, FE may need a smarter merge strategy in a later turn.
- `GET /api/rooms/{room_id}` is still an unpersonalized public snapshot, so translated transcripts there may include entries intended for other listeners. Personalized filtering is currently applied in join snapshot and websocket `room.snapshot`.
- Existing FE code still needs explicit adoption of the new authoritative fields (`text`, `kind`, `utterance_id`) to fully benefit from the normalized schema.
- FE has not yet been switched in this turn to actively suppress cross-language human audio playback; backend now publishes the canonical policy and metadata, but frontend enforcement still needs live verification / follow-up implementation.

## Resume Instructions
- Start with live verification of the new transcript schema on the meeting path, not CLI demo flow
- Bring up `docker compose up redis livekit gateway interpreter`
- Join 2 participants with different languages and confirm:
  - source transcript partial/final events arrive room-wide with correct `speaker.display_name`, `text`, `kind = source`, `transcript_id`, and `utterance_id`
  - translated transcript partial/final events arrive only to the target listener with `kind = translated`, `src_lang`, `tgt_lang`, and `audio_track_name`
  - join snapshot and websocket `room.snapshot` include source transcript history plus only the translated items targeted to the current participant
  - FE can replace partial -> final using stable `transcript_id`
- Then verify translated audio still matches the translated transcript line on `interp::{speaker_id}::{listener_id}::{src_lang}::{tgt_lang}`
