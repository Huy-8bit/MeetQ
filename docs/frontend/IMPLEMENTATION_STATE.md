# Frontend Implementation State

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
