# Frontend Implementation State

## Last Updated

- Time: 2026-04-30T15:30:00+07:00
- Agent: Claude Sonnet 4.6
- Branch: develop

## Current Phase

- Mic Test + Translation Test UI

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

## In Progress

- [ ] Testing deferred by instruction
- Current objective: none for implementation; mic test + translation test batch completed, runtime verification intentionally deferred

## Pending Next

- [ ] Browser/runtime verification if a later turn explicitly allows non code-only validation
- [ ] Runtime verification deferred by instruction
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
  - `speakerParticipantId`
  - `speakerName`
  - `speakerLanguage`
  - `kind` (`source` | `translated`)
  - `srcLang`
  - `tgtLang`
  - `text`
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
- Item layout shows:
  - speaker display name
  - speaker language
  - transcript text
  - status badge (`Partial`/`Final`)
  - kind badge (`Source` or `Translated src->tgt`)
- UX behavior:
  - scrollable transcript list for history review
  - latest line visually highlighted
  - partial lines styled lighter/dashed

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
- verify transcript panel renders both `source` and `translated` kinds from websocket live stream
- verify partial -> final replacement for the same `transcript_id` without extra duplicate lines
- verify room snapshot transcripts hydrate once and dedupe with live events by `transcript_id`
- verify room join in dev under React StrictMode no longer creates duplicate accepted WS connections
- verify backend no longer logs immediate disconnect stack trace right after sending `room.snapshot`
- verify cross-language listeners hear only interpreter translated audio
- verify no human remote audio + interpreter audio overlap in cross-language rooms
- verify same-language passthrough policy still matches backend declaration
- verify local mic/camera publish succeeds in browser with device permissions
- verify create room and join flow against running gateway
- verify WS reconnect behavior by restarting gateway while room is open
- verify interpreter audio routing only plays matching listener track
- verify transcript partial/final replacement against live backend
- verify `fallback_text_only` / degraded states show expected UX
- verify leave cleanup on `pagehide` in a real browser tab close scenario

## Open Issues / Risks
- backend currently returns relative `share_url` and `websocket.url`; FE should resolve these safely
- backend models still include `auto` and `disconnected`, while docs position FE around `vi/en/ja` and reconnect states
- production bundle is large (`dist/assets/index-*.js` ~684 kB before gzip warning) because LiveKit client is bundled into one entry
- no real browser E2E was run in this turn; build verification only
- previously fixed WS root cause: `RoomPage` had passed a new `onSessionInvalidated` function every render, which recreated room runtime effects
- previously fixed WS root cause: `GatewaySocket` had lived only inside component effect scope, so StrictMode dev cleanup could close a fresh socket immediately
- audio model after this turn: authoritative cross-language playback path is `InterpreterAudioFeed` targeted to the current listener via `interp::{speaker_id}::{listener_id}::{src_lang}::{tgt_lang}`
- audio model after this turn: human participants remain for video/presence/name/language/status; remote human audio is no longer the general playback path
- same-language policy kept in FE: `human_passthrough`, isolated in `sameLanguagePassthroughAudioFeeds`
- cleaned state path: removed `humanAudioFeeds` as the general remote playback model
- cleaned state path: `useMeetingRoom` now exposes `interpreterAudioFeeds` and `sameLanguagePassthroughAudioFeeds` separately
- cleaned state path: `RoomPage` no longer auto-attaches remote human audio by cross-language heuristic
- testing deferred: no runtime/browser verification was performed in this turn by explicit instruction

## Resume Instructions

- mở `docs/backend/API_CONTRACT.md` trước nếu cần re-check payload
- nếu cần tiếp tục audio runtime, mở `FE/src/lib/livekit.ts` rồi `FE/src/features/room/useMeetingRoom.ts` trước
- để test mic/translation UI: `cd FE && npm run dev` → mở `http://localhost:5173/test`
- backend cần chạy: `docker compose up redis gateway` (không cần LiveKit cho test flow)
- file test UI: `FE/src/pages/TestPage.tsx`, hooks: `FE/src/features/test/useMicTest.ts` và `FE/src/features/test/useTranslationTest.ts`
