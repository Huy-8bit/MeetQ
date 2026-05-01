# Frontend Implementation State

## Turn Update: 2026-05-01 Chat End-to-End Debug Reopen (Kickoff)

- Time: 2026-05-01T15:23:33+07:00
- Mode: CODE-ONLY
- Testing scope: minimal targeted verification only; no full test suite; no new tests

### Objective Locked

- Debug chat end-to-end again because room chat still does not work.
- Trace full path from `ChatPanel` submit -> FE send handler -> active transport/session -> backend `chat.send` handler -> room state -> `chat.message` broadcast -> FE receive/merge/render.
- Fix only the chat path and preserve existing room join/leave, websocket lifecycle, LiveKit/media, transcript, BRSE/audio, screen-share, host, and moderation flows.

### Mandatory Read Status

- Read current FE chat/runtime files: `FE/src/lib/ws.ts`, `FE/src/lib/api.ts`, `FE/src/features/room/useMeetingRoom.ts`, `FE/src/pages/RoomPage.tsx`, `FE/src/types/ws.ts`, `FE/src/types/api.ts`, `FE/src/components/ChatPanel.tsx`.
- Read backend chat contract/runtime reference: `docs/backend/API_CONTRACT.md`, `docs/backend/IMPLEMENTATION_STATE.md`, `BE/server/models.py`, `BE/server/gateway/ws_endpoint.py`, `BE/server/gateway/ws_hub.py`, `BE/server/gateway/room_service.py`, `BE/server/gateway/event_consumer.py`, `BE/server/gateway/room_store.py`.

### Current Trace Hypothesis

- Backend currently has a `chat.send` gateway handler, recent Redis chat state, and `chat.message` broadcast path.
- FE current send path appears to publish LiveKit data on topic `brse.chat` instead of calling gateway `chat.send`, so messages can bypass backend validation/persist/broadcast/snapshot hydration.
- Root cause will be finalized after targeted code trace and minimal verification.

## Turn Update: 2026-05-01 Chat End-to-End Debug Reopen (Final Sync)

- Time: 2026-05-01T15:27:25+07:00
- Status: chat send path fixed on FE; backend runtime path verified by static trace and compile

### Root Cause Confirmed

- Real current root cause: FE send path was using LiveKit data messages instead of backend gateway websocket chat.
- `ChatPanel` submit did call `meeting.sendChatMessage(...)`, but `FE/src/features/room/useMeetingRoom.ts` required `livekitState === "connected"` and published topic `brse.chat`.
- Because of that, backend never received `chat.send`; room Redis recent state was not updated; backend `chat.message` broadcast did not happen; join/reconnect `recent_messages` could not include those messages.
- This was not a current backend handler/broadcast bug: current BE code already has `chat.send` parsing, participant/session validation, recent-message persistence, and `chat.message` publication.

### Full Path Trace Result

- FE input submit: confirmed `ChatPanel.handleSubmit` invokes `onSend(trimmed)` and only clears input on `true`.
- FE event name/payload before fix: wrong transport; LiveKit data payload `room.chat.message`, not gateway envelope `type=chat.send`.
- WS lifecycle/session before fix: gateway socket existed but chat send did not use it; chat availability was blocked by LiveKit media state instead of gateway websocket state.
- BE parse/validation: `BE/server/gateway/ws_endpoint.py` handles `chat.send` and passes `payload.text`, participant id, and session id into `RoomService.send_chat_message(...)`.
- BE room state/broadcast: `RoomService.send_chat_message(...)` validates text/session, appends Redis recent chat, publishes `chat.message`; gateway-control consumer broadcasts to the room.
- FE receive/render: `applyChatMessage` handles `chat.message`; `ChatPanel` renders `chatMessages`; snapshot hydrate already reads `recent_messages`.

### FE Fix Applied

- `FE/src/lib/ws.ts`
  - `GatewaySocket.sendChatMessage(text)` now returns the generated `event_id`.
  - `sendEnvelope(...)` now returns `event_id` so chat can correlate optimistic UI with backend canonical events.
- `FE/src/features/room/useMeetingRoom.ts`
  - Removed LiveKit data-topic chat send/receive path from room chat.
  - `sendChatMessage(...)` now sends gateway websocket envelope `type=chat.send` with payload `{ text }`.
  - `canSendChat` now depends on gateway websocket connected state, not LiveKit media connection.
  - Pending optimistic messages are keyed by `client_event_id` and replaced by canonical backend `chat.message`.
  - Gateway chat errors matching pending `event_id` now set `chatError` and mark that message `failed` instead of becoming a generic room connection error.
- `FE/src/types/api.ts`
  - Added `client_event_id` and backend `language` compatibility to raw `ChatMessage`.
  - Added `client_event_id` to normalized `RoomChatMessage` for dedupe/reconciliation.

### Snapshot Hydrate / Duplicate Strategy

- Join/initial snapshot still hydrates `session.snapshot.recent_messages` and REST room `recent_messages`.
- WS `room.snapshot` merges `recent_messages` into the same chat collection.
- Realtime `chat.message` and snapshot messages dedupe by canonical `message_id`, and also by `client_event_id` so the local pending row is replaced instead of duplicated.

### Files Updated This Turn

- `FE/src/lib/ws.ts`
- `FE/src/features/room/useMeetingRoom.ts`
- `FE/src/types/api.ts`
- `docs/frontend/IMPLEMENTATION_STATE.md`
- `docs/backend/IMPLEMENTATION_STATE.md`

### Minimal Verification

- `python -m py_compile BE/server/models.py BE/server/events.py BE/server/gateway/ws_endpoint.py BE/server/gateway/ws_hub.py BE/server/gateway/room_service.py BE/server/gateway/event_consumer.py BE/server/gateway/room_store.py` passed.
- `npx tsc -b --pretty false` no longer reports chat-file errors after the optional `recent_messages` narrowing fix.
- `npx tsc -b --pretty false` still fails on existing non-chat `FE/src/lib/livekit.ts` errors: `track.name` missing on LiveKit track types at lines 213, 344, and 596.

### Deferred

- No full test suite and no new tests, per instruction.
- No runtime browser/manual multi-client smoke was run in this turn.
- Existing non-chat LiveKit type errors remain deferred.

## Turn Update: 2026-05-01 Room Chat Runtime Fix (Kickoff)

- Time: 2026-05-01T20:02:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Objective Locked

- Fix room chat end-to-end on FE so users can actually send messages and see them render correctly in realtime.
- Follow the existing backend contract for chat send / receive / snapshot hydrate without changing backend.
- Keep room websocket lifecycle, join/leave, transcript, moderation, BRSE/media flows intact.

### Investigation Scope

- Re-read FE room chat path:
  - `FE/src/lib/ws.ts`
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/pages/RoomPage.tsx`
  - `FE/src/components/ChatPanel.tsx`
  - `FE/src/types/ws.ts`
  - `FE/src/types/api.ts`
- Confirm backend chat contract from docs and runtime implementation before editing.
- Update this state file after root-cause confirmation, after major batch, and before turn end.

## Turn Update: 2026-05-01 Room Chat Runtime Fix (Post-Major)

- Time: 2026-05-01T20:28:00+07:00
- Status: core FE chat send/receive/state/runtime patch completed

### Root Cause Confirmed

- Backend gateway runtime currently does **not** implement room chat transport:
  - `BE/server/gateway/ws_endpoint.py` does not handle `chat.send`
  - `BE/server/gateway/event_consumer.py` does not fan out `chat.message`
  - backend room snapshot/join snapshot models do not serialize `recent_messages`
- FE chat path was therefore silently failing because:
  - `FE/src/features/room/useMeetingRoom.ts` tried to send chat through gateway WS only
  - `FE/src/components/ChatPanel.tsx` used a synchronous fire-and-forget send lifecycle and cleared local input immediately
  - FE join snapshot typing did not carry `recent_messages`, so even if snapshot data existed it would not hydrate cleanly through session state
  - room page disabled chat based on gateway state instead of the runtime transport actually used for chat delivery

### Send / Receive Path Fix Applied

- FE chat transport is now restored through room runtime only, without backend changes:
  - `FE/src/features/room/useMeetingRoom.ts`
    - chat send path now publishes reliable LiveKit data messages on topic `brse.chat`
    - chat receive path now listens to `RoomEvent.DataReceived` and merges incoming room chat payloads into normalized state
    - optimistic local messages are inserted immediately and promoted from `sending -> sent` or `failed`
    - gateway `chat.message` events remain supported and are normalized/merged if backend emits them later
- `FE/src/pages/RoomPage.tsx`
  - chat panel now binds to dedicated chat runtime flags instead of generic gateway-connected state

### Chat State Model Normalized

- Added normalized FE chat message model in `FE/src/types/api.ts`:
  - `RoomChatMessage`
  - required fields: `message_id`, `participant_id`, `display_name`, `text`, `created_at`
  - optional metadata: `sender_language`, `delivery_status`
- `FE/src/features/room/useMeetingRoom.ts` now exposes:
  - `chatMessages`
  - `sendChatMessage()`
  - `chatError`
  - `isSendingChat`
  - `canSendChat`

### Snapshot / Hydrate / Deduping Fixes

- `FE/src/types/api.ts`
  - `JoinRoomResponse.snapshot` now accepts `recent_messages?`
  - raw backend `ChatMessage` type is tolerant to either `sender_* / sent_at` or `participant_* / created_at` field styles
- `FE/src/features/room/useMeetingRoom.ts`
  - initial room snapshot and joined session snapshot now hydrate chat history into normalized FE state
  - room snapshot updates merge `recent_messages` without duplicating existing `message_id`
  - realtime gateway/livekit messages merge into the same deduped state collection

### Input / UX Fixes

- `FE/src/components/ChatPanel.tsx`
  - send path is now async instead of synchronous fire-and-forget
  - input clears only after successful send
  - send button + Enter submit respect `isSending`
  - inline chat error is rendered instead of silent failure
  - sending / failed delivery badges are shown per local message when relevant

### Files Updated In This Batch

- `FE/src/types/api.ts`
- `FE/src/features/room/useMeetingRoom.ts`
- `FE/src/components/ChatPanel.tsx`
- `FE/src/pages/RoomPage.tsx`
- `FE/src/index.css`
- `docs/frontend/IMPLEMENTATION_STATE.md`

### Testing Status

- Testing deferred by instruction: no tests run, no test files modified.

## Turn Update: 2026-05-01 Room Chat Runtime Fix (Final Sync)

- Time: 2026-05-01T20:35:00+07:00
- Scope confirmation:
  - FE chat no longer depends on the non-implemented gateway `chat.send` runtime path to deliver messages.
  - FE send path now uses room runtime delivery with explicit pending/failed UI state and useful error surfacing.
  - FE receive path now merges normalized chat messages from both room snapshot hydration and realtime room events without duplicate `message_id`.

### Final Root Cause Summary

- The original FE implementation assumed a backend gateway chat contract that is not actually implemented in the current repo runtime.
- Because of that mismatch, chat send was a silent no-op, and the FE input lifecycle still cleared user input as if send had succeeded.
- Session snapshot typing also lagged the UI assumptions for `recent_messages`.

### Final File Set Touched This Turn

- `FE/src/types/api.ts`
- `FE/src/features/room/useMeetingRoom.ts`
- `FE/src/components/ChatPanel.tsx`
- `FE/src/pages/RoomPage.tsx`
- `FE/src/index.css`
- `docs/frontend/IMPLEMENTATION_STATE.md`

### Testing Status

- Testing deferred by instruction: no tests run, no test files modified, no verification step executed.

## Turn Update: 2026-05-01 Platform Language Expansion + Create/Join UX (Kickoff)

- Time: 2026-05-01T19:15:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Objective Locked

- Expand FE-supported room/platform languages from `vi/en/ja` to `vi/en/ja/zh/ko/fr/es`.
- Make create-room choose the exact 2 `meeting_languages` directly inside the create-room view.
- Restrict join-room and in-room language selectors to the authoritative room `meeting_languages` pair.
- Replace user-facing short language codes with full names across create/join/room runtime UI.

### Planned FE Scope

- Add a shared FE language catalog + full-name label helpers for `Vietnamese`, `English`, `Japanese`, `Chinese`, `Korean`, `French`, `Spanish`.
- Update create-room UX to collect `meeting_languages` with pair validation before submit and surface backend validation errors clearly.
- Update join-room and room runtime UI to render full-name language labels and block selection outside the room pair.
- Sync `docs/frontend/IMPLEMENTATION_STATE.md` after each major batch and before turn end.

## Turn Update: 2026-05-01 Platform Language Expansion + Create/Join UX (Post-Major)

- Time: 2026-05-01T19:40:00+07:00
- Status: core FE language-catalog + create/join/room UX update completed

### Language Catalog Added

- FE shared language source-of-truth now supports:
  - `vi -> Vietnamese`
  - `en -> English`
  - `ja -> Japanese`
  - `zh -> Chinese`
  - `ko -> Korean`
  - `fr -> French`
  - `es -> Spanish`
- Shared helper file added:
  - `FE/src/lib/languages.ts`
- Full-name rendering strategy:
  - UI components call shared helper functions instead of rendering `toUpperCase()` language codes
  - room pair text uses human-readable labels (for example `Vietnamese and Japanese`)
  - transcript / participant / chat / in-room selector labels now use the same shared map

### Create-Room UX Changes

- `FE/src/pages/HomePage.tsx`
  - added explicit `Meeting languages` section inside the create-room view
  - create-room now requires selecting 2 meeting languages directly on the form before room creation
  - submit path validates:
    - both languages selected
    - languages are distinct
    - languages belong to the shared FE-supported set
  - backend `invalid_meeting_languages` errors are mapped to usable create-room messages

### Join-Room + Room Runtime Changes

- `FE/src/components/JoinRoomCard.tsx`
  - join-room language selector is now labeled `Your language`
  - selector options are limited to the authoritative room `meeting_languages` pair
  - join-room blocks invalid submission when pair is unavailable or the selection is outside the pair
- `FE/src/features/room/useMeetingRoom.ts`
  - room runtime now resolves `meeting_languages` through a shared pair helper instead of a hardcoded `vi/en/ja` path
  - language-change guard and WS invalid-language rollback now show pair-aware messages with full names
- `FE/src/pages/RoomPage.tsx`
  - room header now renders full-name meeting pair text
  - in-room language selector is constrained to the room pair and shows full-name labels

### Full-Name Rendering Coverage

- Updated user-facing language labels in:
  - `FE/src/components/ParticipantList.tsx`
  - `FE/src/components/ParticipantTile.tsx`
  - `FE/src/components/ChatPanel.tsx`
  - `FE/src/components/TranscriptPanel.tsx`
  - `FE/src/components/InterpreterStatusPanel.tsx`
  - `FE/src/pages/TestPage.tsx`
- Runtime parsing widened for new language codes in:
  - `FE/src/lib/livekit.ts`
- FE type union widened for new codes in:
  - `FE/src/types/api.ts`
- Layout tweaks for longer full-name labels in:
  - `FE/src/index.css`

### Files Updated In This Batch

- `FE/src/lib/languages.ts`
- `FE/src/types/api.ts`
- `FE/src/lib/livekit.ts`
- `FE/src/pages/HomePage.tsx`
- `FE/src/components/JoinRoomCard.tsx`
- `FE/src/features/room/useMeetingRoom.ts`
- `FE/src/pages/RoomPage.tsx`
- `FE/src/components/ParticipantList.tsx`
- `FE/src/components/ParticipantTile.tsx`
- `FE/src/components/ChatPanel.tsx`
- `FE/src/components/TranscriptPanel.tsx`
- `FE/src/components/InterpreterStatusPanel.tsx`
- `FE/src/pages/TestPage.tsx`
- `FE/src/index.css`
- `docs/frontend/IMPLEMENTATION_STATE.md`

### Testing Status

- Testing deferred by instruction: no tests run, no test files modified.

## Turn Update: 2026-05-01 Platform Language Expansion + Create/Join UX (Final Sync)

- Time: 2026-05-01T19:48:00+07:00
- Scope confirmation:
  - FE create-room now selects `meeting_languages` directly inside the create-room view.
  - FE join-room and in-room language selectors now constrain choices to the room meeting pair.
  - FE room/create/join/runtime user-facing language text now renders full names instead of short codes.
  - FE room/runtime paths now accept `vi/en/ja/zh/ko/fr/es` through shared catalog + widened type/runtime parsing.

### Final Language Strategy Locked

- Source-of-truth catalog lives in `FE/src/lib/languages.ts`.
- Shared helper responsibilities:
  - supported language list for selectors
  - full-name lookup map
  - room pair formatting helpers
  - authoritative meeting-pair resolution helper
- Short codes remain internal-only for API payloads / room state / track metadata parsing.

### Final File Set Touched This Turn

- `FE/src/lib/languages.ts`
- `FE/src/types/api.ts`
- `FE/src/lib/livekit.ts`
- `FE/src/pages/HomePage.tsx`
- `FE/src/components/JoinRoomCard.tsx`
- `FE/src/features/room/useMeetingRoom.ts`
- `FE/src/pages/RoomPage.tsx`
- `FE/src/components/ParticipantList.tsx`
- `FE/src/components/ParticipantTile.tsx`
- `FE/src/components/ChatPanel.tsx`
- `FE/src/components/TranscriptPanel.tsx`
- `FE/src/components/InterpreterStatusPanel.tsx`
- `FE/src/pages/TestPage.tsx`
- `FE/src/index.css`
- `docs/frontend/IMPLEMENTATION_STATE.md`

### Testing Status

- Testing deferred by instruction: no tests run, no test files modified, no verification step executed.

## Turn Update: 2026-05-01 Room Chat + Host + Moderation (Kickoff)

- Time: 2026-05-01T13:37:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Objective Locked

- Add room chat UI with realtime messaging via WS `chat.send` / `chat.message`
- Add host state tracking: `hostParticipantId`, `isCurrentUserHost`, host badge
- Add automatic host transfer handling from `room.host_changed` events
- Add host mute controls: host-only mute button in participant list
- Add force-mute local mic when current participant receives `moderation.force_muted`
- Hydrate chat/host/moderation state from room snapshot on join

### Planned FE Scope

- `FE/src/types/api.ts`
- `FE/src/types/ws.ts`
- `FE/src/lib/api.ts`
- `FE/src/lib/ws.ts`
- `FE/src/features/room/useMeetingRoom.ts`
- `FE/src/pages/RoomPage.tsx`
- `FE/src/components/ChatPanel.tsx` (new)
- `FE/src/components/ParticipantList.tsx`
- `FE/src/components/ParticipantTile.tsx`
- `FE/src/components/AudioDevicePanel.tsx`
- `FE/src/index.css`
- `docs/frontend/IMPLEMENTATION_STATE.md`

## Turn Update: 2026-05-01 Room Chat + Host + Moderation (Post-Major)

- Time: 2026-05-01T13:55:00+07:00
- Status: core FE implementation completed

### Type/Contract Changes

- `FE/src/types/api.ts`:
  - `ParticipantSnapshot`: added `is_host`, `muted_by_host`
  - `RoomSnapshotResponse.room`: added `host_participant_id`
  - `RoomSnapshotResponse`: added `recent_messages?: ChatMessage[]`
  - New types: `ChatMessage`, `MuteParticipantRequest`, `MuteParticipantResponse`
- `FE/src/types/ws.ts`:
  - New server events: `ChatMessageEvent`, `RoomHostChangedEvent`, `ModerationForceMutedEvent`, `ModerationParticipantMutedEvent`
  - New client messages: `ChatSendMessage`, `ModerationMuteMessage`
  - Extended `participant.joined`/`participant.updated` payloads with `is_host`, `muted_by_host`
  - Extended `room.snapshot` payload with `host_participant_id`, `recent_messages`

### Gateway Client Changes

- `FE/src/lib/ws.ts`:
  - `GatewaySocket.sendChatMessage(text)`: sends `chat.send` envelope
  - `GatewaySocket.sendMuteParticipant(targetParticipantId)`: sends `moderation.mute_participant` envelope
- `FE/src/lib/api.ts`:
  - `api.muteParticipant(roomId, token, body)`: POST `/api/rooms/{room_id}/moderation/mute`

### Room Runtime State Changes

- `FE/src/features/room/useMeetingRoom.ts`:
  - New state: `chatMessages`, `hostParticipantId`, `isCurrentUserHost`, `isMutedByHost`, `isMutingParticipant`, `moderationError`
  - New handlers: `applyChatMessage`, `applyHostChanged`, `applyForceMuted`, `applyParticipantMuted`, `handleForceMuteLocal`
  - New actions: `sendChatMessage`, `muteParticipant`
  - Snapshot hydration: loads `host_participant_id`, `is_host` from participants, `recent_messages`, self `muted_by_host`
  - Host transfer: `room.host_changed` event updates `hostParticipantId` and re-flags all participant `is_host`
  - Force mute: when `moderation.force_muted` targets self, calls `setLocalMicrophoneMuted(track, true)` and sets `isMutedByHost`
  - Participant list now derives `is_host` from `hostParticipantId` for UI rendering

### UI Component Changes

- `FE/src/components/ChatPanel.tsx` (new):
  - Scrollable message list with auto-scroll on new messages
  - Each message shows sender name, sender language pill, timestamp
  - Self messages styled distinctly
  - Input bar with validation (trim, no empty), send button
  - Disabled state when gateway not connected
- `FE/src/components/ParticipantList.tsx`:
  - Host badge (`Host`) shown for `is_host` participants
  - Muted-by-host badge (`Muted`) shown for `muted_by_host` participants
  - Mute button shown per remote human participant when `isCurrentUserHost` is true
  - Mute button has loading state per `isMutingParticipant`
- `FE/src/components/ParticipantTile.tsx`:
  - Added `isHost` and `isMutedByHost` props
  - Host badge and Muted badge rendered in tile footer tags
- `FE/src/components/AudioDevicePanel.tsx`:
  - Added `isMutedByHost` prop
  - When muted by host: unmute button disabled, label shows "Muted by host"
- `FE/src/pages/RoomPage.tsx`:
  - Integrated ChatPanel in sidebar stack
  - Wired host/mute props to ParticipantList and ParticipantTile
  - Added force-muted banner when `isMutedByHost` is true
  - Added moderation error banner

### CSS Changes

- `FE/src/index.css`:
  - Chat panel layout: `.chat-panel`, `.chat-message-list`, `.chat-message`, `.chat-input-bar`, `.chat-send-btn`
  - Message styling: `.chat-message-self`, `.chat-message-header`, `.chat-timestamp`, `.chat-message-text`
  - Host badge: `.badge-host` with warm amber gradient
  - Muted badge: `.badge-muted-by-host` with danger coloring
  - Force muted banner: `.banner-force-muted`
  - Mute button: `.button-mute-participant` with hover/disabled states

### Files Created

- `FE/src/components/ChatPanel.tsx`

### Files Modified

- `FE/src/types/api.ts`
- `FE/src/types/ws.ts`
- `FE/src/lib/api.ts`
- `FE/src/lib/ws.ts`
- `FE/src/features/room/useMeetingRoom.ts`
- `FE/src/pages/RoomPage.tsx`
- `FE/src/components/ParticipantList.tsx`
- `FE/src/components/ParticipantTile.tsx`
- `FE/src/components/AudioDevicePanel.tsx`
- `FE/src/index.css`
- `docs/frontend/IMPLEMENTATION_STATE.md`

### Testing Status

- Testing deferred by instruction: no tests run, no test files modified.

## Turn Update: 2026-05-01 Meeting Language Pair UX (Kickoff)

- Time: 2026-05-01T17:05:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Objective Locked

- Add explicit create-room language-pair selection UX (`meeting_languages`, exactly 2 distinct languages).
- Restrict join-room language selection to room-level `meeting_languages` only.
- Surface room language pair context in room UI and runtime state/hook.
- Wire FE API contracts to backend meeting-pair semantics (no `any`).

### Planned FE Scope

- `FE/src/lib/api.ts`
- `FE/src/types/api.ts`
- `FE/src/types/ws.ts`
- `FE/src/pages/HomePage.tsx`
- `FE/src/components/JoinRoomCard.tsx`
- `FE/src/features/room/useMeetingRoom.ts`
- `FE/src/pages/RoomPage.tsx`
- `docs/frontend/IMPLEMENTATION_STATE.md`

## Turn Update: 2026-05-01 Meeting Language Pair UX (Post-Major)

- Time: 2026-05-01T17:34:00+07:00
- Status: core FE implementation completed

### UX + Flow Changes Implemented

- Create room flow now requires explicit meeting pair selection (2 languages) before submit.
- Join room flow language selector is now constrained to room-level `meeting_languages`.
- In-room language selector is constrained to same pair; selecting outside pair is blocked in runtime hook.
- Room header now shows language context clearly:
  - meeting pair (`A <-> B`)
  - current user language

### FE Validation Rules Added

- Create room:
  - must select both language fields
  - pair must be distinct
  - language must be valid in `vi|en|ja`
- Join room:
  - disable submit if room pair is unavailable/invalid
  - only allow selecting within resolved room pair
- In-room language change:
  - rejects language outside resolved room pair and shows usable error message

### Contract / State Changes

- Added FE request type for create room payload with `meeting_languages` tuple.
- Added `meeting_languages` support on room summary/snapshot/websocket room payload typing.
- Updated join request/participant typing to concrete meeting-language type (no `any`).
- Extended room runtime hook to derive and expose room-level `meetingLanguages` for UI rendering and selector constraints.

### Files Updated (This Turn)

- `FE/src/types/api.ts`
- `FE/src/types/ws.ts`
- `FE/src/lib/api.ts`
- `FE/src/pages/HomePage.tsx`
- `FE/src/components/JoinRoomCard.tsx`
- `FE/src/features/room/useMeetingRoom.ts`
- `FE/src/pages/RoomPage.tsx`
- `FE/src/index.css`
- `docs/frontend/IMPLEMENTATION_STATE.md`

## Turn Update: 2026-05-01 Meeting Language Pair UX (Final Sync)

- Time: 2026-05-01T17:38:00+07:00
- Scope confirmation: FE create/join/in-room language behaviors now follow backend room-level meeting pair semantics.
- Room state path now carries `meeting_languages` context end-to-end (API types, WS payload type, runtime hook, render path).
- Backward compatibility: if `meeting_languages` is absent, FE applies graceful fallback from supported languages and blocks unsafe join submit when pair cannot be resolved.
- Testing status: deferred by instruction (no tests run, no test files modified).

## Turn Update: 2026-05-01 Audio Device Controls Bugfix (Kickoff)

- Time: 2026-05-01T14:30:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Root Cause (Locked)

- Mic input switching path relies on best-effort in-place device switch; when in-place switch is unsupported or reports unsuccessful transition, runtime does not always guarantee microphone track replacement.
- Audio output switching currently depends on per-element sink application path, but lacks centralized sink management for consistent application across existing and future audio elements.
- Device selected state can drift from real runtime apply state when devices change dynamically (plug/unplug) and sink/device apply fails.

### Strategy (Current Turn)

- Harden input switching path to always guarantee real microphone replacement fallback in room runtime.
- Introduce centralized audio sink output-device manager for all room audio playback elements.
- Align `useMeetingRoom` device state with runtime apply result and dynamic device availability.
- Keep mute/unmute semantics stable across input device switch.

## Turn Update: 2026-05-01 Audio Device Controls Bugfix (Post-Major)

- Time: 2026-05-01T14:48:00+07:00
- Status: major implementation completed

### Changes Implemented

- Hardened microphone input switch fallback in `FE/src/lib/livekit.ts`:
  - in-place `setDeviceId` now only accepts successful transition result;
  - when unsupported or unsuccessful, runtime falls back to full track replacement flow.
- Added centralized output sink manager in `FE/src/lib/audioOutput.ts`:
  - registry of active audio elements;
  - centralized `setRoomAudioOutputDevice()` applies sink id to all registered sinks;
  - new sinks auto-apply currently selected output device.
- Updated `FE/src/components/MediaElements.tsx`:
  - `AudioTrackSink` now registers/unregisters audio element in centralized registry;
  - applies current output device via centralized manager and reports apply errors upstream.
- Updated `FE/src/features/room/useMeetingRoom.ts`:
  - integrated centralized output apply in `switchAudioOutput()` and device refresh path;
  - added refs for selected input/output and switching flags to avoid stale-state drift during refresh/device-change;
  - resets centralized output target on session clear and on unsupported browser output path.
- Updated `FE/src/pages/RoomPage.tsx`:
  - removed per-sink output-device prop usage; sink output now managed centrally.

### Validation

- Static diagnostics (`get_errors`) on changed FE files: no TypeScript errors reported.
- Runtime/browser verification: deferred by instruction.

## Turn Update: 2026-05-01 Audio Device Controls Bugfix (Final Sync)

- Time: 2026-05-01T14:50:00+07:00
- Scope confirmation: frontend-only changes, no backend files modified in this turn.
- Testing note: no tests executed (explicitly deferred by instruction).

## Last Updated

- Time: 2026-05-01T13:31:00+07:00
- Agent: Codex
- Branch: develop

## Current Phase

- Audio Device Controls FE Runtime Integration

## Current Objective

- Implement room audio device controls for meeting runtime:
  - mic mute/unmute
  - audio input device enumeration + switching
  - audio output device enumeration + sink switching when browser supports it
- Keep existing join/leave, websocket lifecycle, transcript, screen share, and BRSE/human audio flow stable.
- Testing deferred by instruction (CODE-ONLY).

## Work Log (Current Turn)

### Batch 0: Mandatory Read + Device Strategy Lock (Completed)

- Read required files before code changes:
  - `docs/frontend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/lib/livekit.ts`
  - `FE/src/components/MediaElements.tsx`
  - `FE/src/pages/RoomPage.tsx`
  - `FE/src/types/livekit.ts`
  - all current components under `FE/src/components/`
- Strategy locked for this turn:
  - add local runtime state in `useMeetingRoom` for input/output device lists, selected ids, switching flags, mute flags, and error messages.
  - mic toggle strategy: operate on local published microphone track (`mute/unmute`) with explicit loading/error state.
  - mic switch strategy: prefer in-place `setDeviceId` on current local audio track; fallback to republish a new local audio track bound to selected device and replace stale reference.
  - output switch strategy: central sink-id propagation to all room playback audio elements (`AudioTrackSink`) via shared `outputDeviceId` prop.
  - browser support degrade path: detect sink-id support; keep selector disabled + show short unsupported message when unavailable.
  - edge handling: `devicechange` refresh, missing selected device fallback, empty labels before permission, and switch-failure feedback.
- Testing remains deferred by instruction.

### Batch 1: Audio Device Runtime + UI Integration (Completed)

- Runtime changes in `FE/src/features/room/useMeetingRoom.ts`:
  - Added mic control state/action:
    - `isMicMuted`, `isTogglingMic`, `micToggleError`, `toggleMicrophoneMuted()`
  - Added audio input state/action:
    - `audioInputDevices`, `selectedAudioInputDeviceId`, `isSwitchingAudioInput`, `audioInputError`, `switchAudioInput()`
  - Added audio output state/action:
    - `audioOutputDevices`, `selectedAudioOutputDeviceId`, `isSwitchingAudioOutput`, `audioOutputSupported`, `audioOutputError`, `switchAudioOutput()`
  - Added sink apply error bridge:
    - `reportAudioOutputApplyError()`
  - Added browser device lifecycle handling:
    - enumerate devices on session start
    - subscribe to `navigator.mediaDevices.devicechange`
    - fallback selected device if previous selection disappears
  - Added stale-reference prevention:
    - local mic track ref is updated during media refresh and cleared on teardown/unload/leave
- Helper changes in `FE/src/lib/livekit.ts`:
  - added device helpers:
    - `enumerateAudioDevices()`
    - `supportsAudioOutputSelection()`
    - `getLocalMicrophoneTrack()`
    - `isMicrophoneMuted()`
    - `setLocalMicrophoneMuted()`
    - `switchLocalMicrophoneTrack()`
  - mic switch strategy implemented:
    - prefer in-place `setDeviceId` on current local mic track
    - fallback to republish replacement local audio track bound to selected device and unpublish/stop old track
- UI + sink integration:
  - created `FE/src/components/AudioDevicePanel.tsx`
    - includes mic mute/unmute button
    - includes input device selector
    - includes output device selector + unsupported browser hint
    - includes error feedback rows for toggle/input/output actions
  - updated `FE/src/pages/RoomPage.tsx`
    - renders `AudioDevicePanel` in room sidebar stack
    - wires all new meeting hook state/actions
    - passes selected output device to every room `AudioTrackSink`
  - updated `FE/src/components/MediaElements.tsx`
    - `AudioTrackSink` now accepts `outputDeviceId`
    - applies `setSinkId` per sink when browser supports it
    - reports sink-apply failures back to runtime via callback
  - updated `FE/src/types/livekit.ts`
    - added `AudioDeviceOption` for input/output selectors
  - updated `FE/src/index.css`
    - added styles for `audio-settings-panel` and control rows/errors/hints
- Output device support/degrade path:
  - if browser supports `setSinkId`: output selector enabled and sink id is applied to all room playback audio sinks
  - if unsupported: selector disabled and short unsupported hint shown; runtime keeps playback on default browser routing
- Audio sink apply strategy:
  - propagate single selected output device id from room runtime to all `AudioTrackSink` instances
  - each sink applies `setSinkId` on attach/update so human/BRSE playback paths stay consistent

### Batch 2: Finalization Sync (Completed)

- Final code path for this turn includes:
  - mic mute/unmute runtime action + UI control
  - audio input enumeration + runtime switching action + UI selector
  - audio output support detection + selector + sink-id propagation to all room sinks
  - device-change refresh handling and selected-device fallback behavior
- Files created/updated in this turn:
  - `FE/src/components/AudioDevicePanel.tsx` (new)
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/lib/livekit.ts`
  - `FE/src/components/MediaElements.tsx`
  - `FE/src/pages/RoomPage.tsx`
  - `FE/src/types/livekit.ts`
  - `FE/src/index.css`
  - `docs/frontend/IMPLEMENTATION_STATE.md`
- Testing remains deferred by instruction (CODE-ONLY, no test execution).

## Work Log (This Turn)

### Batch 0: Mandatory Read + Strategy Lock (Completed)

- Read required files before coding:
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `docs/frontend/IMPLEMENTATION_STATE.md`
  - `FE/src/lib/api.ts`
  - `FE/src/lib/ws.ts`
  - `FE/src/lib/livekit.ts`
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/pages/RoomPage.tsx`
  - `FE/src/components/MediaElements.tsx`
  - `FE/src/types/api.ts`
  - `FE/src/types/ws.ts`
  - `FE/src/types/livekit.ts`
- Strategy locked for this turn:
  - Backend sync path ưu tiên REST idempotent endpoints (`/screen-share/start|stop`) sau publish/unpublish LiveKit để tránh phụ thuộc socket state khi browser capture callback kết thúc bất ngờ.
  - FE vẫn consume đầy đủ backend events (`screen_share.started`, `screen_share.stopped`, `participant.updated`) + snapshot fields (`is_screen_sharing`, `screen_share`) để đồng bộ state nguồn sự thật từ backend.
  - Local runtime giữ reference screen-share track/publication rõ ràng trong `useMeetingRoom` để stop/cleanup deterministic.
  - Stage strategy: single-main active shared screen UX (ưu tiên local sharer nếu local đang share, fallback participant remote active đầu tiên theo danh sách).
  - Cleanup strategy: stop button, track ended callback, leave, unload, unmount đều đi qua một stop path idempotent gồm notify backend stop + unpublish/stop local track + clear local state.
  - Không sửa backend, không test run, không đụng test files.

### Batch 1: FE Contract + Runtime Integration (Completed)

- Updated FE contract/types:
  - `FE/src/types/api.ts`
    - added participant screen-share fields: `is_screen_sharing`, `screen_share`
    - added screen-share DTOs: `ScreenShareStartRequest`, `ScreenShareStateResponse`, `ScreenShareTrackInfo`
  - `FE/src/types/ws.ts`
    - added client messages: `screen_share.start`, `screen_share.stop`
    - added server events: `screen_share.started`, `screen_share.stopped`
    - extended `participant.joined` / `participant.updated` payload typings with screen-share fields
  - `FE/src/types/livekit.ts`
    - added `ScreenShareFeed` for dedicated shared-screen stage rendering
- Updated FE API/WS client paths:
  - `FE/src/lib/api.ts`
    - added REST methods:
      - `startScreenShare(roomId, token, body)`
      - `stopScreenShare(roomId, token)`
  - `FE/src/lib/ws.ts`
    - added optional signal helpers:
      - `sendScreenShareStart(...)`
      - `sendScreenShareStop()`
- Updated LiveKit helper/runtime:
  - `FE/src/lib/livekit.ts`
    - added actual publish path using browser screen capture:
      - `publishScreenShareTrack(room)`
    - added local cleanup helper:
      - `unpublishScreenShareTrack(room, track)`
    - extended media snapshot to include `screenShares` from local + remote publications (`Track.Source.ScreenShare`)

### Batch 2: Meeting Hook + UI Stage/Badges + Cleanup Paths (Completed)

- Core runtime flow implemented in `FE/src/features/room/useMeetingRoom.ts`:
  - added local state:
    - `isScreenSharing`
    - `isStartingScreenShare`
    - `isStoppingScreenShare`
    - `screenShareError`
  - added public actions:
    - `startScreenShare()`
    - `stopScreenShare(...)`
  - start flow:
    1) capture screen + publish to LiveKit
    2) extract `track_sid` / `track_name`
    3) sync backend via REST `/screen-share/start`
    4) patch local participant state
  - stop flow:
    1) sync backend via REST `/screen-share/stop`
    2) unpublish + stop local screen track
    3) clear local state and participant flags
  - consume backend updates from:
    - snapshot participant fields
    - `participant.updated`
    - `screen_share.started`
    - `screen_share.stopped`
  - cleanup coverage:
    - manual stop button
    - browser track ended callback (`MediaStreamTrack ended`)
    - leave room path
    - unload/pagehide path (best-effort)
    - hook teardown/unmount (best-effort)
- UI updates:
  - `FE/src/pages/RoomPage.tsx`
    - added start/stop screen share control with loading/error state
    - added dedicated `Shared Screen Stage` panel
    - strategy for multi-share: prefer local sharer if active, else first active sharer
  - `FE/src/components/ParticipantList.tsx`
    - added participant badge: `Sharing screen`
  - `FE/src/components/ParticipantTile.tsx`
    - added tile badge: `Sharing screen`
  - `FE/src/index.css`
    - added stage layout/frame styles and compact header control behavior

### Testing Status

- Testing deferred by instruction: no test run, no test changes.

### Batch 3: Finalization Sync (Completed)

- Final state sync completed before end of turn as required.
- Strategy locked in implementation:
  - primary backend sync via REST (`start/stop` screen-share endpoints)
  - websocket signaling methods retained as fallback/best-effort path during teardown
  - active shared-screen stage driven by backend participant state + LiveKit screen tracks
- Cleanup paths confirmed in code:
  - explicit stop button
  - browser track ended callback
  - leave room path
  - unload/pagehide path
  - hook teardown/unmount path
- Testing remains deferred (CODE-ONLY).

## Completed

- [x] Mic test UI — `/test` page, `useMicTest` hook, `MicLevelMeter` component
- [x] Translation test UI — `/test` page, `useTranslationTest` hook, side-by-side panels
- [x] Backend test-session REST contract wired (`POST/DELETE /api/test/mic`, `POST/DELETE /api/test/translation`)
- [x] WebSocket test session streaming for both mic and translation flows
- [x] PCM16 binary audio capture and streaming to backend test WebSocket
- [x] Mic level meter: server-confirmed RMS/peak/dB with local fallback
- [x] Mic status states: idle / requesting_permission / connecting / active / silence / stopped / error
- [x] Translation status states: idle / requesting_permission / connecting / listening / translating / stopped / error
- [x] Translation transcript partial/final merge — in-place replacement by utterance, no duplicate lines
- [x] Audio player wired for `translation_test.final.audio_url` when backend provides it
- [x] Error handling: user-facing banners for mic permission denied, WS fail, backend error events
- [x] Cleanup: mic stream, AudioContext, ScriptProcessor, WebSocket closed correctly on stop/unmount
- [x] Test flow independent from full meeting room — no LiveKit, no room join required
- [x] `/test` route added to App.tsx router
- [x] "Mic & Translation Test" link added to HomePage dev section
- [x] Test types added to `FE/src/types/api.ts` and `FE/src/types/ws.ts`
- [x] Read required docs: `docs/VISION.md`
- [x] Read required docs: `docs/architecture.md`
- [x] Read required docs: `docs/realtime_protocol.md`
- [x] Read required docs: `docs/backend/API_CONTRACT.md`
- [x] Read required docs: `docs/backend/GATEWAY_DESIGN.md`
- [x] Read required docs: `docs/backend/LIVEKIT_SETUP.md`
- [x] Read required docs: `docs/backend/IMPLEMENTATION_STATE.md`
- [x] Compared docs with backend implementation for FE-critical payload mismatches
- [x] Scaffolded Vite + React + TypeScript frontend in `FE/`
- [x] Added frontend package/build config and app entry files
- [x] Added API contract types, WebSocket types, and LiveKit media types
- [x] Implemented REST client, Gateway WebSocket wrapper, and LiveKit helper utilities
- [x] Added in-memory room session store
- [x] Implemented home page with create room and join existing room by id/link
- [x] Implemented room snapshot fetch and join room form flow
- [x] Implemented Gateway WebSocket connection, ping loop, and reconnect behavior
- [x] Implemented LiveKit connect + local mic/camera publish flow
- [x] Implemented participant grid, participant list, and language badges
- [x] Implemented interpreter track parser and listener-targeted audio routing
- [x] Filtered interpreter participants out of human video grid
- [x] Implemented realtime transcript panel with partial/final replacement and degraded badge
- [x] Implemented interpreter status panel from `interpreter.status` events
- [x] Implemented in-room language change with optimistic UI and rollback on WS `error`
- [x] Implemented leave room button flow and `pagehide` best-effort leave request
- [x] Frontend build passes with `cd FE && npm run build`
- [x] Fixed unstable room lifecycle dependency that recreated WS on rerender
- [x] Added stable frontend `sessionKey` derived from `room_id + participant_id + session_id + websocket.url`
- [x] Added shared GatewaySocket registry so the same joined session reuses one WS connection across StrictMode remounts
- [x] Added explicit connect/disconnect guards to prevent duplicate WS creation while CONNECTING/RECONNECTING
- [x] Limited reconnect to unexpected drops after a previously successful connection
- [x] Prevented reconnect after manual leave / cleanup / obsolete session release
- [x] Build still passes after WebSocket lifecycle fix
- [x] Updated FE contract types for backend `audio_routing` and event-level `audio_output`
- [x] Switched FE meeting runtime to translated-audio-first playback model
- [x] Removed remote human audio as the cross-language playback path
- [x] Kept human participants for video/presence/status only
- [x] Split playback state into interpreter audio vs same-language passthrough audio
- [x] Removed old `humanAudioFeeds` output path from room runtime
- [x] Transcript state now preserves canonical audio metadata from `audio_output`
- [x] Media snapshot now refreshes on listener language / participant language / audio routing policy changes
- [x] Same-language interpreter tracks are suppressed so passthrough audio does not overlap translated audio
- [x] Updated FE transcript contracts for websocket + snapshot normalized fields (`kind`, `text`, `utterance_id`, `is_final`, `speaker_language`, `src_lang`, `tgt_lang`)
- [x] Added normalized transcript state model for room runtime with metadata: speaker id/name/language, kind, source/target language, text, partial/final, timestamp
- [x] Added transcript merge strategy to combine snapshot + live streams and dedupe by `transcript_id`
- [x] Implemented smooth in-place partial -> final upgrade by `transcript_id` to avoid noisy duplicate lines
- [x] Updated room transcript panel UI to render speaker-attributed realtime transcript with `source/translated` and `partial/final` badges
- [x] Added scrollable transcript history with newest line emphasis for room usability
- [x] Read backend BRSE relay contract updates and backend runtime metadata for `meeting_mode=brse_relay`
- [x] Updated FE meeting types for `virtual_brse`, `meeting_mode`, `interpreter_mode`, BRSE relay transcript refs, and `brse_participant_audio`
- [x] Switched meeting runtime from translated-audio-first to BRSE participant mode
- [x] Restored normal remote human audio playback as the primary human audio path
- [x] Added room-wide BRSE AI audio feed handling from virtual participant LiveKit tracks
- [x] Rendered `BRSE AI` as a distinct participant in room grid, participant list, and join-room preview
- [x] Updated transcript normalization/UI to distinguish human source speech from BRSE relay lines
- [x] Bypassed old listener-targeted interpreter audio filtering and removed cross-language human-audio suppression from the active room runtime
- [x] Added FE best-effort leave helper for unload path via authenticated `fetch(..., keepalive: true)`
- [x] Added explicit websocket unload disconnect path (`disconnectForUnload`) to suppress reconnect during tab close/unload
- [x] Hardened room runtime leave guards (`hasLeftRef`, `hasSentLeaveRef`, `manualShutdownRef`) to prevent duplicate leave/disconnect spam
- [x] Unified unload cleanup to always stop local media + disconnect LiveKit + close gateway before session invalidation
- [x] Added lifecycle handlers for `beforeunload` / `pagehide` / `unload` with idempotent cleanup behavior
- [x] Protected runtime event/fatal-close handlers from stale-manual-shutdown races

## In Progress

- [ ] Testing deferred by instruction

## Completed This Turn

- [x] Room chat panel — ChatPanel component with scrollable message list, input bar, send action
- [x] Chat realtime state — `chatMessages` in useMeetingRoom hydrated from snapshot and updated via `chat.message` events
- [x] Chat WS client — `GatewaySocket.sendChatMessage(text)` sends `chat.send` envelope
- [x] Host state model — `hostParticipantId`, `isCurrentUserHost` derived in useMeetingRoom
- [x] Host badge — `Host` badge in ParticipantList and ParticipantTile
- [x] Host transfer handling — `room.host_changed` event updates host state and re-flags all participants
- [x] Host mute controls — host-only `Mute` button in ParticipantList per remote human participant
- [x] Moderation mute REST — `api.muteParticipant()` with WS fallback
- [x] Force mute local mic — `moderation.force_muted` event triggers `setLocalMicrophoneMuted(track, true)`
- [x] Muted-by-host UI — disabled unmute button, "Muted by host" label, `Muted` badge, force-muted banner
- [x] Snapshot hydration — host_participant_id, is_host, recent_messages, muted_by_host loaded on join/reconnect
- [x] FE lifecycle cleanup hardening — stale closure fix, deterministic ref teardown
- [x] Added `isScreenSharingRef` to mirror `isScreenSharing` state without closure capture
- [x] Removed `isScreenSharing` from unload effect deps — handlers now stable per session, no re-registration race on screen share toggle
- [x] `tryCleanupUnload` uses `isScreenSharingRef.current` — always reads current value at unload time
- [x] `tryCleanupUnload` and `leaveRoom` both save refs to locals before nulling, then operate on saved locals — prevents dangling ref use after teardown
- [x] `gatewayRef.current` nulled after `disconnectForUnload()` in unload path
- [x] `livekitRoomRef.current` nulled after `disconnectRoom()` in both unload and explicit leave paths
- [x] No changes to `api.ts`, `ws.ts`, `RoomPage.tsx`, or backend

## Work Log (This Turn)

### Batch 0: Required Read + Plan Lock (Completed)

- Read required files before code changes:
  - `docs/frontend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/lib/ws.ts`
  - `FE/src/lib/api.ts`
  - `FE/src/pages/RoomPage.tsx`
  - `FE/src/lib/livekit.ts`
- Foundation from previous turns (already in place):
  - `leaveRoomBestEffort()` keepalive DELETE in `api.ts`
  - `disconnectForUnload()` in `ws.ts`
  - `hasLeftRef`, `hasSentLeaveRef`, `manualShutdownRef` guards
  - `beforeunload` / `pagehide` / `unload` lifecycle handlers
  - Guarded event and fatal-close callbacks against manualShutdown races
- Remaining gaps identified this turn:
  - `isScreenSharing` captured as stale closure in unload effect — the effect deps include
    `isScreenSharing`, which causes handler re-registration on every screen share toggle.
    During the cleanup→re-register transition, an unload event is missed.
    Fix: `isScreenSharingRef` (always-current ref), remove `isScreenSharing` from deps.
  - `livekitRoomRef.current` not nulled after `disconnectRoom()` in both `tryCleanupUnload`
    and `leaveRoom` finally block — stale room ref could be used after teardown.
  - `gatewayRef.current` not nulled after `disconnectForUnload()` in `tryCleanupUnload`.
- Strategy for this turn:
  - Add `isScreenSharingRef` and sync it from `isScreenSharing` state.
  - Use `isScreenSharingRef.current` in `tryCleanupUnload`, remove `isScreenSharing` from deps.
  - Null both `livekitRoomRef.current` and `gatewayRef.current` after use in cleanup paths.
  - No changes to `api.ts`, `ws.ts`, `RoomPage.tsx`, or backend.

### Batch 1: Stale Closure Fix + Deterministic Ref Teardown

- `FE/src/features/room/useMeetingRoom.ts`:
  - Added `isScreenSharingRef = useRef(false)`.
  - Added `useEffect` to keep `isScreenSharingRef.current` in sync with `isScreenSharing`.
  - In `tryCleanupUnload`: replaced `isScreenSharing` closure capture with `isScreenSharingRef.current`.
  - Removed `isScreenSharing` from unload effect deps `[roomId, session, isScreenSharing]`
    → now `[roomId, session]`. Handlers are registered once per session and stay stable.
  - In `tryCleanupUnload`: saved `livekitRoomRef.current` to a local before nulling the ref,
    then called `clearLocalScreenTrack` and `disconnectRoom` on the saved local. Nulled
    `gatewayRef.current` after `disconnectForUnload`.
  - In `leaveRoom` finally: saved `livekitRoomRef.current` to a local before nulling, and
    saved `gatewayRef.current` to a local before calling `disconnect()` and nulling.
- Testing deferred by instruction.

### Previous Turn Batch 0: Required Read + Plan Lock

- Read required files before code changes:
  - `docs/frontend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/lib/ws.ts`
  - `FE/src/lib/api.ts`
  - `FE/src/pages/RoomPage.tsx`
  - `FE/src/state/session.tsx`
  - `FE/src/lib/livekit.ts`
- Gaps identified:
  - FE currently relies on `pagehide + fetch keepalive`, but lacks robust duplicate-guarding across leave/unload paths.
  - Gateway socket disconnect path exists but missing explicit unload/manual shutdown helper semantics in shared API.
  - Session-aware guard for stale cleanup callbacks can be tightened in `useMeetingRoom` for unload + reconnect races.
- Planned implementation for this turn:
  - add centralized best-effort leave utility in FE API layer (`fetch keepalive` with auth header).
  - add manual-shutdown/unload-safe disconnect API in websocket layer.
  - unify leave/unload cleanup path in `useMeetingRoom` with idempotent guards and session checks.
  - ensure local media/livekit and local room state cleanup happen on unmount/unload, not only button leave.

### Previous Turn Batch 1: FE Lifecycle Cleanup Hardening

- `FE/src/lib/api.ts`
  - Added `leaveRoomBestEffort(roomId, token)` helper using authenticated keepalive `DELETE` request for unload-safe leave signaling.
  - Reused shared auth header builder in `api.leaveRoom`.
- `FE/src/lib/ws.ts`
  - Added `disconnectForUnload(reason)` to mark intentional shutdown, clear timers, reject pending connect, and close websocket with unload-specific close code.
- `FE/src/features/room/useMeetingRoom.ts`
  - Added explicit refs for idempotent lifecycle cleanup: `hasSentLeaveRef`, `manualShutdownRef`.
  - Guarded gateway event and fatal-close callbacks so manual shutdown/unload does not trigger stale invalidation/reconnect handling.
  - On unload lifecycle (`beforeunload`, `pagehide`, `unload`): one-time cleanup now closes websocket (unload path), disconnects LiveKit/local media, sends best-effort leave, and invalidates local session.
  - Manual leave path now uses duplicate guards before REST leave and always performs deterministic local teardown.
  - Session init/reset now reinitializes cleanup guards to avoid stale state carry-over.

## Pending Next

- [ ] Browser/runtime verification if a later turn explicitly allows non code-only validation
- [ ] Runtime verification deferred by instruction
- [ ] Verify BRSE AI virtual participant appears in snapshot and room list against running backend
- [ ] Verify human audio and BRSE relay audio can play simultaneously without overlap issues
- [ ] Verify relay transcript payloads hydrate/render correctly from real gateway events
- [ ] Verify mic test WebSocket streams PCM16 correctly to backend and `mic_test.level` events render meter
- [ ] Verify translation test partial/final flow matches backend event naming exactly
- [ ] Verify `translation_test.final.audio_url` plays correctly when backend emits it

## Files Created

- `docs/frontend/IMPLEMENTATION_STATE.md`
- `FE/src/components/ChatPanel.tsx`
- `FE/src/features/test/useMicTest.ts`
- `FE/src/features/test/useTranslationTest.ts`
- `FE/src/components/MicLevelMeter.tsx`
- `FE/src/pages/TestPage.tsx`
- `FE/.gitignore`
- `FE/package.json`
- `FE/package-lock.json`
- `FE/tsconfig.json`
- `FE/tsconfig.app.json`
- `FE/tsconfig.node.json`
- `FE/vite.config.ts`
- `FE/index.html`
- `FE/src/vite-env.d.ts`
- `FE/src/types/api.ts`
- `FE/src/types/ws.ts`
- `FE/src/types/livekit.ts`
- `FE/src/lib/api.ts`
- `FE/src/lib/rooms.ts`
- `FE/src/lib/ws.ts`
- `FE/src/lib/livekit.ts`
- `FE/src/state/session.tsx`
- `FE/src/features/room/transcripts.ts`
- `FE/src/features/room/interpreter.ts`
- `FE/src/features/room/useMeetingRoom.ts`
- `FE/src/components/ConnectionBadge.tsx`
- `FE/src/components/MediaElements.tsx`
- `FE/src/components/ParticipantTile.tsx`
- `FE/src/components/ParticipantList.tsx`
- `FE/src/components/TranscriptPanel.tsx`
- `FE/src/components/InterpreterStatusPanel.tsx`
- `FE/src/components/JoinRoomCard.tsx`
- `FE/src/pages/HomePage.tsx`
- `FE/src/pages/RoomPage.tsx`
- `FE/src/App.tsx`
- `FE/src/main.tsx`
- `FE/src/index.css`

## Files Modified

- `docs/frontend/IMPLEMENTATION_STATE.md`
- `FE/src/types/api.ts` — added BRSE relay room/participant/transcript/audio descriptor types
- `FE/src/types/ws.ts` — updated room, participant, transcript, and status WS payloads for BRSE mode
- `FE/src/types/livekit.ts` — replaced listener-targeted interpreter feed types with human/brse room-wide media feed types
- `FE/src/lib/livekit.ts` — restored human remote audio playback, added BRSE virtual participant audio parsing, and ensured BRSE tile rendering from gateway snapshots
- `FE/src/features/room/transcripts.ts` — normalized `source` vs `relay` transcript entries with original-speaker and BRSE relay separation
- `FE/src/features/room/interpreter.ts` — reshaped status entries for BRSE relay semantics
- `FE/src/features/room/useMeetingRoom.ts` — replaced translated-audio-first state with `humanAudioFeeds` + `brseAudioFeeds`, room mode metadata, and participant-kind-aware room state
- `FE/src/components/JoinRoomCard.tsx` — surfaced BRSE AI in pre-join participant preview
- `FE/src/components/ParticipantList.tsx` — marked BRSE AI as a virtual relay participant
- `FE/src/components/ParticipantTile.tsx` — added BRSE AI tile treatment and labels
- `FE/src/components/TranscriptPanel.tsx` — split human source lines from BRSE relay lines in room transcript UI
- `FE/src/components/InterpreterStatusPanel.tsx` — reframed status panel around BRSE AI room-wide relay activity
- `FE/src/pages/RoomPage.tsx` — switched runtime audio sinks to human + BRSE feeds and updated room copy for BRSE participant mode
- `FE/src/lib/api.ts` — added unload-safe `leaveRoomBestEffort` helper and shared auth-header path for leave API
- `FE/src/lib/ws.ts` — added `disconnectForUnload` to prevent reconnect during lifecycle unload cleanup
- `FE/src/features/room/useMeetingRoom.ts` — implemented idempotent unload/manual leave cleanup guards and deterministic media/socket teardown
- `FE/src/features/room/useMeetingRoom.ts` — fixed isScreenSharingRef stale closure in unload effect, nulled gatewayRef/livekitRoomRef deterministically in tryCleanupUnload and leaveRoom finally
- `FE/src/index.css` — added visual treatment for BRSE participant tags/tiles and relay transcript blocks
- `FE/src/types/api.ts` — added `MicTestStatus`, `TranslationTestStatus`, `MicTestSessionResponse`, `TranslationTestSessionResponse`, `CreateTranslationTestRequest`
- `FE/src/types/ws.ts` — added `MicTestServerEvent`, `TranslationTestServerEvent` and all payload variants
- `FE/src/lib/api.ts` — added `createMicTest`, `deleteMicTest`, `createTranslationTest`, `deleteTranslationTest`
- `FE/src/App.tsx` — added `/test` route
- `FE/src/pages/HomePage.tsx` — added "Mic & Translation Test" link in dev section
- `FE/src/index.css` — added all test-page, status-badge, level-meter, translation-panel CSS
- no backend files changed in this turn

## Mic Test Model (Current)

- Hook: `useMicTest` in `FE/src/features/test/useMicTest.ts`
- State shape: `MicTestState { status, level, peak, db, error, sessionId }`
- Status lifecycle: `idle → requesting_permission → connecting → active ↔ silence → stopped | error`
- Level source: server-confirmed RMS/peak/dB from `mic_test.level` events; local ScriptProcessor RMS as fallback while no server events have arrived yet
- Audio capture: `AudioContext` at 16 kHz, `ScriptProcessorNode` with 512-sample buffer, PCM16 binary frames sent over WebSocket
- Silence detection: local timer fallback (500 ms below RMS 0.01) + server `mic_test.silence` event
- Component: `MicLevelMeter` — 20-bar segmented meter, color-coded (low=teal, mid=blue, high=amber, peak=red)
- Cleanup: stream tracks stopped, AudioContext closed, WS `mic_test.stop` message sent on stop/unmount; backend session deleted via REST DELETE

## Translation Test Model (Current)

- Hook: `useTranslationTest` in `FE/src/features/test/useTranslationTest.ts`
- State shape: `TranslationTestState { status, srcLang, tgtLang, items[], error, sessionId, lastAudioUrl }`
- Item shape: `TranslationTestItem { id, sourceText, translatedText, isFinal, timestamp }`
- Status lifecycle: `idle → requesting_permission → connecting → listening ↔ translating → stopped | error`
- Partial/final merge: in-place replacement by `pendingItemIdRef` — partial updates the same item ID, final finalizes it; no extra duplicate lines
- Audio output: `translation_test.final.audio_url` triggers HTML `<audio>` playback if backend provides it; audio-ready for future backend audio path
- Language constraints: src and tgt must differ; selectors disabled while running
- Cleanup: same pattern as mic test; backend session deleted on stop/unmount

## Transcript Model (Current)
- Normalized FE transcript entity is `TranscriptEntry` in `FE/src/features/room/transcripts.ts`.
- Primary key: `transcriptId` (`transcript_id` from backend).
- Stored metadata:
  - `utteranceId`
  - `kind` (`source` | `translated` | `relay`)
  - actor row identity: `actorParticipantId`, `actorName`, `actorLanguage`, `actorKind`
  - original speaker identity: `sourceSpeakerId`, `sourceSpeakerName`, `sourceSpeakerLanguage`
  - relay identity: `relayParticipantId`, `relayParticipantName`, `relayTargetLanguage`
  - `sourceText`
  - `relayText`
  - `text`
  - `audioTrackName`
  - `canonicalAudioTrackName`
  - `isFinal`
  - `fallbackUsed`
  - `timestamp`
  - `updatedAt`

## Merge Strategy (Current)
- Snapshot path (`room.snapshot.recent_transcripts`): normalized via `hydrateTranscriptEntries`.
- Live path (`transcript.partial` / `transcript.final`): normalized via `upsertTranscriptEntry`.
- Unified dedupe merge: `mergeTranscriptCollections` keyed by `transcriptId`.
- Partial/final policy:
  - existing `final` is not downgraded by later `partial`
  - incoming `final` upgrades matching `partial`
  - when same finality, keep latest by `updatedAt`
  - preserve earliest line timestamp for stable ordering

## Transcript UI (Current)
- Reused `FE/src/components/TranscriptPanel.tsx` as the room transcript component.
- Item layout now separates:
  - human source speech rows
  - BRSE relay rows rendered as `BRSE AI (tgt_lang)` with original speaker/source text shown above
  - status badge (`Partial`/`Final`)
  - kind badge (`Human Source`, `Translated`, or `BRSE Relay src->tgt`)
- UX behavior:
  - scrollable transcript list for history review
  - latest line visually highlighted
  - partial lines styled lighter/dashed
  - BRSE relay copy visually grouped in a dedicated relay block

## Manual Verification Needed Later

- testing deferred in this turn by explicit instruction
- verify mic test WebSocket opens correctly and `mic_test.level` events update meter in real time
- verify PCM16 binary frames arrive at backend without corruption
- verify `mic_test.silence` event transitions status badge correctly
- verify translation test creates session, opens WS, streams audio, and displays `translation_test.partial` updates in source text box in real time
- verify `translation_test.final` finalizes the in-flight item (no duplicate lines)
- verify `translation_test.final.audio_url` plays via the hidden `<audio>` element when backend provides it
- verify language selector is locked while test is running and unlocks on stop
- verify stop/cleanup: WS closes cleanly, mic stream released, backend session deleted
- verify `/test` page accessible from home page link
- verify transcript panel renders `source` and `relay` kinds from websocket live stream
- verify partial -> final replacement for the same `transcript_id` without extra duplicate lines
- verify room snapshot transcripts hydrate once and dedupe with live events by `transcript_id`
- verify room join in dev under React StrictMode no longer creates duplicate accepted WS connections
- verify backend no longer logs immediate disconnect stack trace right after sending `room.snapshot`
- verify remote human audio plays normally for all human participants
- verify BRSE AI audio plays as supplemental room-wide relay audio
- verify BRSE AI appears as a virtual participant tile and participant-list entry
- verify source speech and BRSE relay lines stay visually separated in transcript UI
- verify local mic/camera publish succeeds in browser with device permissions
- verify create room and join flow against running gateway
- verify WS reconnect behavior by restarting gateway while room is open
- verify BRSE relay status updates render with correct source/target language context
- verify transcript partial/final replacement against live backend
- verify `fallback_text_only` / degraded states show expected UX
- verify leave cleanup on `pagehide` in a real browser tab close scenario

## Open Issues / Risks
- backend currently returns relative `share_url` and `websocket.url`; FE should resolve these safely
- backend models still include `auto` and `disconnected`, while docs position FE around `vi/en/ja` and reconnect states
- production bundle is large (`dist/assets/index-*.js` ~684 kB before gzip warning) because LiveKit client is bundled into one entry
- no real browser E2E, build, or typecheck was run in this turn; verification deferred by instruction
- previously fixed WS root cause: `RoomPage` had passed a new `onSessionInvalidated` function every render, which recreated room runtime effects
- previously fixed WS root cause: `GatewaySocket` had lived only inside component effect scope, so StrictMode dev cleanup could close a fresh socket immediately
- audio model after this turn: human LiveKit audio is restored as the default room audio path for all human participants
- audio model after this turn: BRSE AI relay audio is handled as supplemental room-wide audio from a virtual participant, not listener-private replacement audio
- logic bypassed/removed from active room path: listener-targeted interpreter audio filtering by `listener_id`
- logic bypassed/removed from active room path: cross-language suppression of human remote audio
- logic bypassed/removed from active room path: `sameLanguagePassthroughAudioFeeds` / `interpreterAudioFeeds` mental model as the primary room audio abstraction
- BRSE participant rendering: participant list + join preview show `BRSE AI` badge; video grid renders a dedicated BRSE tile with placeholder when no camera is present
- testing deferred: no runtime/browser verification was performed in this turn by explicit instruction

## Resume Instructions

- mở `docs/backend/API_CONTRACT.md` trước nếu cần re-check payload
- nếu cần tiếp tục audio runtime, mở `FE/src/lib/livekit.ts` rồi `FE/src/features/room/useMeetingRoom.ts` trước
- để test mic/translation UI: `cd FE && npm run dev` → mở `http://localhost:5173/test`
- backend cần chạy: `docker compose up redis gateway` (không cần LiveKit cho test flow)
- file test UI: `FE/src/pages/TestPage.tsx`, hooks: `FE/src/features/test/useMicTest.ts` và `FE/src/features/test/useTranslationTest.ts`
