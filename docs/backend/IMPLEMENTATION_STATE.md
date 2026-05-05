# Backend Implementation State

## Turn Update: 2026-05-06 BRSE Interpreter-Like Public Relay Policy

- Time: 2026-05-06T00:00:00+07:00
- Mode: CODE-ONLY
- Status: implemented
- Testing deferred: full test suite not run, per instruction

### Objective

Improve BRSE relay runtime behavior so public output behaves like a pragmatic
meeting interpreter instead of a transcript narrator. Preserve current room,
LiveKit, Gateway, chat, screen share, expiry, persistence, and silent-listener
flows while tightening only backend/runtime/AI behavior paths.

### Read Status

- Read required docs:
  - `docs/backend/README.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
- Read required runtime files:
  - `BE/server/service/brain_runtime/room_manager.py`
  - `BE/server/service/media/output_router.py`
  - `BE/server/service/media/livekit_runtime.py`
  - `BE/server/service/media/audio_input.py`
  - `BE/server/brain/realtime/interpreter_client.py`
  - `BE/server/brain/realtime/session_config.py`
  - `BE/server/brain/realtime/source_policy.py`
  - `BE/server/brain/prompts/language.py`
- Related files read:
  - `BE/server/service/brain_runtime/events.py`
  - `BE/server/service/gateway/event_consumer.py`

### Initial Trace

- Source transcript capture is already separated from relay publication at the
  room manager / gateway boundary.
- Current relay approval is still eager once a source final passes basic
  transcript validation.
- Existing overlap summary fallback feeds speaker-labelled snippets into the
  model, which can encourage narrator-style output.
- Current prompt forbids labels, but it does not strongly teach public
  usefulness, timing, or interpreter silence as a valid action.

### Root Cause / Hypothesis

- BRSE was source-grounded, but the relay path treated most valid transcript
  finals as public relay candidates. That made the runtime too eager in normal
  meeting flow.
- The model instructions focused on translation fidelity and anti-hallucination,
  but not strongly enough on interpreter pragmatics: when to stay silent, when
  not to interrupt, and how to avoid narrator-style openings.
- Overlap fallback passed speaker-labelled snippets into the summary request,
  which increased the chance of output that sounds like "A said / B said" rather
  than a natural relay.
- Public audio was streamed as soon as response audio arrived, so prompt-only
  protection was weak against narrator-style response openings.

### Runtime / Prompt Changes

- Added explicit interpreter mindset instructions:
  - BRSE is not a narrator, meeting-minute bot, MC, or transcript reader.
  - Output is direct relay content only, not "who said what" commentary.
  - Silence is valid when content is incomplete, low-value, obvious, or poorly
    timed.
- Added pragmatic public relay policy on top of existing source validation:
  - relay only when there is a target-language audience.
  - suppress tiny acknowledgements, filler-like turns, short low-signal turns,
    incomplete fragments, stale queued turns, and chaotic literal relays.
  - preserve source transcript capture even when public relay is suppressed.
- Added output text/audio gate:
  - relay audio is briefly held until initial relay text passes the public text
    gate.
  - narrator-style openings such as name/pronoun + "said/is saying/discussing"
    are rejected and audio buffer is cleared before public playback.
  - held audio is released once the opening is safe, preserving single-speaker
    happy path with minimal added delay.
- Timing updated:
  - server VAD silence duration moved from 1000ms to 1150ms to reduce early
    turn cuts.
  - stale relay starts are suppressed after a short freshness window.
- Overlap behavior updated:
  - normal literal relay from secondary overlapped speakers is suppressed unless
    the runtime enters summary fallback.
  - chaos fallback prompt no longer includes participant names and explicitly
    asks for a short interpreter-style relay, not speaker-by-speaker narration.
- Anti-hallucination preserved:
  - relay and summary still originate only from completed, validated source
    transcripts.
  - prompt still forbids invented facts, decisions, owners, deadlines, causes,
    risks, and next steps.

### Observability

- Logs now distinguish:
  - public relay approved
  - public relay suppressed with reason and signal
  - stale public relay suppressed
  - relay output held for more opening context
  - narrator-style relay rejected
  - public audio held/released/rejected
  - overlap summary fallback selected

### Files Modified

- `BE/server/brain/realtime/source_policy.py`
- `BE/server/brain/realtime/session_config.py`
- `BE/server/brain/realtime/interpreter_client.py`
- `BE/server/service/brain_runtime/room_manager.py`
- `BE/server/service/media/output_router.py`
- `docs/backend/IMPLEMENTATION_STATE.md`

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added, per instruction.
- Existing tests not modified.
- Lightweight checks run:
  - `PYTHONPATH=BE python -m py_compile BE/server/brain/realtime/source_policy.py BE/server/brain/realtime/session_config.py BE/server/brain/realtime/interpreter_client.py BE/server/service/media/output_router.py BE/server/service/brain_runtime/room_manager.py`
  - `git diff --check -- BE/server/brain/realtime/source_policy.py BE/server/brain/realtime/session_config.py BE/server/brain/realtime/interpreter_client.py BE/server/service/media/output_router.py BE/server/service/brain_runtime/room_manager.py docs/backend/IMPLEMENTATION_STATE.md`

---

## Turn Update: 2026-05-05 BRSE Silent Listener Mode

- Time: 2026-05-05T00:00:00+07:00
- Mode: CODE-ONLY
- Testing deferred: full test suite not run, per instruction

### Objective

Add backend/runtime support for a BRSE silent listener summary mode. In this
mode BRSE runtime still joins and listens to meeting audio, source transcript
capture remains active for post-meeting summary, but BRSE does not publish or
relay AI audio back into the LiveKit room.

### Read Status

- Read required docs:
  - `docs/backend/README.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/API_CONTRACT.md`
- Read required backend/runtime files:
  - `BE/server/meeting_modes.py`
  - `BE/server/models.py`
  - `BE/server/service/gateway/api_rooms.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/service/gateway/room_store.py`
  - `BE/server/service/brain_runtime/daemon.py`
  - `BE/server/service/brain_runtime/room_manager.py`
  - `BE/server/service/media/livekit_runtime.py`
  - `BE/server/service/media/output_router.py`
  - `BE/server/brain/realtime/interpreter_client.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/service/gateway/meeting_summary_service.py`
  - `BE/server/brain/meeting_summary.py`
  - `BE/server/service/persistence/room_history.py`

### Strategy Locked

- Add explicit room-level `brse_mode: "relay" | "silent_summary"` while
  preserving `brse_enabled` as the runtime gate.
- Keep semantics distinct:
  - `brse_enabled=false`: no BRSE runtime.
  - `brse_enabled=true`, `brse_mode="relay"`: existing production relay behavior.
  - `brse_enabled=true`, `brse_mode="silent_summary"`: runtime listens and
    captures source transcripts, but output relay is suppressed.
- Silent mode will be supported at room creation/runtime start. Live switching
  between relay and silent modes remains deferred unless the current path needs
  a small preservation fix.

### Final Sync

- Room config/state:
  - `CreateRoomRequest` now accepts additive `brse_mode`, defaulting to `relay`.
  - Room state, create/join/snapshot responses, Mongo archive docs, and summary
    source room metadata now carry `brse_mode`.
  - `meeting_mode` is derived as `brse_relay` for relay and
    `brse_silent_summary` for silent summary.
  - `brse_enabled=false` remains no-BRSE/no-runtime mode.
- Silent listener behavior:
  - Interpreter daemon still spawns a room manager when `brse_enabled=true`,
    including `brse_mode=silent_summary`.
  - LiveKit runtime still joins the room and subscribes to human microphone
    audio tracks.
  - The virtual BRSE participant metadata marks `publishes_audio=false` and
    `subscribes_human_audio=true` in silent mode.
- Relay suppression strategy:
  - Silent mode sets the internal LiveKit token `can_publish=false`.
  - `OutputRouter` gets an explicit `output_enabled` gate and does not create,
    publish, capture, flush, or unpublish relay audio tracks when disabled.
  - `InterpreterRealtimeClient` runs with `request_audio_output=false` and
    silent listener instructions.
  - Room manager does not approve validated source transcript turns for relay
    response creation in silent mode, so BRSE relay text/audio is not generated
    for the meeting.
- Transcript/source capture behavior:
  - Valid source transcript finals are still published internally, appended to
    Redis, and persisted to Mongo for summary evidence.
  - Gateway suppresses websocket fan-out for transcript partial/final events in
    silent mode.
  - Gateway drops any non-source transcript event that reaches it while the room
    is in silent mode, preventing accidental relay text from entering archive.
  - REST/join snapshots hide recent transcripts for silent rooms; the source
    archive remains available to summary generation.
- Summary integration strategy:
  - Existing post-meeting summary trigger/path is reused.
  - Silent mode contributes source transcript lines through `room_messages` in
    Mongo; summary collection reads the same archived source data and records
    `brse_mode` in source room metadata.
  - Summary remains source-grounded and can be skipped if there is not enough
    captured meeting content.
- Live toggle:
  - Existing enable/disable BRSE toggle remains supported and preserves the
    stored `brse_mode`.
  - Live switching between `relay` and `silent_summary` is not exposed yet and
    is deferred.
- Files modified:
  - `BE/server/meeting_modes.py`
  - `BE/server/models.py`
  - `BE/server/service/gateway/api_rooms.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/service/gateway/room_store.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/service/gateway/livekit_tokens.py`
  - `BE/server/service/brain_runtime/daemon.py`
  - `BE/server/service/brain_runtime/room_manager.py`
  - `BE/server/service/brain_runtime/events.py`
  - `BE/server/service/media/livekit_runtime.py`
  - `BE/server/service/media/output_router.py`
  - `BE/server/brain/realtime/interpreter_client.py`
  - `BE/server/brain/realtime/session_config.py`
  - `BE/server/service/persistence/room_history.py`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/README.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Verification:
  - Full test suite not run, per CODE-ONLY instruction.
  - New tests not added.
  - Existing tests not modified.
  - Lightweight checks run:
    - `PYTHONPATH=BE python -m py_compile BE/server/meeting_modes.py BE/server/models.py BE/server/service/gateway/api_rooms.py BE/server/service/gateway/room_service.py BE/server/service/gateway/room_store.py BE/server/service/gateway/event_consumer.py BE/server/service/gateway/livekit_tokens.py BE/server/service/brain_runtime/daemon.py BE/server/service/brain_runtime/room_manager.py BE/server/service/brain_runtime/events.py BE/server/service/media/livekit_runtime.py BE/server/service/media/output_router.py BE/server/brain/realtime/interpreter_client.py BE/server/brain/realtime/session_config.py BE/server/service/persistence/room_history.py`
    - `git diff --check` on touched backend/docs files

## Turn Update: 2026-05-05 Post-Meeting Summary

- Time: 2026-05-05T00:00:00+07:00
- Mode: CODE-ONLY
- Testing deferred: full test suite not run, per instruction

### Objective

Add an additive backend/runtime/persistence path for post-meeting summary after
the meeting ends, without changing live room, relay, chat, expiry, or Redis hot
state behavior.

### Read Status

- Read required docs:
  - `docs/backend/README.md`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
- Read required runtime/persistence files:
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/service/gateway/room_store.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/service/persistence/room_history.py`
  - `BE/server/models.py`
  - `BE/server/brain/*`
  - `BE/server/config.py`
  - `.env.example`
  - `BE/.env.example`
  - `docker-compose.yml`
  - `docker-compose.prod.yml`

### Trigger Strategy

- Summary generation is post-meeting only.
- Triggers are deterministic terminal archive paths:
  - participant cleanup marks the room `empty` when the last human participant leaves.
  - scheduled expiry marks the room `expired` at `expires_at`.
  - join/websocket rejection for already-expired rooms also archives expiry and requests summary.
- The trigger runs in background side-effect tasks after room lifecycle archival, so leave/join/ws
  shutdown paths are not blocked by the model call.
- Summary creation is idempotent by unique `meeting_summaries.room_id`; duplicate terminal
  triggers return without regenerating.

### Source Data Strategy

- Summary generation reads durable Mongo archive data, not ad hoc live state:
  - `rooms` for metadata, lifecycle, languages, duration, participant totals.
  - `room_participants` for participant identity/language/session summaries.
  - `room_messages` in chronological order for `source`, `translated`, `relay`, and `chat`.
- Source transcript lines are treated as primary evidence.
- Relay and translated transcript lines are included as multilingual context but prompt policy tells
  the model not to double-count translated/relay versions of the same utterance.
- Chat messages are included when present.
- `source_stats` records counts for source transcript, translated transcript, relay, chat, included
  messages, and truncation.
- If there is no usable transcript/relay/chat text, the summary record is persisted as `skipped`
  with a conservative insufficient-content message.

### Summary Output

Persisted summary records include:

- `summary_id`
- `room_id`
- `status`: `pending`, `completed`, `failed`, or `skipped`
- `created_at`
- `generated_at`
- `summary_language`
- `summary_text`
- `highlights`
- `decisions`
- `action_items`
- `participant_summary`
- `duration_seconds`
- `source_stats`
- `error` for failed/skipped states

### Grounding / Language Policy

- Prompt/model-call logic lives in `BE/server/brain/meeting_summary.py`.
- The prompt explicitly forbids invented facts, decisions, owners, deadlines, risks, causes, and
  next steps.
- Ambiguous decisions/action items must be omitted.
- Summary language is canonical `MEETING_SUMMARY_LANGUAGE`, default `en`.
- The backend does not infer language from room participants because there is no host/admin
  summary preference in current room metadata.

### Persistence / Retrieval

- MongoDB gets a new `meeting_summaries` collection with unique `room_id`.
- `rooms.meeting_summary` stores a compact status pointer for room-level archive visibility.
- Retrieval path added:
  - `GET /api/rooms/{room_id}/summary`
  - returns pending/completed/skipped/failed summary records from Mongo.
  - returns `404 meeting_summary_not_found` if no summary record exists or Mongo archive is disabled.

### Failure Behavior

- Model/API/JSON/persistence failures are caught by the summary service.
- Room finalization still succeeds even if summary generation fails.
- Failure is logged and persisted as `status=failed` when possible.

### Files Modified

- `BE/server/brain/meeting_summary.py`
- `BE/server/service/gateway/meeting_summary_service.py`
- `BE/server/service/gateway/room_service.py`
- `BE/server/service/gateway/api_rooms.py`
- `BE/server/service/gateway/ws_endpoint.py`
- `BE/server/service/persistence/room_history.py`
- `BE/server/models.py`
- `BE/server/config.py`
- `.env.example`
- `BE/.env.example`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `docs/backend/API_CONTRACT.md`
- `docs/backend/README.md`
- `docs/backend/IMPLEMENTATION_STATE.md`

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added, per instruction.
- Existing tests not modified.
- Lightweight checks run:
  - `PYTHONPATH=BE python -m py_compile BE/server/brain/meeting_summary.py BE/server/service/gateway/meeting_summary_service.py BE/server/service/persistence/room_history.py BE/server/service/gateway/room_service.py BE/server/service/gateway/api_rooms.py BE/server/service/gateway/ws_endpoint.py BE/server/models.py BE/server/config.py`
  - `git diff --check`
  - targeted import/model smoke check for `server.brain.meeting_summary`,
    `MeetingSummaryResponse`, and `RoomService`

---

## Turn Update: 2026-05-04 MongoDB Authentication Wiring Kickoff

- Time: 2026-05-04T00:00:00+07:00
- Mode: CODE-ONLY
- Testing deferred: full test suite not run, per instruction

### Objective

Enable username/password authentication for MongoDB historical persistence without
changing Redis-backed hot runtime behavior or Mongo persistence business logic.

### Read Status

- Read required docs/config:
  - `docs/backend/README.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docker-compose.yml`
  - `docker-compose.prod.yml`
  - `.env.example`
  - `BE/.env.example`
  - `BE/server/config.py`
- Read Mongo wiring/persistence files:
  - `BE/server/integrations/mongodb.py`
  - `BE/server/service/persistence/room_history.py`
  - `BE/server/service/gateway/main.py`
  - related gateway app-state references

### Strategy Locked

- Use MongoDB auth in Docker Compose via `mongod --auth`.
- Create a root/admin user through `MONGO_INITDB_ROOT_USERNAME` /
  `MONGO_INITDB_ROOT_PASSWORD`.
- Create an app-specific user through an init script with `readWrite` on
  `MONGODB_DATABASE`.
- Backend connection remains side-effect persistence only:
  - URI with credentials is accepted when `MONGODB_URL` is set.
  - URI without credentials has `MONGODB_USERNAME` / `MONGODB_PASSWORD`
    injected if both are configured.
  - otherwise backend builds a credentialed URI from
    `MONGODB_HOST`, `MONGODB_PORT`, `MONGODB_DATABASE`,
    `MONGODB_USERNAME`, `MONGODB_PASSWORD`, and `MONGODB_AUTH_SOURCE`.
  - anonymous Mongo URLs are treated as config problems, not silently used.

### Final Sync

- Status: MongoDB auth wiring added for local/dev/prod compose stacks.
- Docker Compose changes:
  - `mongo` now starts with `mongod --auth --bind_ip_all`.
  - `MONGO_INITDB_ROOT_USERNAME` / `MONGO_INITDB_ROOT_PASSWORD` configure the root user.
  - `ops/mongo/init-app-user.js` creates or updates the app user with `readWrite`
    on `MONGODB_DATABASE` during first DB initialization.
  - local compose uses practical dev defaults; prod compose requires Mongo root
    and app credentials to be set.
- Backend config/env changes:
  - added `MONGODB_HOST`, `MONGODB_PORT`, `MONGODB_USERNAME`,
    `MONGODB_PASSWORD`, and `MONGODB_AUTH_SOURCE`.
  - `MONGODB_URL` remains supported, but only credentialed URIs are used directly.
  - if `MONGODB_URL` is blank, backend builds a credentialed URI from field-based config.
  - if a no-auth `MONGODB_URL` is present and username/password are set, backend logs
    a warning and injects credentials into that URI instead of connecting anonymously.
  - if neither credentialed URI nor username/password are available, Mongo persistence
    is disabled with a clear auth/config log message.
- Persistence behavior preserved:
  - no room/chat/transcript persistence business logic was rewritten.
  - Mongo failures still degrade through existing side-effect logging path.
  - Redis remains hot runtime state and pub/sub backbone.
- Existing data note:
  - Mongo init scripts only run on first volume initialization.
  - local volumes that were previously created without users must be recreated or
    manually migrated with users before authenticated Mongo will accept backend writes.
- Files modified:
  - `docker-compose.yml`
  - `docker-compose.prod.yml`
  - `.env.example`
  - `BE/.env.example`
  - `BE/server/config.py`
  - `BE/server/integrations/mongodb.py`
  - `ops/mongo/init-app-user.js`
  - `docs/backend/README.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Verification:
  - full test suite not run, per CODE-ONLY instruction.
  - new tests not added.
  - existing tests not modified.
  - lightweight checks run:
    - `python -m py_compile BE/server/config.py BE/server/integrations/mongodb.py BE/server/service/persistence/room_history.py BE/server/service/gateway/main.py`
    - `git diff --check -- docker-compose.yml docker-compose.prod.yml .env.example BE/.env.example BE/server/config.py BE/server/integrations/mongodb.py ops/mongo/init-app-user.js docs/backend/README.md docs/backend/IMPLEMENTATION_STATE.md`
    - field-based / no-auth-URI credential injection smoke check for `server.integrations.mongodb`
    - `docker compose config --quiet`
    - `node --check ops/mongo/init-app-user.js`

---

## Turn Update: 2026-05-04 BRSE Full-Duplex Relay Runtime Kickoff

- Time: 2026-05-04T00:00:00+07:00
- Mode: CODE-ONLY
- Testing deferred: full test suite not run, per instruction

### Objective

Improve BRSE / AI relay runtime toward practical full-duplex behavior:

- let current BRSE output finish instead of hard-cancelling on new meeting audio
- keep input listening active while output is playing
- queue/stage valid next utterances instead of dropping or cutting current relay
- detect chaotic overlap and fallback to controlled summary-style relay

### Read Status

- Read required docs:
  - `docs/backend/README.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
- Read required runtime files:
  - `BE/server/service/brain_runtime/room_manager.py`
  - `BE/server/service/media/livekit_runtime.py`
  - `BE/server/service/media/audio_input.py`
  - `BE/server/service/media/output_router.py`
  - `BE/server/brain/realtime/interpreter_client.py`
  - `BE/server/brain/realtime/client.py`
  - `BE/server/brain/realtime/session_config.py`
  - `BE/server/brain/realtime/source_policy.py`
  - `BE/server/brain/prompts/language.py`
- Related files read:
  - `BE/server/service/brain_runtime/events.py`

### Root Cause Traced

- Realtime VAD config already has `interrupt_response=false`, but BRSE wrapper still hard-cancels manually:
  - `InterpreterRealtimeClient._handle_event(... input_audio_buffer.speech_started ...)`
  - if `_assistant_speaking` then `await self._cancel_response(ws)`
- Room manager also cuts output on new capture status:
  - `RoomInterpreterManager._bind_client_callbacks(... on_status_change ...)`
  - when status is `capturing`, it pops current `transcript_state` and calls `router.clear_queue()`
- Existing overlap arbitration suppresses secondary speakers by disabling their `LiveKitAudioInput`, so overlapped valid speech can be dropped instead of being queued for the next turn.

### Planned Runtime Policy

- Replace hard-barge-in with controlled full-duplex:
  - new speech while output is active does not cancel current response
  - current output events continue to publish from their validated source utterance
  - input transcript for the new utterance can still be captured and staged
- Queue next validated utterance if a response is already active.
- Only create the next Realtime response when the active response reaches `response.done`.
- Keep source-transcript-first guardrails for all relay and summary output.
- Add chaos detection based on overlap pressure, queued turns, and concurrent active speakers.
- If chaos is high, synthesize a summary relay from validated recent source transcripts only.

### Final Sync

- Status: controlled full-duplex relay policy implemented in the backend runtime path.
- Root cause fixed:
  - `InterpreterRealtimeClient` no longer sends `response.cancel` on `input_audio_buffer.speech_started` while BRSE output is active.
  - `RoomInterpreterManager` no longer resets transcript state or clears the active output router merely because input capture restarted.
  - overlap handling no longer disables `LiveKitAudioInput` for the secondary speaker, so overlapped input can still be captured and staged.
- New speaking/listening concurrency policy:
  - output and input are tracked separately; current response source id continues to own relay output while a new committed input opens a separate utterance state.
  - if another valid source transcript arrives while a response is active, the realtime client queues it instead of cancelling the current response.
  - empty/rejected/failed input transcripts preserve the active response instead of flipping global response suppression.
  - queued relay responses start after `response.done` or after relay focus is released, while preserving generation/route/source validation.
- Overlap / chaos detection:
  - recent validated source turns are retained for a short window.
  - chaos is true only when there are multiple recent valid turns, multiple speakers, and either active overlap pressure or queued relay pressure.
  - relay focus payload now reports `policy=controlled_full_duplex_serialized_output`, `pending_relay_count`, and overlap chaos state.
- Summary fallback:
  - summary mode is conditional, not default.
  - summary relay is built only from validated recent source transcripts, capped in size, and deduped per target language / utterance set.
  - relay events include additive `relay_style: "normal" | "summary"` so FE and persistence can distinguish normal relay from overlap-summary fallback without breaking existing transcript fields.
- Prompt changes:
  - added explicit overlap-summary instructions in `build_interpreter_summary_instructions`.
  - summary prompt keeps source-transcript-first guardrails: no guessing, no invented facts, output nothing if snippets are too thin or unclear.
- Files modified for this runtime change:
  - `BE/server/brain/realtime/interpreter_client.py`
  - `BE/server/brain/realtime/session_config.py`
  - `BE/server/service/brain_runtime/room_manager.py`
  - `BE/server/service/brain_runtime/events.py`
  - `BE/server/models.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/service/persistence/room_history.py`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Verification:
  - full test suite not run, per CODE-ONLY instruction.
  - new tests not added.
  - existing tests not modified.
  - lightweight syntax/diff checks run:
    - `python -m py_compile BE/server/brain/realtime/interpreter_client.py BE/server/brain/realtime/session_config.py BE/server/service/brain_runtime/room_manager.py BE/server/service/brain_runtime/events.py BE/server/models.py BE/server/service/gateway/event_consumer.py BE/server/service/persistence/room_history.py`
    - `git diff --check -- BE/server/brain/realtime/interpreter_client.py BE/server/brain/realtime/session_config.py BE/server/service/brain_runtime/room_manager.py BE/server/service/brain_runtime/events.py BE/server/models.py BE/server/service/gateway/event_consumer.py BE/server/service/persistence/room_history.py docs/backend/IMPLEMENTATION_STATE.md`

---

## Turn Update: 2026-05-04 Mongo Persistence Layer Kickoff

- Time: 2026-05-04T00:00:00+07:00
- Mode: CODE-ONLY
- Testing deferred: full test suite not run, per instruction

### Objective

Add MongoDB as an additive persistence / historical archive layer for room
metadata, participant history, chat, transcript, and relay history while keeping
Redis as the hot runtime source of truth for active rooms.

### Strategy Locked

- Redis remains responsible for room runtime state, pub/sub, TTL lifecycle,
  websocket snapshots, and BRSE runtime coordination.
- MongoDB stores historical records only:
  - `rooms` for room metadata and lifecycle summary.
  - `room_participants` for cumulative participant summaries and join sessions.
  - `room_messages` for chat, source transcript, translated transcript, and
    relay conversation items in timestamp order.
- Persistence and Telegram notifications are side effects. Transient failures
  must log and degrade gracefully without failing create/join/chat/transcript
  runtime paths.

### Initial Hook Points

- Room creation: `RoomService.create_room(...)`
- Participant join: `RoomService.join_room(...)`
- Chat messages: `RoomService.send_chat_message(...)`
- Transcript / relay final events: `event_consumer._handle_interpreter_events(...)`
- Room empty/ended summary: `RoomService.cleanup_participant(...)`
- Startup/shutdown wiring: `service.gateway.main` and `app_state`

### Final Sync

- Time: 2026-05-04T00:00:00+07:00
- Status: MongoDB persistence layer added as Redis-adjacent historical storage.
- Runtime rule preserved: Redis remains active room state, pub/sub, TTL lifecycle,
  websocket snapshot source, and BRSE runtime coordination backbone.

### MongoDB Collections

#### `rooms`

Stores room-level historical summary:

- `room_id`
- `state`
- `created_at`, `activated_at`, `emptied_at`, `expires_at`, `ended_at`
- `meeting_languages`
- `brse_enabled`
- `meeting_mode`
- `interpreter_mode`
- `audio_routing`
- `virtual_participants`
- `participant_count_current`
- `participant_count_total`
- `participant_ids`
- `participant_summaries`
- `duration_seconds`
- `status_summary`
- message counters and last-event timestamps

Room lifecycle strategy:

- `create_room` inserts initial room archive document.
- first human join marks the archive active and sets `activated_at` if missing.
- empty room cleanup marks `state=empty`, sets `ended_at`, and stores duration.
- room expiry is archived by:
  - a lightweight per-room expiry side-effect task scheduled at create time
  - join / websocket rejection paths for expired rooms
- expiry archive update does not override an already-terminal room summary.
- lifecycle archive updates skip stale terminal writes if Mongo already has a
  newer `last_event_at`, which avoids an old empty/expired side effect
  overwriting a fast rejoin.

#### `room_participants`

Stores participant summaries and join-session history:

- unique key: `room_id + participant_id`
- participant identity/display/language/kind/is_virtual/livekit metadata
- `join_count`
- `first_joined_at`, `last_joined_at`, `last_left_at`
- `sessions[]` with `session_id`, `joined_at`, `left_at`, `status`, `reason`, and client metadata

Participant strategy:

- human joins append a new session and refresh room participant totals.
- if the same `participant_id` appears again, it appends another session and increments `join_count`.
- BRSE virtual participant records are stored with `is_virtual=true` / `kind=virtual_brse`, but room `participant_count_total` counts human users only.
- leave / cleanup updates the matching session `left_at` when available.

#### `room_messages`

Stores all durable conversation items in one chronological collection:

- `conversation_type`: `chat` or `transcript`
- `kind`: `chat`, `source`, `translated`, or `relay`
- `room_id`
- `message_id` / `transcript_id`
- participant/display/language fields
- `text`
- `created_at`
- chat metadata: `translation_mode`, `translations`, client event id
- transcript metadata: `source_text`, `translated_text`, `brse_text`, src/target lang, listener, relay/audio output

Conversation strategy:

- chat messages are written after Redis recent chat persistence succeeds.
- transcript / relay lines are written on `transcript.final` after Gateway builds the canonical `TranscriptEvent`.
- source, translated, and BRSE relay transcript lines share `room_messages` to keep room conversation history queryable by one `room_id + created_at` scan.

### Graceful Degradation

- MongoDB client is optional at runtime. If `MONGODB_URL` is unset or `motor` is unavailable, archive writes are disabled and Redis runtime continues.
- MongoDB writes are scheduled as background side effects and wrapped in error logging.
- Mongo insert/update failures do not fail create-room, join-room, chat, leave, websocket, or transcript fan-out paths.

### Telegram Join Notification

- Added optional `participant.joined` Telegram notification.
- Config:
  - `TELEGRAM_NOTIFY_PARTICIPANT_JOINED=true`
- Payload includes:
  - room id
  - meeting languages
  - BRSE on/off
  - current human participant count
  - joined participant id, display name, language, joined time
- Telegram failures remain non-fatal side effects.

### Config / Stack

Added config/env:

- `MONGODB_URL`
- `MONGODB_DATABASE`
- `MONGODB_SERVER_SELECTION_TIMEOUT_MS`
- `MONGODB_CONNECT_TIMEOUT_MS`
- `TELEGRAM_NOTIFY_PARTICIPANT_JOINED`

Local/prod compose changes:

- Added `mongo:7` service.
- Added `mongo_data` volume.
- Gateway receives `MONGODB_URL` / `MONGODB_DATABASE`.
- Gateway depends on Mongo in compose startup order.
- Interpreter remains Redis/LiveKit runtime only and does not use Mongo.

### Files Changed

| File | Change |
|------|--------|
| `BE/server/integrations/mongodb.py` | New Mongo client wiring with optional Motor dependency handling |
| `BE/server/service/persistence/room_history.py` | New MongoDB room history repository and indexes |
| `BE/server/service/persistence/__init__.py` | New persistence package |
| `BE/server/config.py` | Added MongoDB and Telegram join notification config |
| `BE/server/models.py` | Added optional `activated_at` / `emptied_at` to `RoomState` |
| `BE/server/service/gateway/main.py` | Wires Mongo repository into Gateway lifecycle |
| `BE/server/service/gateway/app_state.py` | Stores Mongo client and room history repository |
| `BE/server/service/gateway/room_service.py` | Adds room/participant/chat/lifecycle persistence hooks and Telegram join notify |
| `BE/server/service/gateway/room_store.py` | Allows `mark_room_empty` to persist `emptied_at` in Redis state |
| `BE/server/service/gateway/event_consumer.py` | Persists `transcript.final` / relay lines to Mongo archive |
| `BE/server/service/gateway/ws_endpoint.py` | Archives room expiry on expired websocket rejection |
| `BE/server/integrations/telegram.py` | Adds participant-joined notification |
| `BE/requirements.txt` | Adds `motor` |
| `.env.example` | Adds MongoDB and Telegram join notification env |
| `docker-compose.yml` | Adds local MongoDB service and Gateway env wiring |
| `docker-compose.prod.yml` | Adds prod MongoDB service and Gateway env wiring |
| `docs/backend/README.md` | Documents MongoDB archive role and Telegram join notification |
| `docs/backend/FILE_STRUCTURE.md` | Documents new integration/persistence modules |
| `docs/backend/IMPLEMENTATION_STATE.md` | This implementation state update |

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added, per instruction.
- Targeted syntax check only:
  - `python -m py_compile BE/server/config.py BE/server/integrations/mongodb.py BE/server/integrations/telegram.py BE/server/models.py BE/server/service/gateway/app_state.py BE/server/service/gateway/main.py BE/server/service/gateway/room_store.py BE/server/service/gateway/room_service.py BE/server/service/gateway/event_consumer.py BE/server/service/gateway/ws_endpoint.py BE/server/service/persistence/room_history.py`
- Whitespace check:
  - `git diff --check`
- Targeted import smoke check:
  - `PYTHONPATH=BE python - <<'PY' ... imports ok`

---

## Turn Update: 2026-05-04 Backend Architecture README

- Time: 2026-05-04T00:00:00+07:00
- Mode: documentation-only
- Testing deferred: not applicable

### Objective

Add a backend-facing architecture README in `docs/backend/README.md` to give a
high-level view of the system without relying on code-heavy explanations.

### What was added

- New file: `docs/backend/README.md`

### Scope of the new README

The document is intentionally architecture-first and flow-first. It covers:

- main backend domains and responsibilities
- the role of Gateway, Brain Runtime, Brain, Media, Redis, and LiveKit
- major data flows:
  - create room
  - join room
  - room websocket sync
  - BRSE / AI relay pipeline
  - chat pipeline
  - screen share pipeline
  - room expiry pipeline
- production topology at a high level
- where to look next for deeper docs

### Documentation style decision

- Minimal code snippets
- Focus on responsibility boundaries and runtime flow
- Intended as the "mental model" document for reviewing the backend as a whole

### Follow-up expansion

- Expanded `docs/backend/README.md` with visual diagrams and sequence flows:
  - system overview diagram
  - responsibility map
  - create-room flow
  - join-room flow
  - websocket sync flow
  - BRSE relay pipeline
  - chat pipeline
  - screen-share pipeline
  - expiry enforcement flow
  - production topology diagram

- Goal of the expansion:
  - make the backend easier to understand at a glance
  - reduce dependence on low-level code reading
  - provide a more visual system review document

---

## Turn Update: 2026-05-03 Chat Translation Feature

- Time: 2026-05-03T00:00:00+07:00
- Mode: CODE-ONLY
- Testing deferred: full test suite not run, per instruction

### Objective

Add backend support for chat messages with optional translation. Existing chat
flow is preserved unchanged (backward-compatible additive extension).

### Chat Translation Contract

#### Client → Server: `chat.send`

```json
{
  "type": "chat.send",
  "event_id": "evt_...",
  "room_id": "rm_...",
  "sent_at": "2026-05-03T...",
  "payload": {
    "text": "xin chào",
    "translation_mode": "original_only"
  }
}
```

`translation_mode` is optional.
- If omitted or any unrecognised value → defaults to `"original_only"` (backward-compatible).
- Valid values: `"original_only"` | `"translate"`.

#### Server → All clients: `chat.message`

Canonical broadcast payload (additive — all fields present, old clients ignore new ones):

```json
{
  "type": "chat.message",
  "event_id": "evt_...",
  "room_id": "rm_...",
  "sent_at": "2026-05-03T...",
  "payload": {
    "message_id": "msg_...",
    "room_id": "rm_...",
    "participant_id": "pt_...",
    "display_name": "Huy",
    "language": "vi",
    "text": "xin chào",
    "created_at": "2026-05-03T...",
    "translation_mode": "translate",
    "translations": [
      { "language": "en", "text": "hello" }
    ]
  }
}
```

When `translation_mode = "original_only"`:
- `translations` is an empty list `[]`.

When `translation_mode = "translate"` and translation succeeded:
- `translations` contains one entry for the target language.

When `translation_mode = "translate"` but translation failed:
- `translations` is an empty list `[]` (graceful degradation).
- Original `text` is still present and broadcast — message is never lost.

#### Translation strategy

- Room has a 2-language pair (e.g. `["vi", "en"]`).
- Target language = the language in the pair that is NOT the sender's language.
- Example: sender language = `vi`, room pair = `["vi", "en"]` → target = `en`.
- Translation uses OpenAI chat completions API (`gpt-4o-mini`, temperature 0.2).
- This is chat-only text translation; completely separate from the audio relay
  realtime API path.

#### Default / backward-compatible behavior

- Old FE clients that do not send `translation_mode` receive messages with
  `translation_mode = "original_only"` and `translations = []`.
- Old FE clients that ignore `translation_mode` / `translations` continue to
  render `text` unchanged.
- No existing field is removed or renamed.

### Canonical `ChatMessage` shape

```python
class ChatTranslation(BaseModel):
    language: MeetingLanguage  # e.g. "en"
    text: str

class ChatMessage(BaseModel):
    message_id: str
    room_id: str
    participant_id: str
    display_name: str
    language: Language
    text: str
    created_at: str
    client_event_id: Optional[str] = None
    sender_id: Optional[str] = None
    sender_display_name: Optional[str] = None
    sender_language: Optional[Language] = None
    sent_at: Optional[str] = None
    # New additive fields:
    translation_mode: ChatTranslationMode = "original_only"
    translations: List[ChatTranslation] = []
```

### Snapshot changes

- `recent_messages` in room snapshot already carries full `ChatMessage` objects.
- New `translation_mode` and `translations` fields are stored with each message
  in Redis (via `model_dump_json()`).
- Users joining after translation has occurred will see correct translated
  content in `snapshot.recent_messages`.
- No snapshot schema change; the list of `ChatMessage` objects simply now
  include the new fields.

### Translation failure strategy

- Translation is attempted asynchronously before broadcast.
- If OpenAI call fails (timeout, API error, empty response):
  - `translations` is left empty `[]`.
  - Original message is still persisted and broadcast.
  - A `WARNING` log is emitted for observability.
- FE must treat empty `translations` on a `translate` message as "no
  translation available, show original text".

### Files changed

| File | Change |
|------|--------|
| `BE/server/models.py` | Added `ChatTranslationMode` literal, `ChatTranslation` model, `translation_mode` + `translations` fields to `ChatMessage` |
| `BE/server/service/gateway/chat_translator.py` | New — lightweight async chat translation helper using OpenAI chat completions |
| `BE/server/service/gateway/room_service.py` | `send_chat_message()` accepts `translation_mode`, runs translation path, attaches `ChatTranslation` entries |
| `BE/server/service/gateway/ws_endpoint.py` | `chat.send` handler reads `translation_mode` from payload, defaults to `"original_only"` |

### Testing

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing chat tests not broken (additive-only change; default `translation_mode="original_only"` matches prior behavior).

---

## Turn Update: 2026-05-03 Gateway Under Service Refactor (Kickoff)

- Time: 2026-05-03T19:09:23+07:00
- Mode: CODE-ONLY
- Testing deferred: full test suite not run, per instruction

### Objective Locked

- Refactor backend into two primary domains:
  - `brain`: only AI/model-facing logic.
  - `service`: backend application logic, including Gateway transport and orchestration.
- Move Gateway under `service`; `gateway` must not remain a top-level backend domain next to `brain`.
- Preserve production behavior: no API/WS contract changes, no room lifecycle semantic changes, no BRSE toggle semantic changes, no LiveKit flow changes, no Redis state/event contract changes, and no unrelated business-logic fixes.

### Read Status

- Read required backend docs:
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/backend/FILE_STRUCTURE.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/API_CONTRACT.md`
- Read current backend tree and key runtime roots:
  - `BE/server/service/gateway/*`
  - `BE/server/brain/*`
  - `BE/server/service/*`
  - `BE/server/models.py`
  - Docker compose and Dockerfile entrypoint references
- Current issue before this turn's move: Gateway still exists at `BE/server/service/gateway/*`; this violates the new requested boundary because Gateway is backend service/transport logic, not an independent top-level domain.

### Classification Plan

- Keep in `brain`:
  - prompt/language instruction builders,
  - OpenAI Realtime client and meeting realtime wrapper,
  - model session/VAD config,
  - translation-test model client,
  - fallback STT/chat model pipeline,
  - AI source transcript anti-hallucination/meaningfulness policy.
- Keep/move in `service`:
  - `service/gateway`: FastAPI routes, WebSocket transport, auth, room store/service, browser LiveKit token issuance, event consumer, and test WebSocket endpoints.
  - `service/brain_runtime`: BRSE runtime daemon, room manager orchestration, Redis control/event IO.
  - `service/media`: LiveKit runtime/audio input/output adapters.
- Keep server-level/shared modules only where they are cross-cutting contracts/config/utilities: `models`, `events`, `redis`, `config`, `meeting_modes`, `integrations`, `shared`.

### Final Sync

- Time: 2026-05-03T19:11:37+07:00
- Status: Gateway is now under `service`; canonical backend domains are `server.brain` and `server.service`.

### Final Backend Domain Layout

```text
BE/server/
├── brain/
│   ├── prompts/              # prompt/instruction and language helpers
│   ├── realtime/             # OpenAI Realtime clients, session config, AI source policy
│   └── fallback/             # fallback STT + chat model path
├── service/
│   ├── gateway/              # FastAPI/WS transport, auth, room store/service, event fan-out
│   ├── brain_runtime/        # Redis control daemon and room-level BRSE orchestration
│   └── media/                # LiveKit media adapters used by the runtime service
├── integrations/             # external non-AI integrations
├── shared/                   # generic helpers
├── config.py
├── events.py
├── meeting_modes.py
├── models.py
└── redis.py
```

### Moves In This Turn

- `BE/server/gateway/*` -> `BE/server/service/gateway/*`
- Updated all canonical imports from `server.gateway.*` to `server.service.gateway.*`.
- Updated Gateway entrypoints:
  - `BE/Dockerfile`
  - `docker-compose.yml`
  - `docker-compose.prod.yml`
  - `BE/README.md`
  - `docs/backend/LIVEKIT_SETUP.md`
- Updated Gateway-adjacent service imports:
  - `BE/server/service/brain_runtime/daemon.py`
  - `BE/server/service/media/livekit_runtime.py`
  - Gateway import references in `BE/tests/*`

### Boundary Result

- `brain` remains AI-only:
  - prompt builders,
  - model/realtime clients,
  - model session config,
  - AI response/source policy,
  - fallback model pipeline.
- `service` now owns all backend application logic:
  - Gateway HTTP/WS ingress/egress,
  - room store/service and auth,
  - BRSE runtime daemon/room manager orchestration,
  - LiveKit media adapters,
  - integration glue between room state, Gateway, LiveKit, Redis, and Brain.
- `gateway` no longer exists as a top-level backend package. No compatibility shim was kept because the requested boundary requires Gateway to live under `service`.

### Behavior Preservation Notes

- No REST route paths changed.
- No WebSocket route paths or event names changed.
- No room snapshot shape changed.
- No room lifecycle, BRSE on/off, expiry, chat, LiveKit token, Telegram notification, or Redis event semantics were intentionally changed.
- This was a mechanical package move plus import/entrypoint/docs cleanup.

### Docs Updated

- `docs/backend/FILE_STRUCTURE.md` documents `server.service.gateway` under the `service` domain and removes top-level Gateway from the target tree.
- `docs/backend/GATEWAY_DESIGN.md` documents `server.service.gateway` as the canonical Gateway module path.
- `docs/backend/IMPLEMENTATION_STATE.md` records this behavior-preserving gateway-under-service refactor.

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Lightweight checks run:
  - `python -m py_compile $(find BE/server BE/tests -name '*.py' | sort)`
  - import smoke for `server.service.gateway.main`, Gateway store/service/hub, `service.brain_runtime.room_manager`, `service.media.livekit_runtime`, and `brain.realtime.interpreter_client`
  - `git diff --check`

## Turn Update: 2026-05-03 Brain vs Service Boundary Refactor (Kickoff)

- Time: 2026-05-03T18:31:30+07:00
- Mode: CODE-ONLY
- Testing deferred: full test suite not run, per instruction

### Objective Locked

- Refactor only AI-adjacent backend code so `brain` contains AI-facing logic and `service` contains backend orchestration/application logic.
- Preserve production behavior: no API/WS contract changes, no room lifecycle semantic changes, no BRSE on/off semantic changes, no LiveKit flow changes, no Redis channel/event contract changes, and no unrelated bugfixes.
- Use mechanical moves/import cleanup where possible.

### Read Status

- Read required docs:
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/backend/FILE_STRUCTURE.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/API_CONTRACT.md`
- Read current backend tree and key files:
  - `BE/server/brain/*`
  - `BE/server/service/gateway/*`
  - `BE/server/models.py`
  - Docker compose / entrypoint paths
- Path note: after the previous cleanup, `BE/server/interpreter/*`, `BE/server/src/*`, and `BE/src/*` no longer exist; active AI-adjacent code is under `BE/server/brain/*`.

### Classification Plan

- Keep in `brain`:
  - prompt/language instruction builders,
  - OpenAI Realtime client and meeting realtime wrapper,
  - model session/VAD config,
  - translation-test model client,
  - fallback STT/chat model pipeline,
  - source transcript anti-hallucination/meaningfulness policy used by the model-response path.
- Move to `service`:
  - process entrypoint and Redis control daemon,
  - room-level manager/orchestration,
  - Redis event publisher/envelope adapter,
  - LiveKit room runtime and audio ingress/egress adapters,
  - backend routing between room state, LiveKit media, and brain clients.

### Final Sync

- Time: 2026-05-03T18:35:38+07:00
- Status: `brain` vs `service` boundary refactor completed with canonical imports and updated runtime entrypoint.

### Final Classification

#### `brain`

- `BE/server/brain/prompts/language.py`
  - language detection/routing and prompt/instruction helpers.
- `BE/server/brain/realtime/client.py`
  - reusable OpenAI Realtime websocket client.
- `BE/server/brain/realtime/interpreter_client.py`
  - meeting BRSE realtime model wrapper and model-event callback bridge.
- `BE/server/brain/realtime/session_config.py`
  - realtime model session payload, VAD config, and BRSE instruction config.
- `BE/server/brain/realtime/source_policy.py`
  - source transcript meaningfulness and anti-hallucination policy used by the model-response path.
- `BE/server/brain/realtime/translation_test_client.py`
  - gateway translation-test realtime model client.
- `BE/server/brain/realtime/main.py`
  - local realtime CLI that directly runs the realtime model client.
- `BE/server/brain/fallback/main.py`
- `BE/server/brain/fallback/pipeline.py`
  - fallback STT + chat model path.

#### `service`

- `BE/server/service/brain_runtime/main.py`
  - BRSE runtime service process entrypoint.
- `BE/server/service/brain_runtime/daemon.py`
  - Redis control consumer, room snapshot lookup, BRSE enabled/expired gates, manager spawn/stop lifecycle.
- `BE/server/service/brain_runtime/room_manager.py`
  - room-level orchestration around brain clients, participant/media coordination, speaker lifecycle/focus arbitration, transcript publish orchestration.
- `BE/server/service/brain_runtime/events.py`
  - Redis event publisher/envelope adapter for service-to-gateway output.
- `BE/server/service/media/audio_input.py`
  - LiveKit audio stream adapter into the generic `AudioInput` contract consumed by brain clients.
- `BE/server/service/media/livekit_runtime.py`
  - LiveKit room participant runtime and microphone track subscription.
- `BE/server/service/media/output_router.py`
  - brain audio output publication to LiveKit relay track.

### Notable Moves In This Turn

- `BE/server/brain/main.py` -> `BE/server/service/brain_runtime/main.py`
- `BE/server/brain/relay/daemon.py` -> `BE/server/service/brain_runtime/daemon.py`
- `BE/server/brain/relay/events.py` -> `BE/server/service/brain_runtime/events.py`
- `BE/server/brain/relay/room_manager.py` -> `BE/server/service/brain_runtime/room_manager.py`
- `BE/server/brain/livekit/audio_input.py` -> `BE/server/service/media/audio_input.py`
- `BE/server/brain/livekit/runtime.py` -> `BE/server/service/media/livekit_runtime.py`
- `BE/server/brain/livekit/output_router.py` -> `BE/server/service/media/output_router.py`
- Source transcript validation/anti-hallucination constants and logic were extracted from the room manager into `BE/server/brain/realtime/source_policy.py`; service still calls the same policy from the same callback path.

### Entrypoints Updated

- Docker compose interpreter command now uses `python -m server.service.brain_runtime.main`.
- Production compose interpreter command uses the same path.
- `BE/README.md` and `docs/backend/LIVEKIT_SETUP.md` now document `server.service.brain_runtime.main` for the BRSE runtime service.

### Behavior Preservation Notes

- No API/WS contract changes.
- No Redis channel/event type changes.
- No room lifecycle, BRSE toggle, expiry, chat, participant, LiveKit identity, or track naming behavior was intentionally changed.
- Realtime prompt/session/VAD behavior remains under `brain.realtime.session_config` unchanged.
- Source transcript policy logic was moved, not retuned.
- Room manager decision flow remains service-side and calls the same brain client/model callbacks.
- No compatibility shims were added in this turn; imports were migrated directly to canonical paths.

### Docs Updated

- `docs/backend/FILE_STRUCTURE.md` now documents the strict `brain` vs `service` boundary and module placement.
- `docs/backend/IMPLEMENTATION_STATE.md` updated with this boundary refactor.
- `docs/backend/GATEWAY_DESIGN.md` and `docs/backend/INTERPRETER_DESIGN.md` now point to `server.brain` for AI/model-facing code and `server.service` for orchestration/media.

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests only had imports updated where module paths moved.
- Lightweight checks run after this refactor:
  - `python -m py_compile BE/main.py BE/server/meeting_modes.py BE/server/service/gateway/ws_test_translation.py BE/server/service/brain_runtime/main.py BE/server/service/brain_runtime/daemon.py BE/server/service/brain_runtime/events.py BE/server/service/brain_runtime/room_manager.py BE/server/service/media/audio_input.py BE/server/service/media/livekit_runtime.py BE/server/service/media/output_router.py BE/server/brain/realtime/client.py BE/server/brain/realtime/interpreter_client.py BE/server/brain/realtime/session_config.py BE/server/brain/realtime/source_policy.py BE/server/brain/realtime/translation_test_client.py BE/server/brain/realtime/main.py BE/server/brain/prompts/language.py BE/server/brain/fallback/main.py BE/server/brain/fallback/pipeline.py BE/server/shared/audio.py BE/server/shared/logging_utils.py BE/tests/test_interpreter_audio_adapter.py BE/tests/test_realtime_observability.py`
  - `python - <<'PY' ... import server.service.brain_runtime.main, service room manager/media modules, brain realtime/source policy modules ... PY`
  - `git diff --check`

## Turn Update: 2026-05-03 Backend Brain Domain Refactor (Kickoff)

- Time: 2026-05-03T18:11:09+07:00
- Mode: CODE-ONLY
- Testing deferred: full test suite not run, per instruction

### Objective Locked

- Refactor backend source organization so AI/interpreter/realtime/relay logic has a clear domain home under `brain`.
- Preserve production behavior: API/WS contracts, room lifecycle, BRSE on/off semantics, LiveKit flow, Redis state/event semantics, relay arbitration, transcript-first gates, and Telegram/gateway behavior are not business-logic targets in this turn.
- Use low-risk mechanical moves and import cleanup; after cleanup, remove old shim folders so there is a single canonical import path.

### Initial Read Status

- Read required backend docs:
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/backend/FILE_STRUCTURE.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/API_CONTRACT.md`
- Read current backend tree and key runtime roots:
  - `BE/server/service/gateway/*`
  - `BE/server/interpreter/*`
  - `BE/server/src/realtime/*`
  - `BE/server/src/common/*`
  - `BE/server/models.py`
  - `BE/server/config.py`
  - Docker compose and Dockerfile entrypoint references

### Refactor Direction

- Create `BE/server/brain/` as the primary AI domain.
- Split moved AI code by responsibility:
  - `brain/relay/` for room-level BRSE orchestration and Redis event publishing.
  - `brain/realtime/` for OpenAI Realtime client/runtime behavior.
  - `brain/livekit/` for LiveKit audio ingress/egress used by BRSE runtime.
  - `brain/prompts/` for language routing and instruction/prompt builders.
  - `brain/fallback/` for fallback translation pipeline code.
- Keep `gateway` focused on HTTP/WS room transport and store/service ingress.
- Keep shared generic helpers separate from brain-specific language/prompt logic.
- Migrate callers to canonical `server.brain.*` and `server.shared.*` imports.

### Final Sync

- Time: 2026-05-03T18:17:09+07:00
- Status: backend AI/interpreter/realtime/relay code moved under `server.brain`; old shim folders removed; production entrypoint paths updated.

### New Backend Structure Summary

```text
BE/server/
├── brain/
│   ├── main.py
│   ├── relay/
│   │   ├── daemon.py
│   │   ├── events.py
│   │   └── room_manager.py
│   ├── realtime/
│   │   ├── client.py
│   │   ├── interpreter_client.py
│   │   ├── main.py
│   │   ├── session_config.py
│   │   └── translation_test_client.py
│   ├── livekit/
│   │   ├── audio_input.py
│   │   ├── output_router.py
│   │   └── runtime.py
│   ├── prompts/
│   │   └── language.py
│   └── fallback/
│       ├── main.py
│       └── pipeline.py
├── gateway/
├── integrations/
├── shared/
│   ├── audio.py
│   └── logging_utils.py
```

### Responsibility Boundaries After Refactor

- `server.service.gateway` remains HTTP/WS transport, auth, room store/service, LiveKit browser token issuance, and fan-out of backend events to clients.
- `server.brain` is now the AI domain home:
  - `brain.relay` owns Redis control consumption, room-level BRSE relay orchestration, source/relay transcript publication, focus/overlap arbitration, and manager lifecycle.
  - `brain.realtime` owns OpenAI Realtime clients, meeting realtime wrapper, BRSE session/VAD config, and translation-test realtime client.
  - `brain.livekit` owns LiveKit audio ingress and BRSE relay audio track output.
  - `brain.prompts` owns language routing/detection and instruction/prompt builders.
  - `brain.fallback` owns fallback STT + chat translation pipeline.
- `server.shared` contains generic helpers only: audio abstractions/device helpers and logging helpers.
- `server.integrations` remains non-AI external integrations such as Telegram.

### Notable Mechanical Moves

- `BE/server/interpreter/main.py` -> `BE/server/brain/main.py`
- `BE/server/interpreter/daemon.py` -> `BE/server/brain/relay/daemon.py`
- `BE/server/interpreter/event_publisher.py` -> `BE/server/brain/relay/events.py`
- `BE/server/interpreter/room_manager.py` -> `BE/server/brain/relay/room_manager.py`
- `BE/server/interpreter/interpreter_client.py` -> `BE/server/brain/realtime/interpreter_client.py`
- `BE/server/interpreter/meeting_config.py` -> `BE/server/brain/realtime/session_config.py`
- `BE/server/interpreter/translation_test_client.py` -> `BE/server/brain/realtime/translation_test_client.py`
- `BE/server/interpreter/audio_input.py` -> `BE/server/brain/livekit/audio_input.py`
- `BE/server/interpreter/livekit_runtime.py` -> `BE/server/brain/livekit/runtime.py`
- `BE/server/interpreter/output_router.py` -> `BE/server/brain/livekit/output_router.py`
- `BE/server/src/realtime/client.py` -> `BE/server/brain/realtime/client.py`
- `BE/server/src/realtime/main.py` -> `BE/server/brain/realtime/main.py`
- `BE/server/src/common/lang.py` -> `BE/server/brain/prompts/language.py`
- `BE/server/src/fallback/main.py` and `pipeline.py` -> `BE/server/brain/fallback/`
- `BE/server/src/common/audio.py` -> `BE/server/shared/audio.py`
- `BE/server/src/common/logging_utils.py` -> `BE/server/shared/logging_utils.py`

### Removed Redundant Files

- Cleanup time: 2026-05-03T18:25:55+07:00
- Removed old `BE/server/interpreter/` shim package after backend imports and entrypoints were migrated to `server.brain.*`.
- Removed old `BE/server/src/` shim package after backend imports and CLI paths were migrated to `server.brain.*` / `server.shared.*`.
- Removed old top-level `BE/src/__init__.py` legacy namespace bridge.
- Removed tracked root `.DS_Store`, local `.DS_Store` artifacts, backend `__pycache__`, and backend `.pytest_cache`.

### Entrypoints Updated

- Docker compose interpreter command changed from `python -m server.interpreter.main` to `python -m server.service.brain_runtime.main`.
- Production compose interpreter command changed the same way.
- `BE/README.md` and `docs/backend/LIVEKIT_SETUP.md` now use the `server.service.brain_runtime.main` interpreter entrypoint.
- Local CLI docs now point realtime/fallback commands at `server.brain.realtime.main` and `server.brain.fallback.main`.
- Backend tests that referenced old import paths now import canonical `server.brain.*` modules.

### Behavior Preservation Notes

- REST/WS contracts were not intentionally changed.
- Gateway room state, Redis key/channel names, event types, room lifecycle, BRSE on/off behavior, chat behavior, LiveKit token generation, and Telegram notifier code were not rewritten.
- BRSE source-transcript-first filtering, relay focus arbitration, overlap suppression, Realtime VAD/session config, output routing, and LiveKit audio behavior were moved without changing decision logic.
- The only path-sensitive preservation adjustment made during move was keeping `server.shared.logging_utils` log directory resolution equivalent to the old `server/src/common/logging_utils.py` path.
- No unrelated production bugfixes were folded into this refactor.

### Docs Updated

- `docs/backend/FILE_STRUCTURE.md` now documents the `brain` domain layout, gateway/shared/integration boundaries, notable moves, removed shim folders, and behavior-preservation strategy.
- `docs/backend/IMPLEMENTATION_STATE.md` updated with this refactor record.
- `docs/backend/GATEWAY_DESIGN.md` and `docs/backend/INTERPRETER_DESIGN.md` now include update notes pointing to the new `server.brain` layout and noting that old shim folders were removed.
- `docs/backend/LIVEKIT_SETUP.md` command path updated for the interpreter/brain process.
- `BE/README.md` command paths updated for the moved backend entrypoints.

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests only had imports updated from old shim paths to canonical `server.brain` paths.
- Lightweight checks run:
  - `python -m py_compile BE/main.py BE/server/meeting_modes.py BE/server/service/gateway/ws_test_translation.py BE/server/brain/main.py BE/server/brain/relay/daemon.py BE/server/brain/relay/events.py BE/server/brain/relay/room_manager.py BE/server/brain/realtime/client.py BE/server/brain/realtime/interpreter_client.py BE/server/brain/realtime/session_config.py BE/server/brain/realtime/translation_test_client.py BE/server/brain/realtime/main.py BE/server/brain/livekit/audio_input.py BE/server/brain/livekit/runtime.py BE/server/brain/livekit/output_router.py BE/server/brain/prompts/language.py BE/server/brain/fallback/main.py BE/server/brain/fallback/pipeline.py BE/server/shared/audio.py BE/server/shared/logging_utils.py BE/tests/test_interpreter_audio_adapter.py BE/tests/test_realtime_observability.py`
  - `python - <<'PY' ... import server.brain/main, brain realtime/relay modules, prompt/shared modules ... PY`
  - `git diff --check`

## Turn Update: 2026-05-02 BRSE Realtime Mini Default

- Time: 2026-05-02T15:21:40+07:00
- Mode: CODE-ONLY
- Testing deferred: full test suite not run, per instruction

### Objective

- Reduce BRSE relay operating cost by trying `gpt-realtime-mini` as the default realtime model.
- Keep production rollback fast through the existing `OPENAI_REALTIME_MODEL` environment override.
- Keep the current source-transcript-first anti-hallucination relay pipeline unchanged.

### Runtime Model Change

- Default realtime model changed from `gpt-realtime-1.5` to `gpt-realtime-mini`.
- `OPENAI_REALTIME_MODEL` remains the override path for gateway, interpreter, CLI, and translation-test runtime paths.
- Docker compose defaults now use `gpt-realtime-mini` when `OPENAI_REALTIME_MODEL` is unset.
- Env examples and backend README now document `gpt-realtime-mini` as the default.

### Cost / Quality / Rollback

- Reason: evaluate lower-cost realtime inference for BRSE relay while preserving the current runtime contract.
- Expected cost impact: lower default BRSE relay spend for deployments that do not explicitly set `OPENAI_REALTIME_MODEL`.
- Quality risk: translation and voice relay quality may be slightly lower than `gpt-realtime-1.5`; monitor transcript accuracy, latency, and user reports after rollout.
- Rollback: set `OPENAI_REALTIME_MODEL=gpt-realtime-1.5` in deployment env and restart affected gateway/interpreter services.

### Files Modified

- `.env.example`
- `BE/.env.example`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `BE/README.md`
- `BE/server/config.py`
- `BE/server/src/realtime/client.py`
- `BE/server/interpreter/translation_test_client.py`
- `docs/backend/IMPLEMENTATION_STATE.md`

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests not modified.
- Lightweight checks run:
  - `python -m py_compile BE/server/config.py BE/server/src/realtime/client.py BE/server/interpreter/translation_test_client.py`
  - `git diff --check`

## Turn Update: 2026-05-02 BRSE Source-Transcript-First Anti-Hallucination Runtime

- Time: 2026-05-02T14:57:10+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective Locked

- Stop BRSE/AI relay from speaking on silence, noise, vague speech, partial ASR fragments, or model self-generated responses.
- Make completed source transcript the required source of truth before any BRSE relay text/audio can publish.
- Prefer slower or suppressed relay over hallucinated, guessed, stale, or wrong-speaker output.

### Mandatory Read Status

- Read required docs:
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/API_CONTRACT.md`
- Read required runtime files:
  - `BE/server/interpreter/meeting_config.py`
  - `BE/server/interpreter/interpreter_client.py`
  - `BE/server/interpreter/room_manager.py`
  - `BE/server/interpreter/output_router.py`
  - `BE/server/interpreter/audio_input.py`
  - `BE/server/interpreter/livekit_runtime.py`
  - `BE/server/interpreter/event_publisher.py`
  - `BE/server/src/realtime/client.py`
  - `BE/server/src/common/lang.py`
- Path note: requested `BE/src/realtime/client.py` and `BE/src/common/lang.py` do not exist in this checkout; active files are under `BE/server/src/...`.

### Policy Implemented

- Policy name: `source_transcript_first_strict`.
- Realtime VAD no longer auto-creates model responses:
  - `turn_detection.create_response=false`
  - `turn_detection.interrupt_response=false`
- BRSE relay response is now created manually only after:
  - input audio is committed,
  - source transcription completes,
  - transcript passes low-signal/meaningfulness gates,
  - speaker route still matches room language pair,
  - speaker still owns current relay focus/generation,
  - response source id matches the active utterance.
- Model response is now generated from the validated transcript text via out-of-band `response.create(conversation="none")`, not from loose audio context.

### Runtime Gates Added

- Source transcript guard:
  - rejects empty transcript,
  - rejects punctuation-only transcript,
  - rejects filler-only transcript,
  - rejects known noise-only ASR outputs,
  - rejects repetitive low-signal fragments,
  - rejects too-short transcript,
  - rejects too-short speech duration when available.
- Publish guard before source transcript events:
  - source partial is emitted only after committed input and a meaningful partial threshold.
  - source final is emitted only when completed transcript passes final source validation.
- Publish guard before relay text/audio:
  - relay partial/final requires `source_committed && source_final && source_valid`.
  - audio delta/flush requires the same valid source state.
  - relay output requires matching utterance id from the active response source.
  - relay output requires current speaker generation, current route, and room relay focus.
- Stale response guard:
  - response events without a pending validated source are cancelled/dropped.
  - response events with mismatched response/source ids are dropped.
  - response arriving after utterance reset, speaker mismatch, route change, or focus change cannot publish text/audio.
- Silence/no-speech handling:
  - empty or failed input transcription now suppresses response, prunes conversation items, returns status to idle, and releases focus through existing cooldown.

### Prompt / VAD Changes

- Prompt now explicitly says:
  - relay only from completed, validated source transcript,
  - never speak on silence/noise/VAD-only events/incomplete transcript,
  - when uncertain, say nothing,
  - do not guess missing words,
  - do not complete fragments,
  - do not fill gaps or infer meeting context.
- VAD is less aggressive for noisy rooms:
  - `threshold`: `0.40` -> `0.58`
  - `silence_duration_ms`: `840` -> `1000`
  - `prefix_padding_ms`: `320` -> `300`

### Files Modified

- `BE/server/interpreter/meeting_config.py`
  - disabled auto responses in VAD config,
  - raised VAD activation certainty,
  - strengthened anti-hallucination/source-transcript-first instructions.
- `BE/server/interpreter/interpreter_client.py`
  - tracks active input item id and active response source id,
  - suppresses stale input transcription events,
  - handles empty/failed transcription as no-relay,
  - creates out-of-band response only from approved source transcript,
  - cancels/drops any response created without a validated source.
- `BE/server/interpreter/room_manager.py`
  - added meaningfulness/noise/filler source transcript filter,
  - opens utterance only after committed input,
  - approves relay only from valid source final,
  - gates relay text/audio by utterance id, generation, focus, speaker route, and source validity.
- `docs/backend/IMPLEMENTATION_STATE.md`
  - updated this implementation state.

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests not modified.
- Lightweight checks run:
  - `python -m py_compile BE/server/interpreter/meeting_config.py BE/server/interpreter/interpreter_client.py BE/server/interpreter/room_manager.py BE/server/interpreter/translation_test_client.py`
  - `git diff --check -- BE/server/interpreter/meeting_config.py BE/server/interpreter/interpreter_client.py BE/server/interpreter/room_manager.py`

### Hotfix: Realtime Response Modalities Parameter

- Time: 2026-05-02T15:06:07+07:00
- Production log showed Realtime rejected manual source-transcript relay creation with:
  - `unknown_parameter`
  - `response.output_modalities`
- Fixed `response.create` payload to use `response.modalities`, matching the Realtime websocket shape used elsewhere in this backend session config.
- Lightweight checks rerun:
  - `python -m py_compile BE/server/interpreter/interpreter_client.py BE/server/interpreter/meeting_config.py BE/server/interpreter/room_manager.py`
  - `git diff --check -- BE/server/interpreter/interpreter_client.py BE/server/interpreter/meeting_config.py BE/server/interpreter/room_manager.py docs/backend/IMPLEMENTATION_STATE.md`

## Turn Update: 2026-05-02 BRSE Overlap Speech Arbitration (Kickoff)

- Time: 2026-05-02T14:05:37+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective Locked

- Harden room-level BRSE interpreter runtime for overlapping speakers.
- Reduce mixed relay/transcript output when multiple human mic tracks become active near the same time.
- Keep single-speaker happy path unchanged and avoid frontend or gateway core redesign.

### Mandatory Read Status

- Read required docs:
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/API_CONTRACT.md`
- Read required runtime files:
  - `BE/server/interpreter/room_manager.py`
  - `BE/server/interpreter/interpreter_client.py`
  - `BE/server/interpreter/livekit_runtime.py`
  - `BE/server/interpreter/audio_input.py`
  - `BE/server/interpreter/output_router.py`
  - `BE/server/interpreter/meeting_config.py`
  - `BE/server/interpreter/event_publisher.py`
  - `BE/server/src/realtime/client.py`
  - `BE/server/src/common/lang.py`
- Path note: requested `BE/src/realtime/client.py` and `BE/src/common/lang.py` do not exist in this checkout; active files are under `BE/server/src/...`.
- Related state/relay files inspected:
  - `BE/server/events.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/models.py`
  - FE status usage was skimmed only to avoid choosing a backend status shape that would obviously break runtime consumers; no FE edits planned.

### Root Cause / Hypothesis

- Current BRSE runtime starts an independent realtime client and output router per speaker mic track.
- Realtime VAD can detect speech per speaker, but the room manager does not arbitrate which speaker owns room-level relay focus.
- During overlap, multiple speaker clients can publish source transcript, relay transcript, and BRSE audio concurrently.
- Room-level BRSE semantics therefore degrade because the virtual BRSE participant appears to relay multiple speakers at once, and mic bleed/overlap can cause models to merge or misattribute content.

### Chosen Policy

- Implement deterministic single-primary-speaker arbitration at room scope.
- The first speaker whose realtime VAD reports `speech_started` claims relay focus.
- While focus is held, later speakers are marked `blocked_due_to_overlap`; their relay input is gated and their transcript/audio callbacks are suppressed for that overlapped turn.
- Focus is released only after the primary speaker reaches idle and a short cooldown elapses, preventing rapid flip-flop between speakers.
- Degraded overlap behavior: relay less content but keep output attributable, serialized, and easier to understand.

### Initial Implementation Plan

- Add a small input gate to `LiveKitAudioInput` so the manager can temporarily drop overlapped speaker frames without tearing down LiveKit streams.
- Add speech-start/speech-stop callbacks to `InterpreterRealtimeClient` for room-level arbitration while keeping existing status callbacks.
- Add room-level speaker lifecycle/focus state in `RoomInterpreterManager`: `idle`, `listening`, `speaking`, `cooling_down`, `blocked_due_to_overlap`.
- Suppress non-focus transcript/audio publication and clear queued router output for blocked speakers.
- Enrich interpreter status/transcript payloads with relay focus/overlap metadata for observability.
- Add prompt guardrail instructing a runtime to relay only its assigned speaker and ignore overlapping bleed.
- Final state update will list changed files, policy behavior, and deferred verification.

### Final Sync: BRSE Overlap Speech Arbitration

- Time: 2026-05-02T14:11:46+07:00
- Final status: backend/runtime overlap handling implemented with deterministic room-level relay focus.

### Arbitration Policy Implemented

- Policy name: `single_primary_speaker_serialized`.
- First speaker whose realtime VAD reports `speech_started` claims room relay focus.
- The focus speaker is the only speaker allowed to publish source transcript, relay transcript, and BRSE audio for that turn.
- Later speakers that start while focus is held are marked `blocked_due_to_overlap`.
- Blocked speakers have their `LiveKitAudioInput` gate disabled, queued router output cleared, transcript state dropped, and text/audio callbacks suppressed.
- Focus is released only after the primary speaker reaches realtime `idle` and a short `0.85s` cooldown elapses.
- Blocked speakers are re-enabled after focus release and can claim focus on their next detected speech turn.

### Speaker State Model

- Added room-manager lifecycle states:
  - `idle`
  - `listening`
  - `speaking`
  - `cooling_down`
  - `blocked_due_to_overlap`
- State owner is `RoomInterpreterManager`; realtime clients remain per-speaker, but publish permission is now room-arbitrated.
- Runtime focus metadata tracks:
  - `relay_focus_speaker_id`
  - `relay_focus_generation`
  - `relay_focus_started_at`
  - `relay_focus_cooldown_until`
  - blocked speaker ids/generations and overlap start timestamps.

### Event / Observability Changes

- `interpreter.status` can now emit `status=blocked_due_to_overlap` for suppressed overlap speakers.
- `interpreter.status`, `transcript.partial`, and `transcript.final` can include optional:
  - `relay_focus.policy`
  - `relay_focus.active_speaker_id`
  - `relay_focus.speaker_state`
  - `relay_focus.blocked_speaker_ids`
  - `relay_focus.suppressed_speaker_count`
  - `relay_focus.cooldown_ms`
  - `overlap.detected`
  - `overlap.primary_speaker_id`
  - `overlap.speaker_blocked`
  - `overlap.overlap_window_ms`
- Added logs for:
  - relay focus claimed/released
  - speaker lifecycle transitions
  - overlap detected
  - blocked overlap turn finished
  - audio input gate enabled/disabled

### Files Modified

- `BE/server/interpreter/room_manager.py`
  - added room-level relay focus arbitration
  - added speaker lifecycle state
  - suppresses non-focus transcript/audio callbacks
  - publishes overlap/focus metadata
- `BE/server/interpreter/audio_input.py`
  - added input gate to drop frames for temporarily blocked speakers
  - added gate stats to audio input snapshot
- `BE/server/interpreter/interpreter_client.py`
  - added speech-start/speech-stop callbacks from realtime VAD events
- `BE/server/interpreter/event_publisher.py`
  - added optional `relay_focus` and `overlap` metadata on transcript/status payloads
- `BE/server/interpreter/meeting_config.py`
  - added prompt guardrail to relay only the assigned speaker and ignore overlap bleed
- `docs/backend/API_CONTRACT.md`
  - documented `blocked_due_to_overlap` status and optional overlap metadata
- `docs/backend/IMPLEMENTATION_STATE.md`
  - updated this implementation state.

### Degraded Behavior Chosen

- The runtime intentionally prefers fewer, cleaner relay outputs over attempting to translate every overlapping speaker at once.
- During overlap, secondary speakers are temporarily suppressed instead of being translated concurrently.
- This should reduce wrong-speaker relay, mixed transcripts, and overlapping BRSE audio from the virtual participant.
- Single-speaker path remains the same: input gate defaults enabled, focus is claimed on normal speech, and transcript/audio publish normally.

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests not modified.
- Lightweight checks run:
  - `python -m py_compile BE/server/interpreter/audio_input.py BE/server/interpreter/interpreter_client.py BE/server/interpreter/meeting_config.py BE/server/interpreter/event_publisher.py BE/server/interpreter/room_manager.py`
  - `git diff --check`

## Turn Update: 2026-05-02 MeetQ Production Domain Deploy (Kickoff)

- Time: 2026-05-02T03:20:40+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective Locked

- Configure single-server production deploy for `meetqapp.com` and LiveKit subdomain `rtc.meetqapp.com`.
- Keep FE public access on `https://meetqapp.com`, Gateway REST/WS behind Nginx, LiveKit signaling behind `wss://rtc.meetqapp.com`, and Redis/interpreter internal only.
- Preserve local dev behavior by isolating production compose/Nginx/LiveKit config where needed.

### Mandatory Read Status

- Read required docs:
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/LIVEKIT_SETUP.md`
  - `docs/backend/API_CONTRACT.md`
- Read required runtime/deploy files:
  - `docker-compose.yml`
  - `ops/livekit/livekit.yaml`
  - `BE/server/config.py`
  - `.env.example`
  - `BE/.env.example`
  - `BE/Dockerfile`
  - `FE/package.json`
  - `FE/vite.config.ts`
  - `FE/vite.config.js`
  - current FE API/WS URL resolution code
- Current finding:
  - existing root Compose is local-dev oriented and exposes Gateway `8000` plus LiveKit signaling `7880` directly.
  - no existing production Nginx config or FE Dockerfile was present.
  - backend currently returns relative share/WS URLs and uses `LIVEKIT_WS_URL_PUBLIC` for browser LiveKit URL.

### Initial Implementation Plan

- Add production Nginx config for `meetqapp.com` and `rtc.meetqapp.com`.
- Add isolated production compose topology with `nginx`, `fe`, `gateway`, `interpreter`, `livekit`, and `redis`, exposing only Nginx plus LiveKit media ports.
- Add FE container deploy files and make production API default same-origin while preserving local dev default.
- Add backend public URL settings so production responses can return `https://meetqapp.com` / `wss://meetqapp.com` and LiveKit `wss://rtc.meetqapp.com`.
- Add production LiveKit config with public media assumptions while leaving local LiveKit config intact.
- Sync `.env.example`, `BE/.env.example`, production deploy docs, then finalize this state entry.

### Final Sync: MeetQ Production Domain Deploy

- Time: 2026-05-02T03:26:05+07:00
- Final status: production deploy path configured for one-server `meetqapp.com` stack with Nginx reverse proxy.

### Production Routing Strategy

- Public domains:
  - `https://meetqapp.com/` -> `fe:80`
  - `https://meetqapp.com/api/...` -> `gateway:8000`
  - `wss://meetqapp.com/ws/...` -> `gateway:8000`
  - `wss://rtc.meetqapp.com` -> `livekit:7880`
- Internal services:
  - `gateway:8000` is internal only in production compose.
  - `fe:80` is internal only in production compose.
  - `redis:6379` is internal only.
  - `interpreter` has no public port.
  - `livekit:7880` signaling is internal and exposed only through Nginx on `rtc.meetqapp.com`.
- Public production ports:
  - `80/tcp`, `443/tcp` on `nginx`
  - `7881/tcp` LiveKit ICE TCP fallback
  - `50000-50100/udp` LiveKit WebRTC media

### Files Added

- `ops/nginx/meetqapp.conf`
  - Nginx server blocks for `meetqapp.com`, `www.meetqapp.com`, and `rtc.meetqapp.com`
  - `/api/` REST proxy to Gateway
  - `/ws/` WebSocket proxy to Gateway with upgrade headers and long timeouts
  - LiveKit signaling proxy on `rtc.meetqapp.com` with WebSocket upgrade headers
  - ACME challenge path and explicit certificate mount paths
- `docker-compose.prod.yml`
  - production-only topology with `nginx`, `fe`, `gateway`, `interpreter`, `livekit`, and `redis`
  - no public Gateway/FE/Redis/LiveKit-signaling ports
  - LiveKit media ports exposed
- `ops/livekit/livekit.prod.yaml`
  - production LiveKit config with `use_external_ip: true`, TCP fallback `7881`, and UDP range `50000-50100`
  - production keys supplied via `LIVEKIT_KEYS` from compose env
- `FE/Dockerfile`, `FE/nginx.conf`, `FE/.dockerignore`
  - build Vite app and serve static assets on internal Nginx
- `ops/certbot/www/.gitkeep`
  - ACME webroot mount scaffold
- `docs/backend/DEPLOY_PRODUCTION.md`
  - DNS, Cloudflare, firewall, SSL bootstrap, env, start command, and smoke-check notes

### Files Modified

- `BE/server/config.py`
  - added `PUBLIC_APP_URL`, `PUBLIC_GATEWAY_URL`, `PUBLIC_GATEWAY_WS_URL`
- `BE/server/service/gateway/room_service.py`
  - `share_url` now uses `PUBLIC_APP_URL`
  - join response `websocket.url` now uses public Gateway WS URL
  - `livekit.url` continues to use `LIVEKIT_WS_URL_PUBLIC`
- `FE/src/lib/api.ts`
  - production default API base URL is same-origin (`window.location.origin`)
  - local dev default remains `http://localhost:8000`
- `FE/src/vite-env.d.ts`
  - added `PROD` env typing
- `.env.example`
  - converted to production deploy template for `meetqapp.com`
  - includes `LIVEKIT_WS_URL_PUBLIC=wss://rtc.meetqapp.com`
  - includes `PUBLIC_APP_URL=https://meetqapp.com`
  - includes `PUBLIC_GATEWAY_URL=https://meetqapp.com`
  - includes `PUBLIC_GATEWAY_WS_URL=wss://meetqapp.com`
- `BE/.env.example`
  - added public URL keys and production comments for backend-local env usage
- `.gitignore`
  - keeps real `.env` files ignored while allowing `.env.example` templates to be tracked
- `BE/.gitignore`
  - keeps real backend `.env` files ignored while allowing `BE/.env.example` to be tracked
- `docker-compose.yml`
  - local-dev compose now passes public URL env defaults to Gateway without changing current public local ports
- `ops/livekit/livekit.yaml`
  - marked as local development config
- `docs/backend/GATEWAY_DESIGN.md`
  - env list synced with new public URL settings
- `docs/backend/LIVEKIT_SETUP.md`
  - documented production LiveKit public/internal URLs and prod config file
- `docs/backend/API_CONTRACT.md`
  - added production public URL assumptions for REST, Gateway WS, and LiveKit WS

### Production Response URLs

- Create-room response:
  - `join.share_url = https://meetqapp.com/rooms/{room_id}` in production.
- Join-room response:
  - `websocket.url = wss://meetqapp.com/ws/rooms/{room_id}?token=...` in production.
  - `livekit.url = wss://rtc.meetqapp.com` in production.

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests not modified.
- Lightweight checks run:
  - `docker compose --env-file .env.example -f docker-compose.prod.yml config`
  - `docker compose -f docker-compose.yml config`
  - Python syntax parse for `BE/server/config.py` and `BE/server/service/gateway/room_service.py`
  - `git diff --check`
- Nginx runtime syntax check deferred because local `nginx` binary is unavailable and production certificates are not present in this workspace.
- FE typecheck attempted with no emit; it stops on existing `LocalTrack/RemoteTrack.name` type errors in `FE/src/lib/livekit.ts`, unrelated to this deploy change.

## Turn Update: 2026-05-02 Telegram Room-Created Notification (Kickoff)

- Time: 2026-05-02T02:14:56+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective Locked

- Add backend Telegram channel notification when a meeting room is created successfully.
- Keep Telegram as an optional side effect: missing config or Telegram/network failures must not fail room creation.
- Keep backend/runtime room flows unchanged except for the room-created notification hook.

### Mandatory Read Status

- Read required docs:
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
- Read required backend files:
  - `BE/server/config.py`
  - `BE/server/service/gateway/api_rooms.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/models.py`
- Read related runtime/config files:
  - `BE/server/src/common/logging_utils.py`
  - `BE/server/service/gateway/main.py`
  - `BE/server/service/gateway/dependencies.py`
  - `BE/server/redis.py`
  - `BE/requirements.txt`
  - `.env.example`
  - `BE/.env.example`
  - `docker-compose.yml`
- Current finding: no existing `BE/server/integrations/` folder; create a small Telegram integration under that namespace.

### Initial Implementation Plan

- Add Telegram env/config keys to `BE/server/config.py`.
- Add `BE/server/integrations/telegram.py` with a small async `sendMessage` client using existing `httpx` dependency.
- Hook notification in `RoomService.create_room` after `store.create_room` succeeds.
- Sync `.env.example`, `BE/.env.example`, and `docker-compose.yml` for runtime usability.
- Final state update will list changed files, hook location, failure handling strategy, and testing deferred.

### Batch 1: Config, Integration Client, Create-Room Hook (Completed)

- Time: 2026-05-02T02:16:23+07:00
- Added Telegram config keys in `BE/server/config.py`:
  - `TELEGRAM_NOTIFICATIONS_ENABLED`
  - `TELEGRAM_NOTIFY_ROOM_CREATED`
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
  - `TELEGRAM_API_BASE_URL`
  - `TELEGRAM_REQUEST_TIMEOUT_SECONDS`
- Added `BE/server/integrations/telegram.py`:
  - async `TelegramNotifier` using `httpx.AsyncClient`
  - Bot API `sendMessage`
  - short timeout from config
  - safe skip when disabled or missing token/chat id
  - warning logs for HTTP/network/unexpected failures with `room_id`
- Hooked `RoomService.create_room` in `BE/server/service/gateway/room_service.py`:
  - notification scheduled only after `store.create_room` and room-created/virtual-participant publishes complete
  - schedule uses `asyncio.create_task` so Telegram does not block room creation response
  - task callback logs unexpected task failures
- Testing remains deferred per CODE-ONLY instruction.

### Batch 2: Env Runtime Sync (Completed)

- Time: 2026-05-02T02:16:52+07:00
- Synced Telegram env keys into:
  - `.env.example`
  - `BE/.env.example`
  - `docker-compose.yml` gateway service environment
- Actual local `.env` files were not edited.
- Testing remains deferred per CODE-ONLY instruction.

### Final Sync: Telegram Room-Created Notification

- Time: 2026-05-02T02:18:05+07:00
- Final status: backend Telegram room-created notification implemented.
- Telegram config keys added:
  - `TELEGRAM_NOTIFICATIONS_ENABLED=false` by default
  - `TELEGRAM_NOTIFY_ROOM_CREATED=true` by default
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
  - `TELEGRAM_API_BASE_URL=https://api.telegram.org`
  - `TELEGRAM_REQUEST_TIMEOUT_SECONDS=3`
- Files changed:
  - `BE/server/config.py`
  - `BE/server/integrations/__init__.py`
  - `BE/server/integrations/telegram.py`
  - `BE/server/service/gateway/room_service.py`
  - `.env.example`
  - `BE/.env.example`
  - `docker-compose.yml`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Create-room hook location:
  - `RoomService.create_room` schedules Telegram notification after `store.create_room`, `room.created` publish, and virtual BRSE participant publish have completed.
  - The notification is scheduled immediately before returning `CreateRoomResponse`.
- Notification content:
  - room id
  - meeting languages
  - BRSE enabled flag
  - created_at
  - expires_at
  - participant limit only when configured/non-empty
  - share path
  - creator fields are supported by the notifier but omitted by the current create-room API because creator metadata is not present on that path.
- Failure handling strategy:
  - disabled notifications skip without side effects
  - enabled but missing bot token/chat id skips safely and logs one warning
  - Telegram HTTP/network/unexpected failures are caught and logged with `room_id`
  - room creation response does not wait for or fail because of Telegram delivery
  - background notification tasks are tracked until completion and log unexpected task errors
- Testing deferred per instruction:
  - no tests run
  - no tests written
  - no tests changed
  - no runtime Telegram smoke call performed

### Follow-Up Fix: Legacy `src.*` Import Compatibility

- Time: 2026-05-02T02:26:22+07:00
- Runtime issue reported:
  - Docker gateway failed on startup with `ModuleNotFoundError: No module named 'src'`
  - Import chain: `server.service.gateway.main` -> `server.models` -> `server.meeting_modes` -> `src.common.lang`
- Fix applied:
  - added `BE/src/__init__.py` as a compatibility package
  - the package appends `BE/server/src` to `src.__path__`
  - existing `src.common.*`, `src.realtime.*`, and `src.fallback.*` imports can resolve without changing gateway/interpreter/CLI imports one by one
- Files changed in this follow-up:
  - `BE/src/__init__.py`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Testing deferred per instruction:
  - no tests run
  - no import smoke run

## Turn Update: 2026-05-01 Room Policy: 30-Min Duration + No Participant Cap (Final Sync)

- Time: 2026-05-01T20:22:41+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective Locked

- Change room meeting duration policy to 30 minutes (was 24h).
- Remove backend participant limit enforcement (was hard cap of 8).
- Ensure expired rooms reject new joins and do not spawn new BRSE runtimes.
- Keep all existing room flows (create/join/leave/chat/screen-share/BRSE/transcript) intact.

### Mandatory Read Status

- Read required docs: `API_CONTRACT.md`, `GATEWAY_DESIGN.md`, `IMPLEMENTATION_STATE.md`
- Read required backend files: `models.py`, `api_rooms.py`, `room_service.py`, `ws_endpoint.py`, `event_consumer.py`, `room_store.py`, `config.py`, `events.py`, `meeting_modes.py`
- Read interpreter lifecycle files: `daemon.py`, `room_manager.py`

### Room Expiry Strategy

- **Logical meeting expiry**: 30 minutes from room creation (`room_meeting_duration_seconds = 1800`)
- **Redis key retention TTL**: meeting duration + 5 minutes grace = 35 minutes (`room_meeting_duration_seconds + 300`)
  - Grace allows stale event cleanup, snapshot reads for recently-expired rooms, and consistent cleanup
- **Room JWT token TTL**: remains at 24h (`room_token_ttl_seconds = 86400`) — separate from meeting duration
  - JWT lifetime is longer because it covers reconnect/session scenarios; meeting expiry is enforced at the room state layer, not the JWT layer
- **Product-facing room validity**: 30 minutes. After `expires_at`, no new joins are allowed regardless of Redis key existence.

### Participant Limit Strategy

- **Backend enforcement**: removed. `participant_limit` field is now `Optional[int] = None` in models.
- **Behavior**: when `participant_limit` is `None` or `0`, backend does not enforce any participant cap.
- **Backward compatibility**: field is preserved in contract/response payloads as `null`. FE can interpret `null` as "no limit".
- **Config**: `ROOM_MAX_PARTICIPANTS = 0` (0 = no enforcement). Can be set > 0 to re-enable cap if needed.
- **Old validation removed**: `join_room` no longer raises `RoomFullError` when `participant_limit` is None.

### Room Expired Handling

- **Join room**: raises `RoomExpiredError` → API returns `410 room_expired`
- **WebSocket connect**: checks room expiry before accepting → close code `4410` "Room expired"
- **GET room**: still returns snapshot for expired rooms (useful for post-meeting history/debug)
- **Interpreter daemon**: does not spawn new BRSE runtime for expired rooms; terminates existing managers
- **Event**: `room.expired` event type added (`EventType.ROOM_EXPIRED`); can be broadcast by future background expiry sweeper (deferred to next turn)
- **Active sessions at expiry boundary**: connected participants continue until disconnect; backend does not force-close existing WS at the moment of expiry (practical strategy; FE-side expiry UI deferred)

### Runtime Cleanup Behavior

- Expired rooms do not spawn new interpreter runtime (`_is_room_expired()` check in daemon)
- If a room expires while runtime is active, runtime continues until natural teardown (participant leave, disconnect, or next gateway event check)
- Redis keys auto-expire via TTL (35 min) so no manual cleanup sweep is needed
- Room state transitions remain intact: created → active → empty → deleted (via TTL)

### Contract Compatibility

- `participant_limit` field kept in all response models as `Optional[int]`; value is `null` for new rooms
- `expires_at` field remains unchanged in shape; value now reflects 30-min duration instead of 24h
- New error code `room_expired` (HTTP 410) for join attempts on expired rooms
- New WS close code `4410` for WebSocket connections to expired rooms
- `room.expired` event type registered but active broadcast is deferred

### Files Changed

- `BE/server/config.py` — added `room_meeting_duration_seconds`, `room_max_participants`
- `BE/server/events.py` — added `ROOM_EXPIRED` event type
- `BE/server/models.py` — `participant_limit` → `Optional[int] = None`
- `BE/server/service/gateway/room_service.py` — 30-min expiry, room expiry check, removed participant cap enforcement
- `BE/server/service/gateway/api_rooms.py` — `RoomExpiredError` handling (410)
- `BE/server/service/gateway/ws_endpoint.py` — room expiry check on WS connect (4410)
- `BE/server/service/gateway/room_store.py` — default TTL updated to 2100 (35 min)
- `BE/server/service/gateway/main.py` — RoomStore TTL wired from config
- `BE/server/interpreter/daemon.py` — room expiry gate for BRSE runtime spawn
- `docs/backend/API_CONTRACT.md` — updated policy notes, examples, error codes
- `docs/backend/GATEWAY_DESIGN.md` — updated TTL, participant_limit, env vars, error cases
- `docs/backend/IMPLEMENTATION_STATE.md` — this entry

### Deferred Items

- `room.expired` broadcast to connected WS clients (background expiry sweeper task) — deferred to next turn
- FE-side room expiry UI handling — out of scope (backend only)
- Force-disconnect of active WS sessions at exact expiry moment — deferred (current strategy: let sessions naturally end)
- Testing — deferred per instruction (CODE-ONLY mode)

## Turn Update: 2026-05-01 BRSE Relay Quality Hardening (Kickoff)

- Time: 2026-05-01T20:01:44+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective Locked

- Improve backend/runtime BRSE relay quality without frontend changes or full-suite verification.
- Tighten BRSE interpreter role so the model relays only what the human speaker said.
- Reduce hallucination, assistant-like replies, over-paraphrase, stale route/context drift, and premature utterance cuts.
- Keep room-level `meeting_languages`, participant `language`, and `brse_enabled` as the runtime source of truth.

### Mandatory Read Status

- Read required docs:
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/API_CONTRACT.md`
- Read required backend/runtime files:
  - `BE/server/interpreter/meeting_config.py`
  - `BE/server/interpreter/interpreter_client.py`
  - `BE/server/interpreter/room_manager.py`
  - `BE/server/interpreter/output_router.py`
  - `BE/server/interpreter/audio_input.py`
  - `BE/server/interpreter/livekit_runtime.py`
  - `BE/src/common/lang.py`
  - `BE/src/realtime/client.py`
- Read related BRSE/runtime reuse files:
  - `BE/server/meeting_modes.py`
  - `BE/server/interpreter/translation_test_client.py`
  - `BE/server/interpreter/daemon.py`
  - `BE/server/interpreter/event_publisher.py`

### Initial Root Cause / Hypotheses

- Current BRSE prompt is directionally correct but still too permissive for live meeting relay; it does not make "relay the speech act, never answer/act on it" explicit enough per utterance.
- VAD currently uses a 620 ms silence window and 240 ms prefix padding, which can commit long multi-clause speech too early and lose leading context under jitter.
- Realtime conversation history is pruned only after responses complete; in-flight response cancellation can leave stale items until the next response, increasing role/context drift risk.
- Transcript state is keyed only by speaker, so late/delayed text or audio callbacks can attach to a newer utterance after barge-in or route changes.
- Output audio clear/reset behavior is useful for barge-in but needs better generation checks and observability to avoid stale chunks and hard-to-debug relay mismatches.

### Batch 1: Prompt + VAD/Buffer Tuning (Completed)

- Time: 2026-05-01T20:03:28+07:00
- Tightened BRSE instructions in `BE/server/interpreter/meeting_config.py`:
  - Explicitly defines BRSE AI as a relay/interpreter, not assistant/copilot/chatbot.
  - Requires relaying questions as questions and requests as requests, without answering or performing them.
  - Forbids adding/inventing facts, decisions, deadlines, owners, risks, causes, promises, requirements, or next steps.
  - Allows natural BRSE-style rephrasing only when intent, information, certainty, qualifiers, caveats, and business meaning remain unchanged.
  - Makes room `meeting_languages` authoritative and forbids inferring a different target language.
  - Requires text and spoken audio to contain the same relay content.
- Tuned utterance capture for longer meeting speech:
  - `threshold`: `0.42` -> `0.40`
  - `prefix_padding_ms`: `240` -> `320`
  - `silence_duration_ms`: `620` -> `840`
  - `INTERPRETER_INPUT_QUEUE_MAXSIZE`: `180` -> `420`
  - `INTERPRETER_INPUT_WARMUP_CHUNKS`: `32` -> `45`
  - `INTERPRETER_SEND_QUEUE_MAXSIZE`: `240` -> `420`
- Testing remains deferred per CODE-ONLY instruction.

### Batch 2: Routing Context + Response Lifecycle Guardrails (Completed)

- Time: 2026-05-01T20:09:38+07:00
- Tightened room-level language context in `BE/server/interpreter/room_manager.py`:
  - Runtime now treats room `meeting_languages` as required source of truth before routing.
  - If the room pair is missing/invalid, BRSE relay is paused with `missing_room_language_context` instead of silently falling back to the default `vi-ja` pair.
  - Route selection logs include room id, speaker id, speaker language, target language, fixed meeting pair, and audience ids.
- Added per-speaker runtime generation guards:
  - Each speaker runtime/reconfigure gets a generation id.
  - Transcript source/relay partial/final publish tasks now carry `(utterance_id, generation)` and drop stale tasks.
  - Audio delta/flush callbacks verify the current router and generation before publishing to LiveKit.
  - Final relay logging now includes utterance id, route, source/relay char counts, latency, audience count, and generation.
- Hardened `BE/server/interpreter/interpreter_client.py` response lifecycle:
  - Barge-in or route change now cancels in-flight response without using the CLI stdout path, prunes remembered conversation items, and suppresses stale response events.
  - Response events are dropped when they belong to cancelled/mismatched/no-longer-active response ids.
  - Conversation item ids from committed input buffers are remembered for pruning.
  - `response.audio_transcript.*` is used as text fallback when no `response.text.*` stream is emitted, improving text/audio consistency.
  - `playing` status is emitted only on first audio delta per response to reduce status churn.
  - Added timing logs for input commit, first relay text, first relay audio, and send queue drops.
- Improved output/runtime stability:
  - `BE/server/interpreter/output_router.py` now validates base64 audio chunks, exposes router stats in track descriptors, logs first relay audio frame, and records clear/reset/decode counters.
  - `BE/server/interpreter/livekit_runtime.py` now filters out screen-share audio publications so BRSE subscribes only to human microphone audio.
- Testing remains deferred per CODE-ONLY instruction; no tests added or run.

### Final Sync: BRSE Relay Quality Hardening

- Time: 2026-05-01T20:10:45+07:00
- Final status: backend/runtime BRSE relay quality hardening completed for this turn.
- Files changed:
  - `BE/server/interpreter/meeting_config.py`
  - `BE/server/interpreter/interpreter_client.py`
  - `BE/server/interpreter/room_manager.py`
  - `BE/server/interpreter/output_router.py`
  - `BE/server/interpreter/livekit_runtime.py`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Root cause/hypotheses addressed:
  - Prompt role was not strict enough against assistant-style answering or added business meaning.
  - VAD/buffers were biased toward faster commits and smaller queues, increasing long-utterance cut risk.
  - Runtime could let late response/transcript/audio callbacks affect newer utterance state after barge-in or route changes.
  - Room language context needed a fail-closed guard instead of implicit fallback routing.
- Prompt/instruction changes applied:
  - BRSE AI is explicitly a relay/interpreter, not assistant/copilot/chatbot.
  - Questions, requests, instructions, advice requests, analysis requests, and decisions must be relayed as speech acts, not answered or executed.
  - Natural BRSE-style wording is allowed only when intent, facts, certainty, qualifiers, caveats, and constraints stay faithful.
  - Room pair is authoritative and text/audio output must match.
- VAD/buffering/runtime tuning applied:
  - More tolerant VAD for longer utterances: lower threshold, larger prefix padding, longer silence duration.
  - Larger input/warmup/send queues to reduce drops under jitter/backpressure.
  - Per-speaker generation + utterance guards for transcript/audio publishing.
  - Realtime response cancellation/pruning and stale response id suppression on barge-in/route change.
  - Audio transcript fallback for relay text when audio output exists but text stream does not.
  - Output router base64 validation, stats, and first-frame/clear/reset observability.
  - LiveKit runtime filters out screen-share audio and subscribes only to human mic audio.
- Verification performed:
  - `python -m py_compile BE/server/interpreter/meeting_config.py BE/server/interpreter/interpreter_client.py BE/server/interpreter/room_manager.py BE/server/interpreter/output_router.py BE/server/interpreter/livekit_runtime.py`
  - `git diff --check -- BE/server/interpreter/meeting_config.py BE/server/interpreter/interpreter_client.py BE/server/interpreter/room_manager.py BE/server/interpreter/output_router.py BE/server/interpreter/livekit_runtime.py docs/backend/IMPLEMENTATION_STATE.md`
- Testing deferred per instruction:
  - no full test suite run
  - no tests written
  - no tests changed
  - no runtime LiveKit/OpenAI smoke run

## Turn Update: 2026-05-01 BRSE Mode Toggle Backend Support Reconcile (Kickoff)

- Time: 2026-05-01T19:05:21+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective Locked

- Reconcile and complete backend/runtime support for room-level `brse_enabled: bool`.
- Keep create/join/snapshot/WS room contract explicit for BRSE ON/OFF.
- Ensure interpreter runtime is gated by `brse_enabled=true` and cleaned up when mode switches OFF.
- Do not run tests, write tests, edit tests, or perform runtime verification this turn.

### Mandatory Read Status

- Read required backend docs:
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Read required backend/runtime source:
  - `BE/server/models.py`
  - `BE/server/service/gateway/api_rooms.py`
  - `BE/server/service/gateway/ws_endpoint.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/interpreter/daemon.py`
  - `BE/server/interpreter/room_manager.py`
  - `BE/server/interpreter/livekit_runtime.py`
  - `BE/server/interpreter/output_router.py`
- Read related room state/store/runtime files:
  - `BE/server/service/gateway/room_store.py`
  - `BE/server/meeting_modes.py`
  - `BE/server/events.py`
  - `BE/server/interpreter/event_publisher.py`
- Read FE contract references only:
  - `FE/src/types/api.ts`
  - `FE/src/types/ws.ts`

### Current Findings

- Worktree already contains the main backend BRSE toggle implementation across models, gateway, room store, interpreter daemon, and backend docs.
- Current default behavior is explicit `brse_enabled=true` when create-room omits the field.
- Live toggle is present through REST `POST /api/rooms/{room_id}/brse/enable|disable` and WS `room.brse.enable|room.brse.disable`.
- Host model is not present in backend room state; current live-toggle permission remains active authenticated human room participant.

### Batch 1: Runtime Cleanup Hardening (Completed)

- Tightened `RoomInterpreterManager.stop()` cleanup for BRSE OFF/runtime termination.
- Stop now tears down the union of all tracked speaker runtime state:
  - audio streams
  - audio inputs
  - output routers
  - realtime clients
  - background tasks
  - routing/transcript state
- Stop then clears manager-level participant/routing/transcript maps before disconnecting the BRSE LiveKit participant.
- File changed in this batch:
  - `BE/server/interpreter/room_manager.py`

### Final Sync: BRSE Mode Toggle Backend Support Reconcile

- Time: 2026-05-01T19:07:54+07:00
- Final status: backend/runtime BRSE toggle support is present and reconciled.
- BRSE toggle model:
  - persisted room source of truth: `brse_enabled: bool`
  - default behavior: omitted create-room field defaults explicitly to `true`
  - `brse_enabled=false` is normal human-only meeting mode with no BRSE virtual participant in snapshots
- Create/join/snapshot contract:
  - create-room accepts `brse_enabled`
  - create-room response exposes `room.brse_enabled`
  - join response room payload exposes `room.brse_enabled`
  - REST snapshot and initial WS `room.snapshot` expose `room.brse_enabled`
- Live toggle implemented:
  - REST `POST /api/rooms/{room_id}/brse/enable`
  - REST `POST /api/rooms/{room_id}/brse/disable`
  - WS `room.brse.enable`
  - WS `room.brse.disable`
  - broadcast `room.brse_updated`
- Permission rule:
  - no backend host role/model exists in current `BE/server`
  - current toggle permission is active authenticated human participant with matching session
  - stale session, disconnected participant, missing participant, and virtual participant are rejected
- ON -> OFF cleanup path:
  - room state sets `brse_enabled=false`
  - room meta clears `virtual_participants`
  - room transcript list is cleared and snapshots suppress BRSE transcripts while OFF
  - Gateway broadcasts `room.brse_updated`
  - Gateway broadcasts `participant.left` for `brse_ai`
  - Interpreter daemon terminates the room manager on `room.brse_updated`
  - `RoomInterpreterManager.stop()` tears down clients, tasks, audio inputs, output routers, routing/transcript maps, and disconnects the BRSE LiveKit participant
- OFF -> ON spawn path:
  - room state sets `brse_enabled=true`
  - room meta rebuilds `brse_ai` virtual participant
  - Gateway broadcasts `room.brse_updated`
  - Gateway broadcasts `participant.joined` for `brse_ai`
  - Interpreter daemon spawns a fresh room manager from the current room snapshot
- Files changed for this BRSE toggle work:
  - `BE/server/meeting_modes.py`
  - `BE/server/models.py`
  - `BE/server/events.py`
  - `BE/server/service/gateway/room_store.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/service/gateway/api_rooms.py`
  - `BE/server/service/gateway/ws_endpoint.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/interpreter/daemon.py`
  - `BE/server/interpreter/room_manager.py`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Testing deferred per instruction:
  - no tests written
  - no tests changed
  - no tests run
  - no runtime smoke/verification run

## Turn Update: 2026-05-01 BRSE Mode Toggle Backend Support (Kickoff)

- Time: 2026-05-01T15:34:20+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective Locked

- Add explicit room-level `brse_enabled: bool` state so rooms can run either BRSE relay mode or normal human-only meeting mode.
- Create-room must accept explicit `brse_enabled` input and expose the selected state in REST room responses, join response, and WS `room.snapshot`.
- Interpreter daemon/runtime must only spawn BRSE LiveKit/OpenAI runtime when `brse_enabled = true`.
- Prefer live toggle support in this turn if it can stay scoped to backend/runtime paths.

### Mandatory Read Status

- Read required backend contract/design/state files:
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Read required backend/runtime source files:
  - `BE/server/models.py`
  - `BE/server/service/gateway/api_rooms.py`
  - `BE/server/service/gateway/ws_endpoint.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/interpreter/daemon.py`
  - `BE/server/interpreter/room_manager.py`
  - `BE/server/interpreter/livekit_runtime.py`
  - `BE/server/interpreter/output_router.py`
- Read related room state/store files:
  - `BE/server/service/gateway/room_store.py`
  - `BE/server/meeting_modes.py`
  - `BE/server/events.py`
  - `BE/server/interpreter/event_publisher.py`
- Read FE contract reference only:
  - `FE/src/types/api.ts`
  - `FE/src/types/ws.ts`

### Initial Implementation Choice

- Default behavior selected for compatibility: `brse_enabled = true` when create-room payload omits the field.
- OFF mode will keep normal room/create/join/leave/chat/screen-share flow but will not materialize `brse_ai`, spawn interpreter runtime, publish BRSE transcript/audio, or retain stale BRSE participant state.
- Host permission model is not present in current backend room state; if live toggle is implemented this turn, it will use existing room-token participant auth and note the host-permission assumption.

### Batch 1: Room State + Gateway Contract (Completed)

- Added `brse_enabled` to persisted `RoomState`, room response models, join response room payload, REST room snapshot room payload, and initial WS `room.snapshot` via existing room serialization.
- Create-room now accepts `brse_enabled`; omitted value explicitly defaults to `true` for backward compatibility with existing BRSE-first product behavior.
- Create-room only materializes/publishes the virtual `brse_ai` participant when `brse_enabled = true`.
- Room snapshot/store projection now suppresses virtual BRSE participants and recent interpreter transcripts when `brse_enabled = false`.
- Added backend event type `room.brse_updated` and service-level toggle path scaffold.
- Files changed so far:
  - `BE/server/meeting_modes.py`
  - `BE/server/models.py`
  - `BE/server/events.py`
  - `BE/server/service/gateway/room_store.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/service/gateway/api_rooms.py`
  - `BE/server/service/gateway/ws_endpoint.py`
  - `BE/server/service/gateway/event_consumer.py`

### Batch 2: Runtime Gating + Live Toggle Path (Completed)

- Interpreter daemon now gates every spawn/sync path on `snapshot.room.brse_enabled`.
- `brse_enabled = false` prevents manager spawn on human `participant.joined` and terminates any existing room interpreter manager.
- `room.brse_updated` live toggle event is implemented:
  - ON -> OFF terminates `RoomInterpreterManager`, which tears down speaker clients, audio inputs, output routers, and disconnects the BRSE LiveKit participant through existing `manager.stop()` / `LiveKitRuntime.disconnect()` paths.
  - OFF -> ON spawns a fresh manager from the current room snapshot and rematerializes the virtual BRSE participant event.
- Gateway toggle path updates room state, broadcasts `room.brse_updated`, publishes consistent `participant.joined` / `participant.left` for `brse_ai`, and clears recent interpreter transcripts on disable.
- Live toggle contract implemented in backend:
  - REST: `POST /api/rooms/{room_id}/brse/enable`
  - REST: `POST /api/rooms/{room_id}/brse/disable`
  - WS: `room.brse.enable`
  - WS: `room.brse.disable`
- Permission rule for this branch: no host model is present in backend room state, so any authenticated active human room participant may toggle BRSE mode; virtual/disconnected/stale-session participants are rejected.

### Batch 3: Contract Docs Sync (Completed)

- Time: 2026-05-01T15:40:59+07:00
- Updated backend contract/design docs to expose BRSE toggle semantics:
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
- Contract additions:
  - create-room request/response includes `brse_enabled`
  - get/join/WS snapshot room payload includes `brse_enabled`
  - REST live toggle endpoints documented
  - WS live toggle messages documented
  - `room.brse_updated` event documented with minimum payload: `room_id`, `brse_enabled`, `timestamp`
- Testing remains deferred; no tests or runtime smoke runs executed.

### Final Sync: BRSE Mode Toggle Backend Support

- Time: 2026-05-01T15:41:28+07:00
- Final status: backend/runtime support implemented for create-time and live BRSE mode toggle.
- BRSE toggle model selected:
  - persisted room-level source of truth is `brse_enabled: bool`
  - default is explicit `true` when create-room omits the field
  - `brse_enabled=false` means normal human-only meeting mode
- Live toggle implemented:
  - REST `POST /api/rooms/{room_id}/brse/enable`
  - REST `POST /api/rooms/{room_id}/brse/disable`
  - WS `room.brse.enable`
  - WS `room.brse.disable`
  - broadcast event `room.brse_updated`
- Permission assumption:
  - no host role/model exists in current backend room state
  - current live-toggle permission is active authenticated human participant only
  - future host model should tighten this to host-only
- ON -> OFF cleanup path:
  - room state sets `brse_enabled=false`
  - `virtual_participants` cleared from room meta/snapshot
  - recent interpreter transcripts cleared from room state and suppressed in snapshots
  - `room.brse_updated` broadcast
  - `participant.left` broadcast for `brse_ai`
  - interpreter daemon terminates the room manager, shutting down clients, audio inputs, output routers, and disconnecting the BRSE LiveKit participant
- OFF -> ON spawn path:
  - room state sets `brse_enabled=true`
  - BRSE virtual participant is rebuilt in room meta/snapshot
  - `room.brse_updated` broadcast
  - `participant.joined` broadcast for `brse_ai`
  - interpreter daemon spawns a fresh manager from current room snapshot
- Files changed:
  - `BE/server/meeting_modes.py`
  - `BE/server/models.py`
  - `BE/server/events.py`
  - `BE/server/service/gateway/room_store.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/service/gateway/api_rooms.py`
  - `BE/server/service/gateway/ws_endpoint.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/interpreter/daemon.py`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Testing deferred per instruction:
  - no tests written
  - no tests run
  - no runtime smoke run

## Turn Update: 2026-05-01 Chat End-to-End Debug Reopen (Kickoff)

- Time: 2026-05-01T15:23:33+07:00
- Mode: CODE-ONLY
- Testing scope: minimal targeted verification only; no full test suite; no new tests

### Objective Locked

- Re-debug room chat end-to-end because chat still does not work.
- Trace FE `chat.send` envelope, gateway websocket/session handling, room-state persistence, `chat.message` broadcast, and FE snapshot/realtime hydration.
- Fix only chat-path regressions or mismatches without redesigning gateway, room lifecycle, transcript, BRSE/audio, screen-share, host, or moderation flows.

### Mandatory Read Status

- Read backend contract/state/runtime files: `docs/backend/API_CONTRACT.md`, `docs/backend/IMPLEMENTATION_STATE.md`, `BE/server/models.py`, `BE/server/service/gateway/ws_endpoint.py`, `BE/server/service/gateway/ws_hub.py`, `BE/server/service/gateway/room_service.py`, `BE/server/service/gateway/event_consumer.py`, `BE/server/service/gateway/room_store.py`.
- Read FE chat/runtime reference files: `FE/src/lib/ws.ts`, `FE/src/lib/api.ts`, `FE/src/features/room/useMeetingRoom.ts`, `FE/src/pages/RoomPage.tsx`, `FE/src/types/ws.ts`, `FE/src/types/api.ts`, `FE/src/components/ChatPanel.tsx`.

### Current Trace Hypothesis

- Backend currently exposes the expected gateway path: `chat.send` -> `RoomService.send_chat_message(...)` -> Redis `room:{room_id}:chat` -> gateway-control `chat.message` -> room websocket broadcast.
- Suspected live mismatch is FE send transport, because current FE code sends chat via LiveKit data topic `brse.chat` instead of the backend gateway `chat.send` path.
- Root cause will be finalized after targeted trace and minimal verification.

## Turn Update: 2026-05-01 Chat End-to-End Debug Reopen (Final Sync)

- Time: 2026-05-01T15:27:25+07:00
- Status: backend chat path verified; no backend source change required this turn

### Root Cause Confirmed

- Real current root cause was on FE send transport/lifecycle, not the current backend chat handler.
- FE was sending room chat through LiveKit data topic `brse.chat`, so backend gateway never received `chat.send`.
- As a result, backend room state could not persist the message, gateway control did not emit canonical `chat.message`, and later snapshots could not hydrate those chat messages.

### Backend Trace Result

- Inbound websocket:
  - `BE/server/service/gateway/ws_endpoint.py` has `elif msg_type == "chat.send"`.
  - It extracts `payload.text`, uses authenticated `participant_id`, and uses the current websocket participant `session_id`.
- Validation/session guard:
  - `BE/server/service/gateway/room_service.py::send_chat_message(...)` trims text, rejects non-string/empty/too-long text, rejects stale session mismatch, disconnected/missing participants, and virtual participants.
- Persist:
  - `BE/server/service/gateway/room_store.py::append_chat_message(...)` appends to Redis key `room:{room_id}:chat`, trims to `chat_limit`, and refreshes TTL.
- Broadcast:
  - `RoomService.send_chat_message(...)` publishes `EventType.CHAT_MESSAGE`.
  - `BE/server/events.py` defines `CHAT_MESSAGE = "chat.message"`.
  - `BE/server/service/gateway/event_consumer.py` broadcasts gateway-control messages to all active room sockets.
- Snapshot hydrate:
  - `BE/server/models.py` includes `recent_messages` in `SnapshotData` and `RoomSnapshotResponse`.
  - REST room snapshot, join response, and initial WS `room.snapshot` can project `recent_messages`.

### Backend Files

- Backend source files inspected/verified: `BE/server/models.py`, `BE/server/events.py`, `BE/server/service/gateway/ws_endpoint.py`, `BE/server/service/gateway/ws_hub.py`, `BE/server/service/gateway/room_service.py`, `BE/server/service/gateway/event_consumer.py`, `BE/server/service/gateway/room_store.py`.
- Backend source files changed this turn: none.
- Backend state doc updated: `docs/backend/IMPLEMENTATION_STATE.md`.

### Frontend Compatibility Fix Summary

- FE now sends gateway websocket `chat.send` instead of LiveKit data for room chat.
- FE pending message reconciliation uses backend `client_event_id` so canonical `chat.message` replaces the optimistic row.
- FE chat availability now follows gateway websocket connected state.

### Minimal Verification

- `python -m py_compile BE/server/models.py BE/server/events.py BE/server/service/gateway/ws_endpoint.py BE/server/service/gateway/ws_hub.py BE/server/service/gateway/room_service.py BE/server/service/gateway/event_consumer.py BE/server/service/gateway/room_store.py` passed.
- FE type check was run with `npx tsc -b --pretty false`; chat-related type issue was fixed, but the command still fails on existing non-chat `FE/src/lib/livekit.ts` `track.name` type errors.

### Deferred

- No full test suite and no new tests, per instruction.
- No runtime browser/manual room smoke was run in this turn.
- Existing non-chat LiveKit type errors remain deferred.

## Turn Update: 2026-05-01 Platform Language Expansion (Kickoff)

- Time: 2026-05-01T13:49:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Objective Locked

- Expand officially supported backend/platform languages from `vi,en,ja` to `vi,en,ja,zh,ko,fr,es`.
- Update room contract, join/set-language validation, room snapshot/event serialization, interpreter/BRSE runtime language metadata, and translation-test validation/runtime paths.
- Preserve existing room flow compatibility for `vi`, `en`, and `ja`.

### Locked Scope

- Source-of-truth language constants and validation across `BE/server/*` and `BE/src/common/lang.py`
- Room create/join/ws language acceptance and room `supported_languages` / `meeting_languages`
- Interpreter/BRSE routing metadata, language-name rendering, and prompt/instruction builders
- Translation-test/fallback/realtime guards that still assume only `vi/en/ja`
- Runtime-facing docs sync, especially this state file

### Initial Findings

- Gateway room models and `meeting_modes.py` still hardcode supported meeting languages to `vi/en/ja`.
- `BE/src/common/lang.py` still limits supported codes, language names, and default routing/instruction text to `vi/en/ja`.
- Interpreter room manager still rejects speaker languages outside `vi/en/ja`.
- Translation-test REST validation still hardcodes `vi/en/ja`.

### Planned Batch Order

- Batch 1: introduce shared 7-language source-of-truth and widen room/test-session validation and schemas.
- Batch 2: widen interpreter/BRSE metadata, routing guards, and prompt/instruction rendering for new codes.
- Batch 3: sync backend docs/contracts/state to reflect official 7-language support and note remaining runtime limitations if any.

## Turn Update: 2026-05-01 Platform Language Expansion (Post-Batch 1)

- Time: 2026-05-01T13:54:22+07:00
- Status: source-of-truth language set and primary gateway validation/state expansion completed

### Language Set Added

- Newly added platform-supported codes: `zh`, `ko`, `fr`, `es`
- Effective non-auto room/platform set is now `vi,en,ja,zh,ko,fr,es`

### Backend Areas Expanded

- `BE/src/common/lang.py`
  - widened supported code constants and language-name metadata
  - added default target mapping entries for `zh/ko/fr/es`
  - widened heuristic language detection path so new codes do not fall through unknown metadata handling
- `BE/server/meeting_modes.py`
  - widened room-level supported meeting language source-of-truth to 7 languages
  - preserved default fallback room pair as `vi` + `ja` for compatibility
- `BE/server/models.py`
  - widened `Language` / `MeetingLanguage` literals
  - room state and response models now serialize 7-language `supported_languages`
  - room create input now defaults to the legacy room pair when omitted instead of forcing empty invalid state
- `BE/server/service/gateway/room_service.py`
  - room create validation now accepts meeting-language pairs from the 7-language set
  - empty/omitted meeting-language input falls back to the legacy default pair for backward-compatible room creation
- `BE/server/service/gateway/api_test_sessions.py`
  - translation-test validation now accepts explicit `zh/ko/fr/es` source/target codes

### Validation / Routing Notes

- Room create/join/set-language state path is now ready to accept the expanded language set at the model and meeting-language validation layer.
- Translation-test REST validation no longer hardcodes `vi/en/ja`.

### Testing

- Deferred by instruction; no tests executed.

## Turn Update: 2026-05-01 Backend Chat Runtime Fix (Final Tail Sync)

- Time: 2026-05-01T15:18:06+07:00
- Final state file sync before turn end.
- Backend chat root cause fixed: `chat.send` was missing in WS dispatch, chat state/model were missing, `chat.message` was never published, and snapshots had no `recent_messages`.
- Files updated this turn: `BE/server/models.py`, `BE/server/events.py`, `BE/server/service/gateway/room_store.py`, `BE/server/service/gateway/room_service.py`, `BE/server/service/gateway/ws_endpoint.py`, `docs/backend/IMPLEMENTATION_STATE.md`.
- Recent chat strategy: Redis room list `room:{room_id}:chat`, trimmed to 100 messages, TTL refreshed with room state and deleted with room cleanup.
- Event path: WS `chat.send` -> `RoomService.send_chat_message(...)` -> Redis append -> gateway control publish `chat.message` -> existing consumer room broadcast.
- Session safety: Redis participant state is re-read and current `session_id` must match; disconnected/missing/virtual participants cannot send chat.
- Duplicate handling: inbound envelope `event_id` is stored as `client_event_id`; repeated event ids in recent history do not append/publish a second message.
- Testing deferred by instruction; no tests, smoke runs, or verification commands executed.

## Turn Update: 2026-05-01 Backend Chat Runtime Fix (Final Sync)

- Time: 2026-05-01T15:18:06+07:00
- Scope confirmation: backend chat runtime path now supports `chat.send` -> validate -> persist recent room chat -> broadcast canonical `chat.message` -> hydrate snapshots with `recent_messages`.

### Files Updated

- `BE/server/models.py`
- `BE/server/events.py`
- `BE/server/service/gateway/room_store.py`
- `BE/server/service/gateway/room_service.py`
- `BE/server/service/gateway/ws_endpoint.py`
- `docs/backend/IMPLEMENTATION_STATE.md`

### Root Cause / Fix Summary

- Root cause was missing backend chat runtime wiring:
  - no `chat.send` WS handler
  - no chat message model
  - no Redis recent chat state
  - no `chat.message` publication/broadcast path
  - no `recent_messages` snapshot projection
- Fixed with a dedicated `ChatMessage` model and `RoomService.send_chat_message(...)` runtime handler.

### Validation / Session Safety

- `chat.send` payload must contain string `payload.text`.
- Text is trimmed; empty messages are rejected with `empty_chat_message`.
- Text length is capped at 2000 characters with `chat_message_too_long`.
- Handler re-reads Redis participant state and requires matching current `session_id`.
- Missing/disconnected participants are rejected and cannot append/broadcast chat.
- Virtual participants are rejected from human chat send path.

### Broadcast / Snapshot / State Strategy

- Successful sends append to Redis list `room:{room_id}:chat`.
- List is trimmed to the recent 100 messages and shares room TTL refresh/delete cleanup.
- Service publishes `chat.message` on the existing gateway control channel.
- Existing `event_consumer.py` gateway-control fanout broadcasts to every active socket in the room, including sender.
- REST room snapshot, join response snapshot, and initial WS `room.snapshot` include `recent_messages`.

### Duplicate Handling

- The inbound envelope `event_id` is stored as `client_event_id` on the recent message.
- If the same event id is seen again while still in recent room history, the service returns the existing message and does not append or publish another `chat.message`.

### Testing

- Deferred by instruction; no tests, smoke runs, or verification commands executed.

## Turn Update: 2026-05-01 Platform Language Expansion (Post-Batch 2)

- Time: 2026-05-01T13:57:41+07:00
- Status: interpreter/BRSE runtime metadata and routing guards widened for the 7-language platform set

### Runtime / Routing Areas Expanded

- `BE/server/interpreter/meeting_config.py`
  - BRSE prompt context now resolves human-readable names for `zh`, `ko`, `fr`, `es`
  - instruction text no longer assumes only a bilingual `vi/en/ja` world
- `BE/server/interpreter/room_manager.py`
  - speaker-language routing guard now accepts the full supported room language set
  - deterministic relay mapping continues to derive target language from room `meeting_languages` instead of a hardcoded 3-language branch
  - room-context sync rejects invalid meeting-language pairs outside the supported 7-language set
- `BE/src/realtime/client.py`
  - runtime-facing descriptions now reflect the expanded language support set

### Remaining Runtime Limitation

- Non-room auto-detection paths in `BE/src/common/lang.py` are still heuristic/best-effort for `zh/ko/fr/es`; this turn expands code-path support and metadata, but does not add pair-specific quality tuning.

### Testing

- Deferred by instruction; no tests executed.

## Turn Update: 2026-05-01 Platform Language Expansion (Final Sync)

- Time: 2026-05-01T13:57:41+07:00
- Scope confirmation: backend/runtime contract now officially recognizes `vi,en,ja,zh,ko,fr,es` across room validation, room snapshots/events, BRSE/interpreter prompt metadata, and translation-test validation.

### Files Updated

- `BE/src/common/lang.py`
- `BE/src/realtime/client.py`
- `BE/server/meeting_modes.py`
- `BE/server/models.py`
- `BE/server/service/gateway/room_service.py`
- `BE/server/service/gateway/api_test_sessions.py`
- `BE/server/interpreter/meeting_config.py`
- `BE/server/interpreter/room_manager.py`
- `docs/backend/API_CONTRACT.md`
- `docs/backend/GATEWAY_DESIGN.md`
- `docs/backend/INTERPRETER_DESIGN.md`
- `docs/backend/IMPLEMENTATION_STATE.md`

### Validation / Contract / State Coverage

- Room create validation now accepts meeting-language pairs drawn from `vi,en,ja,zh,ko,fr,es`, with omitted pair defaulting to legacy `["vi", "ja"]` for compatibility.
- Join-room language validation and participant language update validation continue to enforce membership in room `meeting_languages`, which can now be any valid pair from the 7-language platform set.
- Room state, participant state, transcript event models, and room snapshot serialization now accept the new language codes without schema rejection.
- `supported_languages` contract examples/docs now reflect `["vi", "en", "ja", "zh", "ko", "fr", "es"]`.

### Runtime Limitations Still Explicit

- This turn does not tune language-pair-specific model quality or bespoke prompt styles for `zh/ko/fr/es`; it focuses on end-to-end backend/runtime support, validation, serialization, and routing compatibility.

### Testing

- Deferred by instruction; no tests executed.

## Turn Update: 2026-05-01 BRSE Relay Audio InvalidState Stabilization (Kickoff)

- Time: 2026-05-01T18:05:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Objective Locked

- Fix BRSE relay audio output instability for long utterances causing LiveKit `InvalidState - failed to capture frame`.
- Harden `OutputRouter` lifecycle so `capture_frame` never races with reset/clear/unpublish/cleanup on stale source state.
- Keep transcript path unchanged while improving audio output robustness.

### Root Cause Hypothesis (Current)

- `OutputRouter` capture path currently lacks strict per-route serialization.
- `capture_pcm`/`flush`/`clear_queue`/`_reset_track` can interleave via concurrent tasks (`response.audio.delta`, `response.audio.done`, status transitions), allowing `capture_frame` on source state that is already resetting or released.
- Long utterances increase chunk count and amplify this race window.

### Planned Fix Scope

- Primary: `BE/server/interpreter/output_router.py`
- Minimal touch outside router only if required by type/lifecycle plumbing.

## Turn Update: 2026-05-01 BRSE Relay Audio InvalidState Stabilization (Post-Major)

- Time: 2026-05-01T18:20:00+07:00
- Status: core router lifecycle hardening completed

### Root Cause Confirmation (This Turn)

- Confirmed `OutputRouter` had no strict per-route serialization for concurrent operations coming from runtime callbacks:
  - `response.audio.delta` -> `capture_pcm`
  - `response.audio.done` -> `flush`
  - status transition/cancel path -> `clear_queue`
  - failure path -> track reset/recreate
- Under longer utterances (more chunks), these operations can overlap and hit stale/invalid `rtc.AudioSource` state, producing repeated `InvalidState - failed to capture frame`.

### Fix Strategy Applied

- Added per-router async operation lock (`_op_lock`) to serialize critical output lifecycle operations.
- Introduced explicit source generation tracking for observability and stale-state safety.
- Moved track/source ensure path to locked internal method (`_ensure_track_locked`) and increased source queue budget (`queue_size_ms=6000`) for longer responses.
- Reworked capture failure handling:
  - mark current state inactive immediately on capture failure
  - execute reset/recreate in serialized locked path (`_reset_track_locked`)
  - block continued capture on stale state
- Hardened clear-queue behavior:
  - buffer clear + deferred source queue clear guarded by lock
  - avoids direct unsynchronized `source.clear_queue()` racing capture path
- Hardened shutdown path to serialize release with in-flight operations.

### Output Lifecycle / Guards Added

- Serialized operations: ensure, capture, flush, reset, clear-queue apply, shutdown.
- Stale-state guard in capture path now checks active/current state before frame push.
- Reset path now guarantees release of old state before creating a new state and prevents chunks from writing into released source.

### Files Updated (This Turn)

- `BE/server/interpreter/output_router.py`
- `docs/backend/IMPLEMENTATION_STATE.md`

## Turn Update: 2026-05-01 BRSE Relay Audio InvalidState Stabilization (Final Sync)

- Time: 2026-05-01T18:24:00+07:00
- Scope confirmation: BRSE relay audio output lifecycle hardened primarily in `OutputRouter` without changing transcript path behavior.
- Reset/recreate strategy is now serialized and state-safe, reducing repeated `InvalidState` loops under long utterance chunk streams.
- Added observability for source generation and reset reasons to ease next-round runtime diagnosis.
- Testing status: deferred by instruction (no tests executed).

## Turn Update: 2026-05-01 Meeting Language Pair Semantics (Kickoff)

- Time: 2026-05-01T16:05:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Objective Locked

- Add explicit room-level meeting language pair (exactly 2 languages) into create/get/join/ws contracts and runtime state.
- Enforce participant language validation against room meeting pair on join and language updates.
- Drive BRSE/interpreter target-language routing context from room-level pair instead of generic supported-language set.

### Planned Change Scope

- `BE/server/models.py`
- `BE/server/service/gateway/api_rooms.py`
- `BE/server/service/gateway/room_service.py`
- `BE/server/service/gateway/ws_endpoint.py`
- `BE/server/service/gateway/event_consumer.py` (only if contract fan-out adjustments needed)
- `BE/server/service/gateway/room_store.py` (if snapshot/state compatibility updates needed)
- `BE/server/interpreter/room_manager.py`
- `BE/server/interpreter/interpreter_client.py`
- `BE/server/interpreter/meeting_config.py`
- docs contract/design sync files

## Turn Update: 2026-05-01 Meeting Language Pair Semantics (Post-Major)

- Time: 2026-05-01T16:30:00+07:00
- Status: core implementation completed

### Backend Contract + State Changes

- Added explicit `meeting_languages` (room-level pair) to backend room models and room responses/snapshots.
- Added create-room payload contract with `meeting_languages` input and strict validation (exactly 2, distinct, subset of `vi|en|ja`).
- Kept `supported_languages` as capability set for compatibility.

### Gateway Behavior Changes

- `POST /api/rooms` now accepts body `{ "meeting_languages": [...] }` and returns `invalid_meeting_languages` on invalid pair.
- Join flow now validates participant `language` against room `meeting_languages` (rejects `auto` and non-pair language).
- WebSocket `set_language` now validates against room `meeting_languages` and returns pair-aware error message.
- Room snapshot projection now includes `meeting_languages` from persisted `RoomState`.

### Interpreter Runtime Changes

- Interpreter manager now receives and stores room-level `meeting_languages` context from room snapshot.
- Routing resolution now computes relay target from room pair mapping ("language còn lại trong pair") instead of static global map.
- If speaker language is outside room pair, runtime publishes deterministic routing error and does not build invalid route.
- Realtime interpreter instructions now include explicit room pair context text for BRSE relay behavior.

### Docs Synced

- `docs/backend/API_CONTRACT.md`
- `docs/backend/GATEWAY_DESIGN.md`
- `docs/backend/INTERPRETER_DESIGN.md`

## Turn Update: 2026-05-01 Meeting Language Pair Semantics (Final Sync)

- Time: 2026-05-01T16:36:00+07:00
- Scope confirmation: explicit room-level meeting pair semantics implemented across models, create/join/ws validation, and interpreter routing context.
- `supported_languages` preserved; `meeting_languages` is authoritative for participant language acceptance and BRSE route direction.
- Testing status: deferred by instruction (no test execution).

## Turn Update: 2026-05-01 Room Create 500 Hotfix (JSON Serialization)

- Time: 2026-05-01T15:26:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Root Cause

- `POST /api/rooms` failed with 500 because `RoomService.create_room()` publishes `participant.joined` for virtual participants.
- `room.virtual_participants` is typed as `List[ParticipantSnapshot]`, so `_publish(...)` received Pydantic objects.
- `_publish` used `json.dumps(envelope)` directly, causing `TypeError: Object of type ParticipantSnapshot is not JSON serializable`.

### Fix Applied

- Updated `BE/server/service/gateway/room_service.py`:
  - `_publish(...)` now accepts `payload: Any` and applies `fastapi.encoders.jsonable_encoder(payload)` before building/publishing envelope.
  - This normalizes Pydantic payloads to JSON-safe dict/list primitives and keeps existing event semantics unchanged.

### Impact

- Hotfix unblocks room creation path and Redis event publish path for virtual participant payloads.
- No feature redesign, no test changes, no FE changes.

## Turn Update: 2026-05-01 Interpreter Startup Hotfix (Kickoff)

- Time: 2026-05-01T15:05:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Root Cause (Locked)

- Interpreter container crash-loop is caused by a Python indentation regression in `BE/server/interpreter/livekit_runtime.py`.
- In `LiveKitRuntime.connect()`, `_sync_existing_audio_tracks()` is dedented outside method body, causing `IndentationError: unexpected indent` at import/runtime startup.

### Plan (Current Turn)

- Repair indentation/block structure in `connect()` so method body is structurally valid.
- Re-scan nearby methods in the same file (`disconnect`, callbacks, `_sync_existing_audio_tracks`) for adjacent block regressions.
- Keep semantics unchanged except minimal structural fixes needed to unblock interpreter startup.

## Turn Update: 2026-05-01 Interpreter Startup Hotfix (Post-Major)

- Time: 2026-05-01T15:10:00+07:00
- Status: implementation completed

### Files Updated

- `BE/server/interpreter/livekit_runtime.py`
- `docs/backend/IMPLEMENTATION_STATE.md`

### Structural Fix Applied

- Fixed indentation regression in `LiveKitRuntime.connect()`:
  - restored `_sync_existing_audio_tracks()` into the `connect()` method body.
  - method statement order is now structurally correct:
    - `await self.room.connect(...)`
    - `self._sync_existing_audio_tracks()`
    - `logger.info(...)`

### Nearby Block Scan (Same File)

- Reviewed adjacent blocks for similar indentation/structure breakage:
  - `async def connect`
  - `async def disconnect`
  - callbacks `_on_track_subscribed`, `_on_track_published`, `_on_track_unsubscribed`, `_on_participant_disconnected`
  - helper `_sync_existing_audio_tracks`
- No additional indentation regressions found in those blocks.

### Impact

- This is a hotfix to unblock interpreter module import/startup path that was failing with `IndentationError`.
- No feature redesign or behavior expansion in this turn.
- Testing deferred by instruction (no test execution).

## Turn Update: 2026-05-01 Interpreter Startup Hotfix (Final Sync)

- Time: 2026-05-01T15:12:00+07:00
- Scope confirmation: backend runtime hotfix only.
- Startup blocker addressed: `BE/server/interpreter/livekit_runtime.py` indentation in `connect()` fixed.
- Testing status: deferred by instruction.

## Turn Update: 2026-05-01 Stale/Ghost Participant Cleanup (Kickoff)

- Time: 2026-05-01T14:05:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Root Cause (Locked)

- Room websocket disconnect path can remove socket references but still leave participant record in Redis participant map, so snapshots/participant lists can retain stale entries.
- Leave semantics are spread across paths; REST leave is the strongest path while disconnect/stale paths can be weaker or delayed.
- Old session disconnect can race with reconnect; without strict session ownership checks, delayed cleanup can remove newer active presence.

### Implementation Plan (Current Turn)

- Unify all leave/disconnect/stale cleanup into one canonical, idempotent room-service path.
- Ensure websocket disconnect and dead-socket failures trigger the same cleanup path as REST leave.
- Enforce session-safe cleanup guard (cleanup only when session matches active participant session).
- Ensure participant removal is destructive in room state (remove stale participant from Redis participant map), not only status flip.
- Keep interpreter/BRSE cleanup synchronized through participant lifecycle event path.
- Reconfirm stale fallback (heartbeat/last_seen timeout) and wire to unified cleanup path.

### Batch B1: Unified Cleanup + Redis Ghost Removal (Completed)

- Unified cleanup path confirmed and reinforced:
  - REST `DELETE /leave` -> `RoomService.cleanup_participant(...)`
  - WS disconnect/failure -> `WSHub.on_connection_lost(...)` -> same `cleanup_participant(...)`
  - stale timeout sweeper -> same WS lost callback -> same `cleanup_participant(...)`
- Session-safety strategy active:
  - destructive cleanup only runs when provided `session_id` matches active participant session in room state.
  - delayed disconnect from old session is ignored for destructive path.
- Root ghost fix implemented:
  - participant cleanup now removes participant entry from Redis participant hash (destructive removal), not only status flag update.
  - snapshot projection skips legacy disconnected rows to avoid old ghost entries surfacing.
- Idempotency hardened:
  - repeated cleanup on an already-disconnected legacy row now performs silent purge without duplicate `participant.left` publish.
- WS lifecycle hardening:
  - websocket endpoint now uses `finally` disconnect hook so unexpected loop exit still triggers unified cleanup.

### Files Updated In Batch B1

- `BE/server/service/gateway/room_store.py`
- `BE/server/service/gateway/room_service.py`
- `BE/server/service/gateway/ws_endpoint.py`

### Batch B2: Lifecycle Consistency Notes (Completed)

- Room snapshot consistency:
  - participant snapshot projection now excludes disconnected rows to prevent legacy ghost participants from resurfacing.
  - canonical cleanup path now removes participant row from Redis hash, ensuring subsequent snapshots remain clean.
- `participant.left` live event path:
  - still emitted from unified cleanup path only.
  - includes contract-required fields (`participant_id`, `left_at`) and diagnostic fields (`session_id`, `reason`) for disconnect root-cause observability.
- WSHub dead-socket handling:
  - send/broadcast failures continue to drop socket references and trigger same cleanup callback path.
- Interpreter/BRSE dependency cleanup:
  - interpreter daemon consumes `participant.left` and invokes `remove_participant(...)`; with unified disconnect cleanup this path now also runs when tab/browser/network dies without REST leave.

### Batch B3: Final Turn Sync (Completed)

- stale participant root cause (final):
  - stale/ghost participant came from non-destructive disconnect handling path (socket drop without guaranteed participant-row removal from Redis participant map).
- unified cleanup path (final):
  - REST leave, WS disconnect, send/broadcast socket failure, and stale timeout now converge on one canonical cleanup method in room service.
- session-safety strategy (final):
  - cleanup enforces active-session ownership when session id is available; old delayed disconnect events cannot remove new active reconnect session.
- heartbeat/last_seen strategy (final):
  - kept in runtime: hub-level stale timeout sweeper + per-message activity touch + Redis `last_seen_at` updates via presence touch path.
- room snapshot consistency (final):
  - disconnected legacy rows are filtered out from snapshot projection.
  - current cleanup removes participant row entirely from Redis participant hash.
- participant.left contract behavior (final):
  - event emitted once from unified path; includes required payload fields and diagnostic metadata (`session_id`, `reason`) while preserving contract compatibility.
- files updated in this turn:
  - `BE/server/service/gateway/room_store.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/service/gateway/ws_endpoint.py`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- testing status:
  - deferred by instruction (no test execution, no verification run).

## Last Updated

- Time: 2026-05-01T13:22:00+07:00
- Agent: Codex
- Branch: develop

## Current Mode

- CODE-ONLY
- Testing deferred: yes

---

## Current Objective

- FIX backend BRSE runtime so `brse_ai` participant actually operates in live meeting rooms.
- Fix room mode/runtime routing so BRSE relay runtime materializes reliably.
- Fix BRSE ingest/output runtime path for transcript + audio relay to room-wide contract.
- Align gateway/interpreter Redis channel wiring and WS fan-out projection when needed.
- Keep CODE-ONLY constraints: no tests, no test edits, no verification run.

## Work Log (Current Turn)

### Batch A0: Mandatory Read + Root Cause Lock (Completed)

- Mandatory files re-read before code changes (gateway/interpreter/runtime/models/docs).
- Confirmed BRSE architecture is partially implemented but runtime has critical reliability gaps.
- Root cause candidates locked for fix in this turn:
  - Redis pub/sub channel wiring is hard-coded and not environment-configurable across gateway/interpreter runtime.
  - BRSE runtime creation is gated by audience presence (`audience_ids`) so runtime can silently not materialize.
  - LiveKit runtime ingestion path is brittle for pre-existing publications / callback-loop handling.
  - Virtual BRSE participant exists in room snapshot but lacks explicit join materialization event on room creation.
- Next step: apply backend/runtime patches only, then update this state file again before finishing.

### Batch A1: BRSE Runtime Path Fixes (Completed)

- Redis pub/sub wiring made environment-configurable (gateway + interpreter):
  - added settings keys:
    - `redis_channel_gateway_control`
    - `redis_channel_interpreter_events`
  - updated publish/subscribe paths in:
    - `BE/server/service/gateway/room_service.py`
    - `BE/server/service/gateway/event_consumer.py`
    - `BE/server/interpreter/event_publisher.py`
    - `BE/server/interpreter/daemon.py`
- BRSE participant materialization improved:
  - room creation now emits explicit `participant.joined` for virtual BRSE participant(s), not snapshot-only presence.
- BRSE runtime materialization gating fixed:
  - removed strict `audience_ids` non-empty requirement in `RoomInterpreterManager._build_routing_resolution(...)`.
  - BRSE runtime now starts for active mapped speaker route even when audience list is temporarily empty.
- LiveKit ingest path hardened in interpreter runtime:
  - bind audio stream creation to stable runtime loop.
  - add tolerant handling for `track_published` to force subscribe on human audio publications.
  - sync existing remote audio publications right after room connect to avoid missing already-published mic tracks.
  - add defensive error handling for callback failures to avoid silent ingest break.

### Batch A2: Completion Sync (Completed)

- Backend-only runtime/code path updates completed.
- No tests executed, no test files modified, no verification commands run (per instruction).
- Required state file updated at kickoff and at completion for this BRSE-fix turn.

## Work Log (This Turn)

### Batch 0: Mandatory Read + Screen Share Strategy Lock

- Read required files before coding:
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `BE/server/models.py`
  - `BE/server/service/gateway/api_rooms.py`
  - `BE/server/service/gateway/ws_endpoint.py`
  - `BE/server/service/gateway/ws_hub.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/interpreter/livekit_runtime.py`
  - FE reference only:
    - `FE/src/types/ws.ts`
    - `FE/src/types/livekit.ts`
    - `FE/src/features/room/useMeetingRoom.ts`
- Strategy locked:
  - Extend participant state/snapshot with explicit screen-share fields (not hidden in free-form metadata only).
  - Add dedicated room events `screen_share.started` and `screen_share.stopped` for FE usability.
  - Keep `participant.updated` in sync when screen-share state changes for backward compatibility.
  - Support state sync through both:
    - WS client messages (`screen_share.start`, `screen_share.stop`)
    - REST endpoints (`POST /api/rooms/{room_id}/screen-share/start|stop`)
  - Preserve multi-share-capable data model (per-participant state), no hard single-share enforcement.
  - Ensure cleanup clears screen-share state on participant leave/disconnect/stale timeout.
- Testing remains deferred by instruction.

### Batch 1: Screen Share State + Service Lifecycle (Completed)

- Extended shared models in `BE/server/models.py`:
  - added `ScreenShareTrackInfo`.
  - added `ParticipantState.is_screen_sharing` and `ParticipantState.screen_share`.
  - added same fields to `ParticipantSnapshot` for snapshot contract parity.
  - added DTOs: `ScreenShareStartRequest`, `ScreenShareStateResponse`.
- Extended event vocabulary in `BE/server/events.py`:
  - `screen_share.started`
  - `screen_share.stopped`
- Extended snapshot projection in `BE/server/service/gateway/room_store.py`:
  - participant snapshot now includes screen-share fields.
- Implemented service lifecycle in `BE/server/service/gateway/room_service.py`:
  - `start_screen_share(...)`
  - `stop_screen_share(...)`
  - both publish `participant.updated` plus dedicated screen-share events.
  - idempotent behavior for repeated start/stop.

### Batch 2: Signaling Entry Points + Stale Cleanup Paths (Completed)

- Added REST signaling endpoints in `BE/server/service/gateway/api_rooms.py`:
  - `POST /api/rooms/{room_id}/screen-share/start`
  - `POST /api/rooms/{room_id}/screen-share/stop`
  - both room-token authenticated via existing dependency and session-aware.
- Added WS signaling handlers in `BE/server/service/gateway/ws_endpoint.py`:
  - `screen_share.start`
  - `screen_share.stop`
  - returns `error` envelope on session mismatch / participant invalid.
- Strengthened stale cleanup in `BE/server/service/gateway/event_consumer.py`:
  - on `participant.media_disconnected`, gateway now also attempts `stop_screen_share(...)`.
- Participant disconnect cleanup in service now proactively clears active screen-share state before final leave mutation.

### Batch 3: Backend Contract Docs Sync (Completed)

- Updated `docs/backend/API_CONTRACT.md` with screen-share addendum:
  - participant state fields in snapshot/events.
  - REST start/stop request-response examples.
  - WS client message and server broadcast event examples.
- Updated `docs/backend/GATEWAY_DESIGN.md` with runtime notes:
  - explicit screen-share state model.
  - signaling paths (REST + WS).
  - stale cleanup behavior and lifecycle consistency.

### Batch 4: Finalization State Sync (Completed)

- Required state-file updates performed after major implementation batches and at end of turn.
- No tests executed, no test files touched, per explicit instruction.
- Final hardening in this batch: normalize unexpected `source` values to `screen_share` in service layer to keep DTO/model validation stable.

## Architecture Decision Locked In

- Default meeting mode for room runtime in this turn: `brse_relay`
- Interpreter mode for room runtime in this turn: `brse_participant`
- Virtual participant identity in backend contract:
  - `participant_id = brse_ai`
  - `display_name = BRSE AI`
  - `kind = virtual_brse`
- LiveKit runtime strategy:
  - human participants still publish original audio directly to LiveKit
  - interpreter runtime joins as the BRSE participant and subscribes to all human mic tracks
  - BRSE relay audio is published as canonical BRSE participant track(s), not per-listener private tracks

## BRSE Output Language Strategy

- Strategy chosen for this batch: deterministic room-level speaker-language map
- Implemented pair in this turn:
  - `vi -> ja`
  - `ja -> vi`
- Scope note:
  - `en` remains an allowed room language in shared models/contracts
  - BRSE relay target mapping is intentionally locked to the primary `vi <-> ja` bridge for now
  - architecture will be shaped so the map can be extended later without reviving per-listener routing

## Runtime Paths To Change

- Bypass old per-listener runtime assumptions in:
  - `BE/server/interpreter/room_manager.py`
  - `BE/server/interpreter/output_router.py`
  - `BE/server/interpreter/livekit_runtime.py`
  - `BE/server/interpreter/event_publisher.py`
- Extend gateway/snapshot contract in:
  - `BE/server/models.py`
  - `BE/server/service/gateway/room_store.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/service/gateway/ws_endpoint.py`
- Update BRSE relay prompt/instructions in:
  - `BE/server/interpreter/meeting_config.py`
  - `BE/server/interpreter/interpreter_client.py`

## Contract Assumptions For FE

- Room snapshot will expose room-level mode fields for BRSE relay.
- Participant list will include a virtual BRSE participant with explicit non-human metadata.
- Transcript events for BRSE relay will be broadcast room-wide and include:
  - original speaker identity
  - BRSE participant identity
  - `source_text`
  - `brse_text`
  - `src_lang`
  - `tgt_lang`
  - partial/final state
- Old listener-private translated audio is no longer the authoritative meeting output in BRSE rooms.
- FE changes are out of scope in this turn; backend contract will carry enough metadata for later FE alignment.

## Work Log

### Batch 0: Stale Participant Cleanup Kickoff (In Progress)

- Re-read required design + contract + runtime files before code changes:
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `BE/server/service/gateway/ws_endpoint.py`
  - `BE/server/service/gateway/ws_hub.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/models.py`
  - `BE/server/redis.py`
  - `BE/server/interpreter/room_manager.py`
- Root cause identified:
  - websocket disconnect currently only removes in-memory socket (`WSHub.disconnect`) but does not invoke room-state participant leave cleanup.
  - `RoomService.leave_room` is not session-aware; delayed cleanup from stale socket can remove a newer reconnect session.
  - No stale websocket fallback cleanup path (heartbeat/last_seen timeout) exists in gateway runtime.
- Plan locked for this turn:
  - add unified participant disconnect/leave service path with optional session ownership guard.
  - wire websocket disconnect and send-failure cleanup to the same idempotent service path.
  - add participant last_seen tracking and stale session sweeper in websocket hub.
  - keep testing deferred per instruction.

### Batch 1: Unified Leave + Session-Safe WS Cleanup (Completed)

- Core stale participant root cause fixed:
  - `ws_endpoint` disconnect path no longer only removes in-memory websocket; it now triggers room-state cleanup via shared service path.
  - `ws_hub` send-failure/broadcast-failure cleanup now also routes into the same participant cleanup flow.
- Unified cleanup method implemented in gateway service:
  - added `RoomService.cleanup_participant(room_id, participant_id, session_id, reason)` as the canonical leave/disconnect handler.
  - `RoomService.leave_room(...)` now delegates to this core method.
  - idempotent behavior:
    - missing participant -> no-op
    - already disconnected -> no-op
    - repeated cleanup -> no duplicate state mutation
- Session-safety strategy implemented:
  - cleanup only applies when provided `session_id` matches participant's current room state session.
  - old websocket/session cleanup is ignored if participant session has moved.
  - REST `/leave` now forwards claim `session_id` into leave flow.
- Redis room-state consistency updates:
  - participant state now carries and updates `ws_connected` + `last_seen_at`.
  - disconnect cleanup sets `status=disconnected`, `ws_connected=false`, `left_at`, and `last_seen_at` atomically in same patch path.
  - snapshots now include these presence fields.
- Participant left broadcast contract behavior:
  - `participant.left` is emitted only from shared cleanup path.
  - payload now includes `participant_id`, `session_id`, `left_at`, `reason` for downstream consumers.
- Interpreter dependency cleanup path confirmed:
  - interpreter daemon already consumes `participant.left` and removes participant runtime via `manager.remove_participant(...)`.
  - with unified WS cleanup publishing `participant.left`, abrupt tab/browser close now flows into interpreter recompute/cleanup as well.
- Heartbeat/stale fallback implemented:
  - `ws_hub` now tracks `last_seen_monotonic` per active connection.
  - inbound websocket messages touch connection activity and update participant `last_seen_at` in Redis.
  - background sweeper closes stale sockets on timeout and triggers same shared cleanup path.
  - new settings:
    - `ws_stale_timeout_seconds` (default 90)
    - `ws_stale_sweep_interval_seconds` (default 15)
- Testing remains deferred per CODE-ONLY instruction.

### Batch 2: Lifecycle Hardening + Finalization (Completed)

- Room lifecycle consistency hardened:
  - join flow now transitions room to `active` when previous state is `created` or `empty`.
  - this keeps room-empty lifecycle coherent after last-participant disconnect and later rejoin.
- Store helper consistency:
  - `mark_participant_left` now also clears websocket presence (`ws_connected=false`) and updates `last_seen_at`.
- WS endpoint readiness guard:
  - websocket route now requires `room_store` initialized before accepting handshake because session ownership validation depends on store reads.

## Stale Participant Fix Summary (This Turn)

- Stale participant root cause:
  - abrupt tab/browser close path only removed websocket in memory but did not always remove participant from Redis-backed room state.
- Cleanup paths added/updated:
  - REST `/leave` -> `RoomService.cleanup_participant(...)`
  - websocket disconnect -> `WSHub` connection-lost callback -> same `cleanup_participant(...)`
  - websocket send/broadcast failure -> same callback path
  - stale websocket timeout sweep -> same callback path
- Session-safety strategy:
  - cleanup requires session ownership match when session id is available.
  - delayed stale disconnect from old session cannot remove newer session state.
- Heartbeat / last_seen usage:
  - yes, implemented.
  - participant state now tracks `last_seen_at` in Redis.
  - WS hub tracks in-memory monotonic activity and sweeps stale connections on timeout.
  - inbound websocket messages refresh both in-memory last-seen and Redis `last_seen_at`.
- Broadcast behavior:
  - `participant.left` now emitted from one shared idempotent cleanup method to avoid duplicate/fragmented leave semantics.
- Interpreter dependency cleanup:
  - unchanged consumer path, but now reliably triggered because WS-based cleanup publishes `participant.left` even when REST leave is missing.

## Deferred Verification

- No tests were run in this turn (explicitly deferred by instruction: CODE-ONLY, no test/verification execution).

### Batch 0: Mandatory Read + Migration Plan

- Read required architecture, contract, gateway, interpreter, runtime, and FE reference files.
- Confirmed current implementation is still `translated_audio_first`.
- Confirmed current interpreter runtime is keyed by speaker + listener-target semantics and private LiveKit tracks.
- Confirmed current websocket transcript visibility is listener-scoped for translated events and must be widened for BRSE relay.

### Batch 1: Shared Models + Gateway State

- Added shared backend mode helpers in `BE/server/meeting_modes.py`.
- Room state now carries:
  - `meeting_mode = brse_relay`
  - `interpreter_mode = brse_participant`
  - `virtual_participants`
  - BRSE audio routing metadata and relay language map
- Gateway snapshot/store now merges the BRSE virtual participant into `participants`.
- Human join-limit and room-empty logic now use human-only participant counting so BRSE does not consume capacity or keep rooms alive by itself.
- Transcript visibility rules now treat `relay` transcripts as room-wide, not listener-private.

### Batch 2: Interpreter Runtime Rewrite

- `LiveKitRuntime` now joins the room as the BRSE participant identity instead of a generic per-room interpreter identity.
- `RoomInterpreterManager` no longer resolves runtime by per-listener target sets.
- New runtime routing is:
  - `speaker + source_language -> deterministic bridge target language`
  - runtime only starts when there is at least one human audience participant for that target language
- `OutputRouter` no longer publishes private listener tracks.
- BRSE relay audio is now published as canonical BRSE participant track name:
  - `brse::{speaker_id}::{src_lang}::{tgt_lang}`
- `event_publisher` now emits room-wide BRSE relay transcript payloads with:
  - `kind = relay`
  - `original_speaker`
  - `brse_participant`
  - `relay_target`
  - `brse_text`
  - BRSE audio descriptor metadata
- Interpreter prompt/instructions were changed from literal translator posture to BRSE relay posture:
  - natural interpreted restatement allowed
  - no answering on behalf of speaker
  - no adding facts or business logic

### Batch 3: Contract Doc Sync

- Added update notes at the top of:
  - `docs/architecture.md`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/INTERPRETER_DESIGN.md`
- These notes explicitly mark old per-listener translated-audio sections as historical/legacy context and point current readers to BRSE relay semantics.

## Files Changed This Turn

- `docs/backend/IMPLEMENTATION_STATE.md`
- `docs/architecture.md`
- `docs/backend/API_CONTRACT.md`
- `docs/backend/GATEWAY_DESIGN.md`
- `docs/backend/INTERPRETER_DESIGN.md`
- `BE/server/meeting_modes.py`
- `BE/server/models.py`
- `BE/server/service/gateway/room_store.py`
- `BE/server/service/gateway/room_service.py`
- `BE/server/service/gateway/event_consumer.py`
- `BE/server/service/gateway/livekit_tokens.py`
- `BE/server/interpreter/daemon.py`
- `BE/server/interpreter/meeting_config.py`
- `BE/server/interpreter/livekit_runtime.py`
- `BE/server/interpreter/output_router.py`
- `BE/server/interpreter/event_publisher.py`
- `BE/server/interpreter/room_manager.py`

## Per-Listener Path Bypass

- Bypassed as authoritative meeting output in BRSE mode:
  - listener-scoped routing resolution in `BE/server/interpreter/room_manager.py`
  - listener-private track publish/unpublish and subscription permissions in `BE/server/interpreter/output_router.py`
  - listener-private translated transcript fan-out semantics in `BE/server/service/gateway/event_consumer.py`
- Backward-compatible fields such as `listener_id`, `listener_ids`, and `translated_text` may still appear in some payload shapes where useful, but BRSE relay mode no longer depends on them for core runtime semantics.

## Current FE Contract Assumptions

- FE should treat human audio from LiveKit as canonical original audio.
- FE should treat BRSE audio as supplemental relay audio coming from a virtual participant.
- Snapshot participants now include explicit non-human metadata:
  - `kind`
  - `is_virtual`
  - `livekit_identity`
  - `metadata`
- Room payload now includes:
  - `meeting_mode`
  - `interpreter_mode`
  - updated `audio_routing`
- Relay transcript payloads are room-wide and include both the original human speaker and BRSE participant references.
- Current batch does not include FE code changes, so any FE logic still hard-coded to old per-listener track naming will need follow-up alignment against the new backend contract.

## Deferred Testing

- Per instruction, no tests, smoke runs, or runtime verification will be executed in this turn.

## Turn Update: 2026-05-01 Backend Chat Runtime Fix (Kickoff)

- Time: 2026-05-01T15:15:12+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Objective Locked

- Fix room chat end-to-end on backend runtime path only.
- Support `chat.send` inbound WS messages, persist recent chat in room Redis state, broadcast canonical `chat.message`, and hydrate snapshots with `recent_messages`.
- Preserve existing create/join/leave, websocket lifecycle, transcript/BRSE, and screen-share flows.

### Mandatory Read Status

- Read backend contract/design/state and primary runtime files:
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/GATEWAY_DESIGN.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `BE/server/models.py`
  - `BE/server/service/gateway/ws_endpoint.py`
  - `BE/server/service/gateway/ws_hub.py`
  - `BE/server/service/gateway/room_service.py`
  - `BE/server/service/gateway/event_consumer.py`
  - `BE/server/service/gateway/room_store.py`
- Read FE contract reference only:
  - `FE/src/lib/ws.ts`
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/types/ws.ts`
  - `FE/src/types/api.ts`

### Root Cause Confirmed

- Backend has no `chat.send` handler in `BE/server/service/gateway/ws_endpoint.py`.
- Backend has no stable chat message model in `BE/server/models.py`.
- Room Redis state has no recent chat list/key and snapshots only include `recent_transcripts`.
- No runtime path publishes/broadcasts `chat.message`, so FE optimistic chat is never reconciled by a canonical backend event.

### Planned Runtime Fix

- Add `ChatMessage` model and include `recent_messages` in REST/join/WS snapshot models.
- Add Redis room-state chat list in `RoomStore`, trimmed to a bounded recent window and covered by the existing room TTL refresh/delete lifecycle.
- Add `RoomService.send_chat_message(...)` with trim, empty/length validation, active participant/session validation, persist, and publish `chat.message`.
- Wire `chat.send` in WS endpoint and return usable `error` envelopes for invalid payload/session/participant failures.

## Turn Update: 2026-05-01 Backend Chat Runtime Fix (Post-Batch 1)

- Time: 2026-05-01T15:16:47+07:00
- Status: core backend chat runtime path implemented

### Root Cause Fixed

- Added missing inbound WS `chat.send` dispatch in `BE/server/service/gateway/ws_endpoint.py`.
- Added missing stable `ChatMessage` backend model in `BE/server/models.py`.
- Added missing room-scoped recent chat persistence in `BE/server/service/gateway/room_store.py`.
- Added missing chat service handler and canonical `chat.message` publication in `BE/server/service/gateway/room_service.py`.

### Inbound / Outbound Event Path

- Inbound:
  - browser sends WS envelope `type = chat.send`
  - `ws_endpoint.py` extracts `payload.text`
  - `RoomService.send_chat_message(...)` validates text and session-owned participant state
- Outbound:
  - service appends the canonical message to room Redis state
  - service publishes `chat.message` to the existing gateway control channel
  - `event_consumer.py` existing gateway-control broadcast path fans it out to all sockets in the room, including sender

### State Strategy

- Recent chat is stored as Redis list key `room:{room_id}:chat`.
- Messages are appended oldest-to-newest with `RPUSH` and trimmed with `LTRIM` to a bounded recent window.
- Existing room TTL refresh now also refreshes the chat key.
- Existing room delete now removes the chat key.

### Snapshot Hydration

- `SnapshotData` and `RoomSnapshotResponse` now include `recent_messages`.
- REST room snapshot, join response snapshot, and initial WS `room.snapshot` can hydrate the FE chat panel from Redis recent chat history.

### Testing

- Deferred by instruction; no tests executed.

## Turn Update: 2026-05-01 Backend Chat Runtime Fix (Final End Sync)

- Time: 2026-05-01T15:18:06+07:00
- Final state file sync before turn end.
- Backend chat root cause fixed: `chat.send` was missing in WS dispatch, chat state/model were missing, `chat.message` was never published, and snapshots had no `recent_messages`.
- Files updated this turn: `BE/server/models.py`, `BE/server/events.py`, `BE/server/service/gateway/room_store.py`, `BE/server/service/gateway/room_service.py`, `BE/server/service/gateway/ws_endpoint.py`, `docs/backend/IMPLEMENTATION_STATE.md`.
- Recent chat strategy: Redis room list `room:{room_id}:chat`, trimmed to 100 messages, TTL refreshed with room state and deleted with room cleanup.
- Event path: WS `chat.send` -> `RoomService.send_chat_message(...)` -> Redis append -> gateway control publish `chat.message` -> existing consumer room broadcast.
- Session safety: Redis participant state is re-read and current `session_id` must match; disconnected/missing/virtual participants cannot send chat.
- Duplicate handling: inbound envelope `event_id` is stored as `client_event_id`; repeated event ids in recent history do not append/publish a second message.
- Testing deferred by instruction; no tests, smoke runs, or verification commands executed.
