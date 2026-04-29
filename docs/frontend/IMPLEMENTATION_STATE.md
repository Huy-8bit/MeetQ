# Frontend Implementation State

## Last Updated
- Time: 2026-04-29T22:55:16+07:00
- Agent: Codex
- Branch: develop

## Current Phase
- WebSocket

## Completed
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

## In Progress
- [ ] Browser/runtime verification against real gateway logs
- Current objective: confirm the new guards eliminate duplicate WS connects and immediate post-snapshot disconnects in a real joined room
- Files being edited:
  - none

## Pending Next
- [ ] Join one room in browser and confirm only one WS is accepted per `session_id`
- [ ] Refresh page and confirm old session closes cleanly while new session opens once
- [ ] Click leave and confirm no reconnect happens afterward
- [ ] Watch backend logs to confirm no `Cannot call "send" once a close message has been sent` during normal join flow
- [ ] Optionally split LiveKit bundle if initial JS size needs optimization

## Files Created
- `docs/frontend/IMPLEMENTATION_STATE.md`
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
- `FE/src/lib/ws.ts`
- `FE/src/features/room/useMeetingRoom.ts`
- `FE/src/pages/RoomPage.tsx`
- `FE/src/state/session.tsx`
- no backend files changed in this turn

## Manual Verification Needed Later
- verify room join in dev under React StrictMode no longer creates duplicate accepted WS connections
- verify backend no longer logs immediate disconnect stack trace right after sending `room.snapshot`
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
- root cause identified:
- `RoomPage` passed a new `onSessionInvalidated` function every render, so `useMeetingRoom` effect tore down and recreated WS/LiveKit repeatedly
- `GatewaySocket` lived only inside component effect scope, so React StrictMode dev remount could open one WS and immediately close it during fake cleanup
- remaining risk:
- LiveKit runtime still reconnects at component scope rather than via shared registry; this turn intentionally focused on Gateway WS stability only

## Resume Instructions
- mở `docs/backend/API_CONTRACT.md` trước nếu cần re-check payload
- nếu cần runtime verify, mở `FE/src/lib/ws.ts` rồi `FE/src/features/room/useMeetingRoom.ts` trước
- command nên chạy tiếp: `cd FE && npm run dev`
- backend/gateway nên chạy cùng LiveKit trước khi test browser flow
