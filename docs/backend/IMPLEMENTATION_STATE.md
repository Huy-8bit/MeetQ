# Backend Implementation State

## Turn Update: 2026-05-01 Room Create 500 Hotfix (JSON Serialization)

- Time: 2026-05-01T15:26:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Root Cause

- `POST /api/rooms` failed with 500 because `RoomService.create_room()` publishes `participant.joined` for virtual participants.
- `room.virtual_participants` is typed as `List[ParticipantSnapshot]`, so `_publish(...)` received Pydantic objects.
- `_publish` used `json.dumps(envelope)` directly, causing `TypeError: Object of type ParticipantSnapshot is not JSON serializable`.

### Fix Applied

- Updated `BE/server/gateway/room_service.py`:
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

- `BE/server/gateway/room_store.py`
- `BE/server/gateway/room_service.py`
- `BE/server/gateway/ws_endpoint.py`

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
  - `BE/server/gateway/room_store.py`
  - `BE/server/gateway/room_service.py`
  - `BE/server/gateway/ws_endpoint.py`
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
    - `BE/server/gateway/room_service.py`
    - `BE/server/gateway/event_consumer.py`
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
  - `BE/server/gateway/api_rooms.py`
  - `BE/server/gateway/ws_endpoint.py`
  - `BE/server/gateway/ws_hub.py`
  - `BE/server/gateway/event_consumer.py`
  - `BE/server/gateway/room_service.py`
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
- Extended snapshot projection in `BE/server/gateway/room_store.py`:
  - participant snapshot now includes screen-share fields.
- Implemented service lifecycle in `BE/server/gateway/room_service.py`:
  - `start_screen_share(...)`
  - `stop_screen_share(...)`
  - both publish `participant.updated` plus dedicated screen-share events.
  - idempotent behavior for repeated start/stop.

### Batch 2: Signaling Entry Points + Stale Cleanup Paths (Completed)

- Added REST signaling endpoints in `BE/server/gateway/api_rooms.py`:
  - `POST /api/rooms/{room_id}/screen-share/start`
  - `POST /api/rooms/{room_id}/screen-share/stop`
  - both room-token authenticated via existing dependency and session-aware.
- Added WS signaling handlers in `BE/server/gateway/ws_endpoint.py`:
  - `screen_share.start`
  - `screen_share.stop`
  - returns `error` envelope on session mismatch / participant invalid.
- Strengthened stale cleanup in `BE/server/gateway/event_consumer.py`:
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
  - `BE/server/gateway/room_store.py`
  - `BE/server/gateway/room_service.py`
  - `BE/server/gateway/event_consumer.py`
  - `BE/server/gateway/ws_endpoint.py`
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
  - `BE/server/gateway/ws_endpoint.py`
  - `BE/server/gateway/ws_hub.py`
  - `BE/server/gateway/room_service.py`
  - `BE/server/gateway/event_consumer.py`
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
- `BE/server/gateway/room_store.py`
- `BE/server/gateway/room_service.py`
- `BE/server/gateway/event_consumer.py`
- `BE/server/gateway/livekit_tokens.py`
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
  - listener-private translated transcript fan-out semantics in `BE/server/gateway/event_consumer.py`
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
