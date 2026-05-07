# Frontend Implementation State

## Turn Update: 2026-05-07 Frontend Theme, Custom Select, and Landing Polish

- Time: 2026-05-07T00:00:00+07:00
- Mode: CODE-ONLY
- Status: implemented
- Testing deferred: yes, per instruction

### Objective

Polish frontend UI consistency without changing room/runtime data contracts:

- normalize light/dark surfaces and controls.
- replace important native selects with reusable web UI selects.
- redesign the landing/create-room experience in a refined Apple-like direction.
- update product-facing room duration wording from 30 minutes to 60 minutes.

### Root Cause

- The frontend had a newer theme token layer, but many user-facing surfaces still
  used older hardcoded light colors (`white`, slate text, light panel fills).
- Native `<select>` controls were visually hidden or directly rendered in core
  flows, so language and audio device menus still used OS/browser chrome.
- The landing page had a compact utility-card feel and still showed the old
  30-minute duration promise.

### Theme Consistency Strategy

- Added a final token-based CSS override layer for app, landing, join, side
  panel, settings drawer, summary, relay, chat, device, and test-page surfaces.
- Centralized field/select colors through field/menu CSS variables for light
  and dark mode.
- Kept runtime structure and data flow unchanged; the changes are presentation
  and control implementation only.
- Removed the old in-room expired copy that mentioned 30 minutes and replaced it
  with duration-neutral wording.

### Custom Select Strategy

- Added reusable `CustomSelect` with web-rendered trigger/listbox, click outside
  close, disabled state, compact/standard sizes, selected/hover/active states,
  long-label truncation, and keyboard handling for arrows, Home/End, Enter,
  Space, and Escape.
- The component accepts a typed option list and preserves existing state/update
  semantics by calling the same language/audio handlers with the selected value.
- Mobile behavior uses bounded menu height and clipped labels instead of native
  OS dropdown UI.

### Native Selects Replaced

- Landing/create room meeting language A/B.
- Join-room user language.
- In-room topbar user language.
- Settings microphone input device.
- Settings speaker/output device.
- Dev translation test source and target language controls.

### Landing Redesign Strategy

- Reworked the home page into a spacious hero plus a focused create/open action
  stack.
- Used restrained typography, broad spacing, subtle glass-like surfaces, calm
  depth, and neutral Apple-like color balance.
- Updated duration wording to `60-minute rooms` and `60 min` on the landing
  surface.

### Files Changed

| File | Change |
|------|--------|
| `FE/src/components/CustomSelect.tsx` | Added reusable web UI select/listbox component |
| `FE/src/pages/HomePage.tsx` | Redesigned landing hero/action layout; switched create language controls to custom select; updated duration to 60 minutes |
| `FE/src/components/JoinRoomCard.tsx` | Replaced join language native select with custom select |
| `FE/src/components/RoomTopBar.tsx` | Replaced in-room language native select with compact custom select |
| `FE/src/components/AudioDevicePanel.tsx` | Replaced microphone and speaker native selects with custom select |
| `FE/src/pages/TestPage.tsx` | Replaced translation test language native selects with custom select |
| `FE/src/pages/RoomPage.tsx` | Removed old 30-minute expired-room wording from runtime banner |
| `FE/src/index.css` | Added custom select styling, landing polish, theme token overrides, and dark/light surface consistency fixes |
| `docs/frontend/IMPLEMENTATION_STATE.md` | Documented root cause, select strategy, landing strategy, 60-minute wording, files changed, and deferred testing |

### Testing

- Full test suite not run, per CODE-ONLY instruction.
- Verification/build commands not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests not modified.

---

## Turn Update: 2026-05-07 Final Summary Fetch-First Flow

- Time: 2026-05-07T00:00:00+07:00
- Mode: CODE-ONLY
- Status: implemented
- Testing deferred: yes, per instruction

### Objective

Fix the frontend final-summary runtime path so the ended-room summary screen
reads an existing `final` summary before offering any generation action.

### Root Cause

- The ended-room path in `RoomPage` automatically called
  `prepareFinalSummary()`.
- `prepareFinalSummary()` maps to `POST /api/rooms/{room_id}/summary?type=final`,
  which is the backend generate path.
- Because that action ran on screen load and last-leave/expiry transitions, FE
  could show final preparation/error states even when a completed `final`
  summary was already persisted in MongoDB and readable through the contract
  `GET /api/rooms/{room_id}/summary?type=final`.

### Fix Strategy

- Keep `GET` and `POST` summary calls separate in the FE runtime.
- Make final-summary screen entry fetch `final` first.
- Keep generation only behind explicit user actions such as prepare/retry.
- Render final summary states distinctly: loading, completed, pending, failed,
  and no summary yet.
- Preserve active-room interim summary generation/refresh behavior.

### Runtime Changes

- Ended-room page entry now calls
  `GET /api/rooms/{room_id}/summary?type=final` with not-found treated as the
  product state "not available yet".
- Expiry shutdown and last-human-leave summary transitions now read final
  summary first instead of auto-posting generation.
- `POST /summary?type=final` remains available only through the explicit
  Prepare/Retry final action.
- Final summary polling remains bounded and read-only after a pending final
  record is observed.
- The hook guards final generation when a final summary is already
  `completed` or `pending`, preventing accidental duplicate generate requests.
- Fetch and generate failures now use operation-specific messages:
  - fetch: `Could not load final summary.`
  - generate: `Could not generate final summary.`

### Render State Machine

- Loading: shows saved-summary lookup state while final `GET` is in flight.
- Completed: renders the final artifact immediately and hides prepare as the
  primary path.
- Pending: shows final-summary preparation state and allows read-only
  "Check latest".
- Failed: shows failure copy and an explicit retry action.
- No summary yet: shows final summary unavailable state and allows explicit
  prepare.
- Skipped/not enough content: shows unavailable content state without treating
  it as a completed artifact.

### Payload Rendering

- Completed summaries render available `summary_text`, `highlights`,
  `decisions`, `action_items`, `participant_summary`, `generated_at`, and
  `summary_language`.
- `source_stats` is shown as a compact source-count section when useful.
- Optional fields remain backward-safe and hidden when absent.

### Files Changed

| File | Change |
|------|--------|
| `FE/src/pages/RoomPage.tsx` | Changed ended-room and last-leave final summary entry from auto-generate to fetch-first; wired separate final check action |
| `FE/src/features/room/useMeetingRoom.ts` | Separated fetch/generate error handling, cleared stale cross-type summaries, guarded final generate when completed/pending, and changed expiry flow to fetch final |
| `FE/src/lib/api.ts` | Uses distinct read/generate response aliases for summary API calls |
| `FE/src/types/api.ts` | Added `FetchMeetingSummaryResponse` and `GenerateMeetingSummaryResponse` aliases over the shared backend schema |
| `FE/src/components/MeetingSummaryPanel.tsx` | Added final-specific state machine/actions and renders optional summary payload sections safely |
| `FE/src/index.css` | Added compact source-stat and summary metadata styling, including dark theme support |
| `docs/frontend/IMPLEMENTATION_STATE.md` | Documented root cause, fetch-first strategy, state changes, files changed, and deferred testing |

### Testing

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests not modified.

---

## Turn Update: 2026-05-07 Meeting Theme, Layout, and Stage Focus UX

- Time: 2026-05-07T00:00:00+07:00
- Mode: CODE-ONLY
- Status: implemented
- Testing deferred: yes, per instruction

### Objective

Add additive room UX controls for:

- light/dark theme selection.
- meeting layout mode selection.
- stage focus mode for shared screen or active meeting content.

### Theme Strategy

- Add document-level theme mode: `light` and `dark`.
- Restore saved theme before React mount to avoid flashing the wrong room theme.
- Use CSS variables for app/room surfaces, borders, text, stage background,
  tile media background, panel surfaces, and controls.
- Keep the existing dark meeting feel as the default for production continuity.
- Add light-mode overrides for:
  - room shell and top bar.
  - meeting stage and shared-screen frame.
  - participant tiles and active/speech badges.
  - side panel, chat, relay, people, summary, controls, and empty states.
- Add dark-mode overrides for previously light panel surfaces so dark mode is
  coherent across the side panel and settings drawer.

### Layout Strategy

- Add three room layout modes:
  - `stage-focus`: larger stage, narrower side panel, wider share frame.
  - `balanced`: default room balance.
  - `compact`: tighter side panel and slightly denser controls.
- Layout modes are CSS-only around the existing `room-shell`, `meeting-stage`,
  and `room-side-panel` structure.
- No LiveKit, websocket, relay, chat, people, screen-share, or summary runtime
  paths were changed for layout behavior.

### Focus Strategy

- Add a direct `Focus` / `Exit` action in the room control bar.
- Stage focus mode hides the side panel, keeps top bar and meeting controls
  available, and expands the stage/shared-screen frame.
- Opening a panel or settings exits focus mode to avoid conflicting layout state.
- The implementation uses stage focus rather than browser fullscreen so the room
  controls remain predictable and no browser permission/fullscreen edge case can
  block the meeting UI.

### Persistence Strategy

- Store theme in `localStorage` key `brseai_theme_mode`.
- Store room layout in `localStorage` key `brseai_room_layout_mode`.
- Storage read/write failures are ignored so private-mode or blocked storage
  does not break join/room runtime.

### Mobile Behavior

- Theme applies globally on mobile.
- Desktop layout widths collapse to the existing single-column/bottom-sheet
  mobile room pattern.
- Stage focus hides the mobile bottom-sheet side panel and removes alert stack
  clutter so the stage gets the available viewport.
- Settings drawer remains full-height and scrollable with compact view controls.

### Files Changed

| File | Change |
|------|--------|
| `FE/src/lib/uiPreferences.ts` | Added theme/layout preference loading, saving, and DOM theme application |
| `FE/src/main.tsx` | Restores saved theme before React renders |
| `FE/src/pages/RoomPage.tsx` | Wires theme, layout, stage focus state, persistence, and view settings |
| `FE/src/components/MeetingViewPanel.tsx` | New compact settings section for theme, layout, and stage focus |
| `FE/src/components/SettingsDrawer.tsx` | Generalized drawer title/eyebrow for room settings |
| `FE/src/components/RoomControlBar.tsx` | Added direct stage focus toggle |
| `FE/src/index.css` | Added theme tokens, light/dark room styling, layout modes, focus mode, and mobile rules |
| `docs/frontend/IMPLEMENTATION_STATE.md` | Documented implementation and deferred testing |

### Testing

- Full test suite not run, per CODE-ONLY instruction.
- Verification/build commands not run, per CODE-ONLY instruction.
- No new tests added.
- No existing tests modified.

---

## Turn Update: 2026-05-07 Microphone Capture Cleanup

- Time: 2026-05-07T00:00:00+07:00
- Mode: CODE-ONLY
- Status: implemented
- Testing deferred: yes, per instruction

### Objective

Improve frontend microphone capture quality before publishing local audio to
LiveKit/backend, without changing room flow or redesigning the audio system.

### Mic Constraints Strategy

- Centralize room microphone capture constraints in `FE/src/lib/livekit.ts`.
- Apply browser/device-level processing on the real room capture path:
  - `echoCancellation`
  - `noiseSuppression`
  - `autoGainControl`
  - `voiceIsolation` as an optional preference where supported
  - mono/speech-oriented capture hints (`channelCount`, `sampleRate`,
    `sampleSize`, `contentHint="speech"`)
- Reuse the same constraints for initial mic publish and input-device switching.
- Publish microphone tracks with speech-oriented LiveKit audio settings:
  `AudioPresets.speech`, `dtx=true`, `red=true`, `forceStereo=false`.
- Keep playback route unchanged: local video preview remains muted, audio sinks
  are remote-only, and screen-share capture still excludes system audio.
- Keep mute/unmute and selected input/output device behavior intact.

### Compatibility Strategy

- Use standard optional media constraints that unsupported browsers can ignore.
- Keep device selection exact when the user chooses an input device.
- Prefer in-place mic restart with full constraints on device switch; fall back
  to LiveKit `setDeviceId`; then fall back to creating and publishing a
  replacement mic track.
- Avoid aggressive custom WebAudio processing that could distort speech or break
  mobile/browser behavior.
- If processing-constraint reapply fails after `setDeviceId`, FE falls back to
  non-device-specific processing hints and keeps the room running.
- If the current mic was muted during input-device switch, the replacement track
  is published muted to avoid a short unmuted leak.

### Files Changed

| File | Change |
|------|--------|
| `FE/src/lib/livekit.ts` | Added shared microphone capture constraints, speech publish options, speech content hint, and device-switch fallback path |
| `FE/src/features/room/useMeetingRoom.ts` | Passes muted-state preservation into microphone device switching |
| `docs/frontend/IMPLEMENTATION_STATE.md` | Documented microphone capture cleanup |

### Testing

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests not modified.
- Build check run: `cd FE && npm run build`.
  - Result: pass.
  - Vite still emits the existing large chunk warning.

---

## Turn Update: 2026-05-06 Meeting Summary UI

- Time: 2026-05-06T00:00:00+07:00
- Mode: CODE-ONLY
- Status: implemented
- Testing deferred: yes, per instruction

### Objective

Add additive frontend UI/runtime support for meeting summaries:

- live `interim` checkpoint summary while a meeting is active.
- post-meeting `final` summary after expiry or last participant leave.

### Placement Strategy

- Add `Summary` as a fourth room side-panel tab next to `Relay`, `Chat`, and
  `People`.
- Reuse the existing side-panel/bottom-sheet pattern so desktop and mobile keep
  the current meeting stage/control flow.
- Keep summary out of the primary stage unless the room has ended.
- Add `Summary` to the bottom control tab cluster so users can open it the same
  way they open Relay/Chat/People.
- Badge the tab when a summary record exists.

### Runtime Strategy

- Add FE types for `MeetingSummaryResponse`, status, type, source window, source
  stats, highlights, decisions, action items, and participant summaries.
- Add API methods for:
  - `GET /api/rooms/{room_id}/summary?type=interim|final`
  - `POST /api/rooms/{room_id}/summary?type=interim|final`
- Keep parsing backward-safe: missing `summary_type`, optional arrays, and
  optional structured fields must not crash render.
- `useMeetingRoom` owns summary runtime state:
  - `meetingSummary`
  - `summaryIntent`
  - `isLoadingSummary`
  - `isGeneratingSummary`
  - `summaryError`
  - `fetchMeetingSummary(type)`
  - `refreshInterimSummary()`
  - `prepareFinalSummary()`
- On active room mount, FE silently checks for an existing `interim` record.
- User action in the Summary tab calls `POST .../summary?type=interim` to
  generate or refresh the live checkpoint.
- Final summary generation uses `POST .../summary?type=final`, then bounded
  background polling via `GET .../summary?type=final` while status is pending or
  the record is not visible yet.

### UX States

- No summary yet.
- Checking/loading saved summary.
- Generating/refreshing.
- Completed/skipped/pending/failed summary record.
- Final-summary pending state after room end with retry/check-again affordance.
- Interim UI labels the artifact as `Current summary`.
- Final UI labels the artifact as `Final summary`.
- Completed summaries render:
  - `summary_text`
  - `highlights`
  - `decisions`
  - `action_items`
  - `participant_summary`
  - generated timestamp when available
- Failed/skipped states surface backend `error` when provided and keep retry
  controls visible.

### Room-End Handling

- Expiry while joined no longer redirects directly home. The session is still
  cleared and media/socket teardown remains in `useMeetingRoom`, but RoomPage
  stays on `/rooms/:roomId` and shows a final-summary screen.
- Direct visit to an expired room also shows the final-summary screen and asks
  the backend to prepare/fetch the final summary.
- Manual leave preserves the previous home redirect for non-last participants.
  If the current user appears to be the last human participant, FE stays on the
  room route and shows the final-summary screen.

### Mobile Behavior

- Summary is included in the existing mobile bottom-sheet side panel.
- The bottom control tab row now supports the fourth tab with horizontal
  overflow safety on small screens.
- The final-summary screen stacks copy and summary artifact vertically on
  mobile.

### Files Changed

| File | Change |
|------|--------|
| `FE/src/types/api.ts` | Added meeting summary contract types; added `brse_mode`/silent-summary-safe meeting mode typing |
| `FE/src/types/ws.ts` | Added `brse_silent_summary` to room snapshot meeting mode union |
| `FE/src/lib/api.ts` | Added `getRoomSummary` and `generateRoomSummary` |
| `FE/src/features/room/useMeetingRoom.ts` | Added summary state/actions, interim fetch, interim refresh, final generation/polling, backward-safe normalizers |
| `FE/src/components/MeetingSummaryPanel.tsx` | New artifact UI for interim/final summaries and all summary states |
| `FE/src/components/RoomSidePanel.tsx` | Added `Summary` tab and summary content slot |
| `FE/src/components/RoomControlBar.tsx` | Added `Summary` shortcut to room control tabs |
| `FE/src/pages/RoomPage.tsx` | Wired Summary panel, active interim actions, final room-ended screen, last-leave final-summary path |
| `FE/src/index.css` | Added summary panel, final-summary screen, desktop/mobile responsive styling |
| `docs/frontend/IMPLEMENTATION_STATE.md` | Documented summary UI implementation |

### Testing

- Full test suite not run, per CODE-ONLY instruction.
- No new tests added.
- No existing tests modified.

---

## Turn Update: 2026-05-03 Chat Translation UI

- Time: 2026-05-03T00:00:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective

Add UI/UX for chat with optional translation mode. Backend sends translated
text alongside original; FE lets user choose mode and renders both clearly.

### Chat Translation UI Strategy

User-facing controls are added to `ChatPanel`:

- A compact **segmented control** (`chat-mode-bar`) sits between the message
  list and the input bar.
- Two options: `Original` | `+ Translate`.
- Active option highlighted with white pill (Apple-segmented-control feel).
- Choice is **persisted in `localStorage`** under key
  `brseai_chat_translation_mode` so the user's last mode survives tab reloads.
- Default (first visit or unknown stored value): `original_only`.

### Message Render Strategy

**`original_only` messages:** render exactly as before — no visual change.

**`translate` messages with translations:**

```
┌─────────────────────────────────────────────────────────┐
│  Huy  [VI]                                   12:34      │
│  xin chào mọi người                                     │
│  ╔══════════════════════════════════════════════════╗   │
│  ║ TRANSLATED · ENGLISH                             ║   │
│  ║ hello everyone                                   ║   │
│  ╚══════════════════════════════════════════════════╝   │
└─────────────────────────────────────────────────────────┘
```

- Original `text` always rendered as the primary content.
- Each `translations[]` entry rendered as a secondary block with:
  - Small uppercase label: `Translated · English`
  - Left green border accent (`2px solid rgba(15,118,110,0.28)`)
  - Slightly muted background
- "Translating…" placeholder shown for optimistic (sending) messages in
  translate mode until the server echo with actual translated text arrives.

**Backward compat:** messages without `translation_mode` / `translations` (old
server or old snapshot) default to `original_only` rendering — no crash, no
blank fields.

### Send Mode Wiring

```
User picks mode in ChatPanel (segmented control)
  → stored in component state + localStorage
  → handleSubmit() calls onSend(text, translationMode)
  → ChatPanel.onSend prop: (text, translationMode) => Promise<boolean>
  → RoomPage passes meeting.sendChatMessage directly (signature compatible)
  → useMeetingRoom.sendChatMessage(text, translationMode="original_only")
  → GatewaySocket.sendChatMessage(text, translationMode?)
  → WS payload: { text, translation_mode? }
  → backend picks up translation_mode, runs translation if "translate"
  → broadcasts chat.message with translations[]
  → FE applyChatMessage → normalizeChatMessage → mergeRoomChatMessages
  → ChatPanel re-renders with translation block
```

### Snapshot Hydration

- `normalizeChatMessage()` now maps `translation_mode` and `translations` from
  `ChatMessage` into `RoomChatMessage`.
- Messages loaded from `recent_messages` (join snapshot / WS snapshot) with
  existing translation data render correctly immediately.
- No duplicate risk: `mergeRoomChatMessages` deduplicates by
  `message_id` / `client_event_id` as before.

### Optimistic Message Handling

- `createOptimisticChatMessage()` accepts `translationMode` and stamps
  `translation_mode` + `translations: []` on the pending message.
- When `translationMode === "translate"` and `delivery_status === "sending"`,
  ChatPanel shows `"Translating…"` placeholder in the translation block.
- Server echo replaces the optimistic entry (via `mergeRoomChatMessages`),
  populated with real `translations[]`.

### Persistence Choice

- `localStorage` key: `brseai_chat_translation_mode`
- Stored on every mode change; loaded once on `ChatPanel` mount.
- Gracefully skipped if `localStorage` unavailable (try/catch).

### Files Changed

| File | Change |
|------|--------|
| `FE/src/types/api.ts` | Added `ChatTranslationMode`, `ChatTranslation`; extended `ChatMessage` and `RoomChatMessage` with translation fields |
| `FE/src/types/ws.ts` | Imported `ChatTranslationMode`; added `translation_mode?` to `ChatSendMessage` payload |
| `FE/src/lib/ws.ts` | `sendChatMessage(text, translationMode?)` — passes `translation_mode` in WS payload |
| `FE/src/features/room/useMeetingRoom.ts` | `sendChatMessage(text, translationMode)`, `normalizeChatMessage`, `createOptimisticChatMessage` carry translation fields |
| `FE/src/components/ChatPanel.tsx` | Segmented mode control, translation bubble render, localStorage persistence, `meetingLanguages` prop |
| `FE/src/pages/RoomPage.tsx` | Passes `meetingLanguages` to ChatPanel |
| `FE/src/index.css` | `.chat-mode-bar`, `.chat-mode-btn`, `.chat-translation-block`, `.chat-translation-label`, `.chat-translation-text` |

### Testing

- Full test suite not run, per CODE-ONLY instruction.
- No new tests added.
- No existing tests modified.

---

## Turn Update: 2026-05-03 Mobile Layout, Bottom Bar Regrouping & Active Speaker Highlight

- Time: 2026-05-03T20:55:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective
Enhance meeting layout by repositioning bottom bar tabs, creating a dedicated mobile structure with bottom-sheet side panels, and implementing active speaker highlights for both humans and AI.

### Changes Implemented

#### 1. Bottom Bar Regrouping
- **Repositioning Decision:** Moved the `Relay / Chat / People` tab cluster closer to the right side of the screen by wrapping it together with the secondary controls (Settings/Leave) in a `.room-control-right-cluster` flex container.
- **Visual Balance:** This separates the primary meeting actions (Mute/Video/Share) on the left from the navigation and utility functions on the right, removing the floating, disconnected feel of the tabs in the center.

#### 2. Dedicated Mobile Layout
- **Strategy:** Added a comprehensive `@media (max-width: 768px)` block to overhaul the mobile experience.
- **Top Bar:** Rút gọn noise bằng cách ẩn `.room-topbar-sub` và `.connection-label`, giữ cho top bar mỏng và tập trung.
- **Stage Priority:** Đặt `.meeting-stage` thành vùng ưu tiên, co giãn lấp đầy chiều cao còn trống, giữ vai trò trung tâm trên màn hình nhỏ.
- **Mobile Control Bar:** Chuyển `.room-control-bar` thành layout 2 hàng (column flex): hàng trên chứa 3 nút media (chia đều 3 cột grid), hàng dưới chứa tabs và nút chức năng dàn trải đều (space-between). Các nút to, dễ bấm hơn.
- **Mobile Panel Pattern:** Khi mở panel trên mobile, `.room-side-panel` desktop được transform thành một bottom sheet overlay (fixed bottom, slide-up animation, z-index cao), dễ thao tác bằng một tay và không đẩy meeting stage ra khỏi màn hình.

#### 3. Active Speaker Highlighting
- **Highlight Strategy:** Áp dụng hiệu ứng glowing nhẹ (`box-shadow`, `border-color` và transform `translateY(-2px)`) cho `.participant-tile.is-speaking`. Hiệu ứng có transition 240ms mượt mà để tránh nhấp nháy gắt.
- **BRSE / AI Active Speaker:** AI participant (`participant-tile-brse`) có highlight tone màu sáng và nổi bật hơn một chút để phân biệt với người dùng thông thường.
- **Detection Source:** Tích hợp trực tiếp state `isSpeaking` từ LiveKit SDK (thông qua `RoomEvent.ActiveSpeakersChanged`). Giá trị này đã được map vào `VideoFeed.isSpeaking` trong file `lib/livekit.ts` và truyền xuống `ParticipantTile`. Tránh dùng thủ thuật text relay để xác định active speaker, đảm bảo tính ổn định và real-time.

### Files Modified
- `FE/src/components/RoomControlBar.tsx` (Regrouped tabs to the right)
- `FE/src/components/ParticipantTile.tsx` (Added `.is-speaking` class dynamically)
- `FE/src/lib/livekit.ts` (Binded `RoomEvent.ActiveSpeakersChanged` & added `isSpeaking` to payload)
- `FE/src/types/livekit.ts` (Updated `VideoFeed` interface)
- `FE/src/index.css` (Added active speaker animations & new mobile responsive layout block)

### Build Check
- Test suite and build deferred (CODE-ONLY mode).

## Turn Update: 2026-05-03 Meeting Controls Polish & Panel Tabs Cohesion

- Time: 2026-05-03T20:44:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective

Refine meeting controls and navigation panel tabs to be more cohesive, Apple-like, and text-focused without using icons for main meeting actions.

### Changes Implemented

#### 1. Panel Tab Cluster Tightening
- Updated `.room-control-tabs` layout to use a segmented-control feel.
- Grouped `Relay`, `Chat`, and `People` tabs into a continuous pill cluster with `padding: 4px` and a shared dark background.
- Overrode `.panel-shortcut` spacing and active state to match the tighter visual rhythm and Apple-like aesthetic without breaking functionality.

#### 2. Meeting Control Buttons Icon Removal
- Removed icons entirely from `Mute`, `Stop video`, and `Share` buttons.
- Updated `FE/src/components/RoomControlBar.tsx` `ControlButton` component to only display `.control-btn-label`.
- Refined button padding (`padding: 0 20px`), label typography (`font-weight: 600`, `letter-spacing: 0.01em`), and text alignment to compensate for icon removal, preventing a "floating" or empty appearance.
- Replaced `.control-icon` CSS dependencies with direct styles on `.meeting-control-button` for active/muted/sharing states.

### Preserved Runtime Behavior
- Panel switching logic, Mute/Video/Share functionality, and responsive behavior remain exactly the same. No behavioral or backend changes made.

### Build Check
- Test suite and build deferred (CODE-ONLY mode).
- Testing not required per instruction.

## Turn Update: 2026-05-03 UI/UX Redesign — Apple-like, Panel Collapse, User Persistence

- Time: 2026-05-03T21:00:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective

Full UI/UX redesign of the meeting room toward a minimal, premium, Apple-like direction. Added user identity caching, collapsible side panel, and simplified relay panel.

### Changes Implemented

#### 1. User Identity Persistence

- **New file:** `FE/src/lib/userPrefs.ts`
  - `saveUserPrefs(name, language)` — writes to `localStorage` with keys `brse_display_name` / `brse_preferred_language`. No-op if storage unavailable (private browsing).
  - `loadUserPrefs()` — reads both keys, returns `{ displayName, language }`.
- **`FE/src/components/JoinRoomCard.tsx`**
  - On mount: reads saved prefs. Pre-fills `displayName` state from `brse_display_name`. Pre-selects `language` only if the saved value is still in `meetingLanguages`; otherwise falls back to `""` (safe fallback for changed language pairs).
  - On join submit: calls `saveUserPrefs()` before `onJoin()` so the latest values are always persisted.

#### 2. Side Panel Collapse / Expand

- **`FE/src/pages/RoomPage.tsx`**
  - New `sidePanelOpen` state (default `true`).
  - `room-page` gets `.panel-open` / `.panel-closed` class.
  - Panel tab buttons in `RoomControlBar` call a new `onOpenPanel` wrapper that also opens the panel if it was closed.
  - `RoomSidePanel` receives `open`, `onClose` props.
  - Relay content simplified: `TranscriptPanel` removed from relay slot — `BrseRelayPanel` now renders the full history.
- **CSS (`FE/src/index.css`)**
  - `.room-shell` uses `grid-template-columns: minmax(0,1fr) 380px` with `transition: grid-template-columns 240ms cubic-bezier(0.4,0,0.2,1)`.
  - `.room-page.panel-closed .room-shell` collapses column to `0px` — meeting stage expands to fill all available space.

#### 3. RoomSidePanel Redesign

- **`FE/src/components/RoomSidePanel.tsx`** — full rewrite
  - Props: `open`, `onClose`, `activeTab`, counts, `onTabChange`, `relay`/`chat`/`people` slots.
  - New structure: `.side-panel-header` containing `.side-panel-tabs` (segmented-pill style) + `.side-panel-close` (✕ button).
  - Tabs: compact 30px-tall segmented control, Apple pill look with white active state and subtle shadow.
  - Badge count shown only when `> 0`, minimal style.
  - `.side-panel-body` replaces old `.room-side-content` — 14px padding, clean grid.

#### 4. BrseRelayPanel Simplification

- **`FE/src/components/BrseRelayPanel.tsx`** — full rewrite
  - Removed: status cards ("AI relay is available"), "Relay State" section, status-list boxes, explanatory copy, `relay-mode-card`.
  - Now renders only a scrollable `relay-history-list` of `RelayEntry` items, or a 1-line empty state.
  - `RelayEntry`: speaker name + language tag in meta row, live-pulse dot for partial entries, relay direction badge. Source text + translated text (styled distinctly) for relay kind; source text only for human kind.
  - Auto-scroll to bottom (same threshold pattern as old `TranscriptPanel`).

#### 5. RoomControlBar Refinement

- **`FE/src/components/RoomControlBar.tsx`** — full rewrite
  - New prop: `sidePanelOpen`, `onToggleSidePanel`.
  - Three sections: media controls left, panel tab shortcuts center, secondary actions right.
  - Media buttons use emoji icons + short labels, `is-live`/`is-muted` states.
  - Secondary: `control-icon-btn` for panel toggle (⇥/⇤) and settings (⚙), `leave-button` pill.
  - Panel tab shortcuts open panel if it was closed (`onOpenPanel` wrapper in `RoomPage`).

#### 6. RoomTopBar Refinement

- **`FE/src/components/RoomTopBar.tsx`** — full rewrite
  - Layout: `.room-topbar-identity` (brand mark + name + meta sub-line) on left; controls on right.
  - Brand mark: 36×36px (down from 54×54px), tighter radius.
  - Name shown as `.room-topbar-name`, sub-line (`.room-topbar-sub`) shows room ID · language pair · participant count · timer, all in a single compact row.
  - Language selector: inline `<select>` with `topbar-lang-select` (no label wrapper, 30px height).
  - Removed old `.room-language-select` wrapper; `mode-chip` removed from topbar (BRSE toggle already shows state).
  - Connection badge and BRSE toggle remain; both visually slimmed.

#### 7. MeetingStage Cleanup

- **`FE/src/components/MeetingStage.tsx`**
  - Removed verbose `.stage-status-row` (title, kicker, two state pills).
  - Replaced with `.stage-sharer-label` shown only when screen sharing is active — one compact line.
  - Stage grid: default `minmax(0, 1fr)` single row (no top auto row); `.has-sharer-label` adds `auto` row.
  - Empty state text shortened to "Waiting for video".

#### 8. CSS Visual Direction (Apple-like)

- **`FE/src/index.css`** — multiple targeted edits + new section appended
  - Background: very dark `#080c14`, near-black.
  - Topbar: padding reduced (`8px 12px`), border-radius `18px`, `backdrop-filter: blur(24px)` with `-webkit-` prefix.
  - Control bar: 60px min-height, `border-radius: 18px`, three distinct section groups.
  - Meeting stage: padding `10px`, radius `22px`, no top status row.
  - Side panel: `border-radius: 20px`, subtle shadow, smooth opacity transition when closed.
  - New segmented tab system for side panel.
  - New relay history entry styles: clean cards, green accent for translated text, live pulse dot.
  - `topbar-lang-select`, `topbar-timer`, `room-topbar-name`, `room-topbar-sub` — new topbar identity classes.
  - BRSE toggle: slimmed to 32px height, 36px toggle track, tighter layout.
  - Connection badge: 30px height, smaller dot, lighter background.
  - Responsive: `@media (max-width: 1180px)` forces single-column layout; panel collapse is no-op on mobile (panel either shown or hidden via `display:none`).

### Architecture Note

`TranscriptPanel` is no longer rendered inside the relay tab. `BrseRelayPanel` now handles all transcript display in relay tab (both source and relay entries). `TranscriptPanel` component file is untouched and still importable for potential standalone use.

### Preserved Runtime Behavior

Join/leave room, WebSocket, LiveKit, BRSE toggle, chat, participant list, screen share, camera/mic controls — all unchanged. Session store, `useMeetingRoom`, audio sinks, settings drawer — all unchanged.

### Build Check

- `tsc --noEmit` passed clean (zero errors).
- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.

### Files Changed

| File | Action |
| --- | --- |
| `FE/src/lib/userPrefs.ts` | New |
| `FE/src/components/JoinRoomCard.tsx` | Updated (persistence) |
| `FE/src/components/RoomSidePanel.tsx` | Rewrite |
| `FE/src/components/BrseRelayPanel.tsx` | Rewrite |
| `FE/src/components/RoomControlBar.tsx` | Rewrite |
| `FE/src/components/RoomTopBar.tsx` | Rewrite |
| `FE/src/components/MeetingStage.tsx` | Updated |
| `FE/src/pages/RoomPage.tsx` | Updated |
| `FE/src/index.css` | Multiple targeted edits + new section |

---

## Turn Update: 2026-05-03 Screen Share Readability Quality Fix (Kickoff)

- Time: 2026-05-03T20:06:13+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction; no full test suite and no new tests

### Objective Locked

- Debug and fix blurry/low-resolution screen share in the meeting app.
- Trace screen-share quality end-to-end across FE capture, publish options, LiveKit source/layer behavior, subscriber/render quality, and stage CSS.
- Prioritize text/UI/code readability over webcam-style motion smoothness.
- Keep start/stop share, join/leave, camera/mic, BRSE, chat, transcript, and existing meeting stage behavior intact outside the quality path.

### Initial Trace Findings

- FE capture currently uses `createLocalScreenTracks({ audio: false, video: true })` in `FE/src/lib/livekit.ts`; no app-level readability profile, content hint, or higher-than-default screen resolution is set.
- LiveKit client defaults cap non-Safari screen capture at `h1080fps30` and publish screen share with `h1080fps15` encoding, which downscales high-resolution shared monitors/windows before participants render them.
- Screen share is correctly identified as `Track.Source.ScreenShare` by LiveKit SDK and backend metadata uses `source: "screen_share"`.
- FE render uses `VideoTrackView fit="contain"` and bounded stage CSS; no current `cover` crop/stretch path was found for active screen share.
- No backend/LiveKit YAML bitrate cap specific to screen share has been found so far.

### Final Sync

- Time: 2026-05-03T20:09:01+07:00
- Final status: screen share now uses a FE readability profile instead of default webcam-like/default screen settings.

### Root Cause Confirmed

- Primary root cause was FE screen-share capture/publish quality, not backend room metadata or LiveKit YAML.
- `createLocalScreenTracks({ audio: false, video: true })` let `livekit-client` apply its default non-Safari screen capture cap of 1920x1080 at 30fps.
- Publishing without screen-specific options used LiveKit's default screen encoding of 1080p at 15fps around 2.5 Mbps, which is too low for detailed text/code/UI from 1440p/4K shared sources.
- The active stage was already bounded and used `object-fit: contain`; no active CSS stretch/crop path was found as the blur source.
- Remote screen share subscription relied on adaptive stream defaults only; the main stage did not explicitly request the high-quality layer for the selected shared screen.
- `ops/livekit/livekit.yaml`, `ops/livekit/livekit.prod.yaml`, `docker-compose.yml`, and backend screen-share state APIs do not define a screen-share bitrate/layer cap, so no backend/LiveKit config change was needed.

### Changes Implemented

- `FE/src/lib/livekit.ts`
  - added a dedicated screen-share capture profile: 2560x1440 ideal resolution at 15fps, `contentHint="detail"`, screen audio disabled, and browser surface switching enabled.
  - kept Safari 17-based browsers on uncapped SDK capture behavior to avoid the known Safari low-resolution constraint bug.
  - publishes screen share with `source: Track.Source.ScreenShare`, `stream: "screen_share"`, simulcast enabled, `screenShareEncoding` at 6 Mbps / 15fps, and `degradationPreference: "maintain-resolution"`.
  - exposes `preferScreenShareHighQuality(...)` to request the high layer for the active remote screen share.
- `FE/src/types/livekit.ts`
  - carries the LiveKit publication with `ScreenShareFeed` so render code can control subscription quality.
- `FE/src/components/MeetingStage.tsx`
  - requests `VideoQuality.HIGH` for the selected screen-share feed shown in the main stage.

### Backend / LiveKit Config Decision

- Backend and LiveKit config were read and traced but not modified.
- Backend screen-share APIs only store/broadcast metadata (`source: "screen_share"`, track SID/name) and do not transcode or choose layers.
- Local/prod LiveKit YAML only configures signaling/RTC ports, Redis, keys, and external IP behavior; no screen-share codec/bitrate/dynacast policy is currently capping quality there.
- `docs/backend/IMPLEMENTATION_STATE.md` was not updated because no backend or LiveKit config files were changed.

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests not modified.
- Lightweight checks run:
  - `npm exec tsc -- -p tsconfig.app.json` from `FE/`
  - `git diff --check`
- Both checks passed.

### Follow-Up Smoothness Tune

- Time: 2026-05-03T20:14:38+07:00
- Updated screen-share capture and publish framerate from 15fps to 24fps for smoother demos while keeping the same readability-first profile:
  - 2560x1440 ideal capture resolution.
  - `contentHint="detail"`.
  - 6 Mbps screen-share encoding.
  - `degradationPreference: "maintain-resolution"`.
- Full test suite still not run, per CODE-ONLY instruction.
- Lightweight checks re-run:
  - `npm exec tsc -- -p tsconfig.app.json` from `FE/`
  - `git diff --check`
- Both checks passed.

## Turn Update: 2026-05-02 Screen Share Stage Layout Fix (Kickoff)

- Time: 2026-05-02T14:51:23+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction; no full test suite and no new tests

### Objective Locked

- Fix the meeting screen-share presentation so large shared monitors/windows cannot resize the outer meeting layout.
- Keep LiveKit track handling, start/stop share flow, participant state, BRSE, chat, relay, settings, and backend runtime paths unchanged.
- Make the shared screen stage size predictable on desktop and keep side panel, video tiles, and controls usable while sharing.

### Initial Root Cause

- The active screen-share branch uses `.screen-share-frame` with only a `min-height` and no firm height/max-height boundary.
- The screen-share branch sits in flexible grid rows, so the stage can grow with available/intrinsic child sizing instead of staying bounded.
- The video element already uses `object-fit: contain`, but its parent does not consistently constrain block size or overflow, allowing large source resolutions to affect surrounding layout.

### Planned Layout Strategy

- Add explicit desktop-first sizing tokens for the meeting shell and shared stage.
- Make the screen-share stage a bounded grid container with a stable media surface height.
- Keep shared video at `width: 100%`, `height: 100%`, `object-fit: contain`, and clamp overflow at the frame/stage boundaries.
- Convert participant tiles under a share into a controlled filmstrip so they cannot stretch the share stage or side panel.

### Final Sync

- Time: 2026-05-02T14:55:16+07:00
- Final status: screen share now renders inside a bounded meeting stage instead of allowing large shared sources to expand the room layout.

### Root Cause Confirmed

- The screen-share frame had only a minimum height and inherited flexible grid sizing from the surrounding stage.
- The outer room shell did not fully constrain overflow on desktop, so the share branch could push the stage/page rather than fitting into a predictable viewport region.
- `object-fit: contain` was present on the share video, but it was not enough without a fixed parent media surface.

### Files Modified

- `FE/src/components/MeetingStage.tsx`
  - split the screen-share branch into `SharedScreenStage`, `ParticipantGrid`, and `ParticipantFilmstrip`.
  - kept track rendering and selected sharer/feed logic unchanged.
- `FE/src/index.css`
  - added desktop viewport-bound layout constraints for `.room-page`, `.room-shell`, `.room-main-column`, and `.meeting-stage`.
  - gave `.screen-share-frame` a predictable clamp-based height and hard overflow boundary.
  - kept shared media on `object-fit: contain` with full-width/full-height rendering inside the bounded frame.
  - converted participant tiles during screen share into a fixed-height horizontal filmstrip.
- `docs/frontend/IMPLEMENTATION_STATE.md`
  - documented root cause, sizing strategy, fit/overflow strategy, modified files, and deferred testing.

### Sizing / Fit / Overflow Strategy

- Desktop meeting page is viewport-bound with internal scrolling/overflow at the alert stack, side panel, stage grid, and filmstrip boundaries.
- Shared screen frame uses `--screen-share-frame-height: clamp(340px, 58vh, 700px)`, capped to available stage height, with `overflow: hidden` and layout containment.
- Shared video remains `object-fit: contain`, so 4:3, 16:9, and ultrawide sources fit inside the frame without changing the outer layout.
- Participant tiles under an active share use a fixed-height horizontal strip; labels truncate and badges are hidden in the strip to prevent tile content from resizing the stage.
- Below desktop breakpoint, the room page can scroll vertically while the share frame remains clamped and bounded.

### Verification

- Testing deferred per instruction.
- Full test suite not run.
- New tests not added.
- Existing tests not modified.

### Follow-Up Crop Fix

- Time: 2026-05-02T15:04:20+07:00
- Issue observed: the bounded stage prevented page expansion, but the shared source could still appear vertically cropped when the available stage was much wider than it was tall.
- Cause: the frame used a fixed clamped height while still stretching to the full stage width, creating an ultrawide render box where any `cover` fallback looked cropped.
- Fix:
  - `VideoTrackView` now supports explicit `fit="contain"` and optional class names.
  - Screen share rendering passes `fit="contain"` with `screen-share-video`.
  - `.screen-share-frame` now keeps a 16:9 media surface and centers it, shrinking width when height is constrained instead of cropping the video.
  - The filmstrip remains full-width and fixed-height below the share surface.
- Testing still deferred per instruction.

### Follow-Up Hard 16:9 Fit

- Time: 2026-05-02T15:13:24+07:00
- Issue observed: stretching the browser horizontally could still produce a share surface wider than the available stage height, causing the visible video area to look clipped.
- Fix:
  - Added a measured `StageMediaSurface` around screen share rendering.
  - The surface uses `ResizeObserver` to read the actual available stage slot and computes the largest rectangle that fits inside it at exactly 16:9.
  - `.screen-share-frame` no longer relies on a fixed height clamp for desktop sizing; runtime style sets exact 16:9 width/height from the measured slot.
  - The screen-share video remains `object-fit: contain`, so the full shared screen stays visible inside the hard 16:9 frame.
- Testing still deferred per instruction.

## Turn Update: 2026-05-02 Room Expiry Exit Enforcement (Kickoff)

- Time: 2026-05-02T14:20:55+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction; no full test suite and no new tests

### Objective Locked

- Enforce the 30-minute room expiry in the frontend runtime, not only in countdown UI.
- When `expires_at` is reached or backend reports expiry, shut down the active room session and take the user out of the meeting screen.
- Prevent Gateway WebSocket reconnects, LiveKit reconnects, local media, screen share, or stale callbacks from reviving an expired room.
- Keep create/join/leave/chat/screen-share/BRSE/host flows unchanged outside the expiry path.

### Mandatory Read Status

- Read required docs:
  - `docs/frontend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Read required FE runtime files:
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/pages/RoomPage.tsx`
  - `FE/src/lib/ws.ts`
  - `FE/src/lib/api.ts`
  - `FE/src/types/api.ts`
  - `FE/src/types/ws.ts`
  - related routing/join/create/landing files:
    - `FE/src/App.tsx`
    - `FE/src/pages/HomePage.tsx`
    - `FE/src/components/JoinRoomCard.tsx`
    - `FE/src/components/RoomTopBar.tsx`
    - `FE/src/features/room/useRoomExpiry.ts`
    - `FE/src/state/session.tsx`
    - `FE/src/lib/livekit.ts`

### Initial Expiry Exit Strategy

- Add a centralized expired-room shutdown path in `useMeetingRoom`.
- Trigger it from:
  - local `expires_at` timer
  - immediate stale `expires_at` detection on session/snapshot hydration
  - `room.expired` Gateway event
  - backend `room_expired` WebSocket error or expired close code
- Use an `expiredShutdown` guard alongside existing manual shutdown guards so reconnect/lifecycle callbacks cannot revive an expired room.
- UX strategy: cleanly leave the room screen and redirect to the landing page with the short message "This meeting has ended."
- Refreshing/opening an already expired room link should stay out of meeting UI and show the existing expired join/interstitial state.

### Final Sync

- Time: 2026-05-02T14:27:33+07:00
- Final status: frontend now enforces room expiry as a runtime shutdown path instead of a countdown-only UI state.

### Expiry Exit Strategy Implemented

- Active meeting expiry exits the room screen.
- `RoomPage` redirects to `/` with landing state notice:
  - `This meeting has ended.`
- Expired room links without an active session remain out of meeting UI and use the existing expired join/interstitial state.
- Join attempts against expired rooms are still blocked locally when `expires_at` is stale and by backend `410 room_expired`.

### Expiry Triggers

- Local timer from authoritative `expires_at` in the live room/session metadata.
- Immediate expired `expires_at` check on active session hydration.
- Expired `expires_at` from Gateway `room.snapshot`.
- Gateway `room.expired` event.
- Gateway `error` event with `code=room_expired`.
- WebSocket close code `4410` now treated as fatal room expiry.
- Focus/pageshow/visibility checks re-run the local expiry guard after tab sleep/background throttling.

### Cleanup Path On Expiry

- Centralized shutdown function: `shutdownExpiredRoomSession(...)` in `FE/src/features/room/useMeetingRoom.ts`.
- Sets `expiredShutdownRef` and `manualShutdownRef` so stale Gateway/LiveKit callbacks cannot revive room state.
- Stops Gateway reconnect by intentionally disconnecting the retained Gateway socket.
- Disconnects LiveKit and stops/unpublishes local microphone, camera, and screen-share tracks through the existing LiveKit cleanup helpers.
- Sends best-effort screen-share stop before teardown when a local share is active.
- Clears local meeting runtime state: participants, self state, transcripts, chat sends, media feeds, interpreter status, device state, host/moderation state, and transient errors.
- Invalidates the stored room session after cleanup so reload/re-render cannot re-enter the expired session.

### Files Modified

- `FE/src/features/room/useMeetingRoom.ts`
  - added `expiredShutdownRef`, `RoomExpiredDetails`, local expiry enforcement, backend expiry handling, and centralized expired-session cleanup.
  - hardened async Gateway/LiveKit/media lifecycle checks against expired shutdown.
  - guarded chat, BRSE toggle, language change, media, screen share, and moderation actions after expiry.
- `FE/src/lib/ws.ts`
  - treats Gateway close code `4410` as fatal so room expiry reaches the hook.
- `FE/src/pages/RoomPage.tsx`
  - passes `onRoomExpired` callback that clears the session and redirects to landing.
- `FE/src/pages/HomePage.tsx`
  - displays the short landing notice after expiry redirect.
- `docs/frontend/IMPLEMENTATION_STATE.md`
  - documented this implementation and verification status.

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests not modified.
- Lightweight checks run:
  - `npm exec tsc -- -p tsconfig.app.json` from `FE/`
  - `git diff --check`
- Both checks passed.

## Turn Update: 2026-05-02 MeetQ CDN Frontend Multi-Origin Runtime Config (Kickoff)

- Time: 2026-05-02T03:42:26+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction; no full test suite and no new tests

### Objective Locked

- Update FE production config for a CDN/static-app deployment on `https://meetqapp.com`.
- Use separate production Gateway API origin `https://api.meetqapp.com`.
- Use separate production Gateway WebSocket origin `wss://api.meetqapp.com`.
- Keep LiveKit production signaling on `wss://rtc.meetqapp.com`.
- Keep invite/share links on the FE public origin `https://meetqapp.com`.
- Preserve local dev behavior with localhost env defaults.

### Mandatory Read Status

- Read required docs:
  - `docs/frontend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Read required FE runtime/config files:
  - `FE/src/lib/api.ts`
  - `FE/src/lib/ws.ts`
  - `FE/src/lib/livekit.ts`
  - `FE/src/lib/urls.ts`
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/types/api.ts`
  - `FE/src/types/ws.ts`
  - `FE/.env.example`
  - `FE/.env.development`
  - `FE/.env.production`
  - `FE/vite.config.ts`
  - `FE/vite.config.js`
  - `FE/vite.config.d.ts`
  - `FE/package.json`
- Current finding:
  - previous FE production strategy still allowed same-origin API/WS fallback from `meetqapp.com`.
  - current deployment requirement explicitly separates FE CDN origin from Gateway API/WS origin.

### Initial Implementation Plan

- Change FE URL helper defaults to distinct production app/API/WS/RTC origins.
- Add clear env names for the multi-origin model:
  - `VITE_APP_ORIGIN`
  - `VITE_API_BASE_URL`
  - `VITE_WS_BASE_URL`
  - `VITE_LIVEKIT_WS_URL`
- Keep old env aliases temporarily readable for compatibility, but document the new names as canonical.
- Update FE env templates for production and local dev.
- Re-run URL hardcode search and lightweight FE typecheck.
- Final state update will record the CDN deployment mapping and verification status.

### Final Sync

- Time: 2026-05-02T03:44:07+07:00
- Final status: FE runtime config now matches the CDN frontend + separate Gateway API/WS + separate LiveKit production topology.
- This supersedes the immediately previous same-origin production strategy entry.

### FE-on-CDN Production Mapping

- App / invite origin:
  - `https://meetqapp.com`
  - source of truth: `VITE_APP_ORIGIN`
  - used by invite/share URL helpers only
- Gateway REST origin:
  - `https://api.meetqapp.com`
  - source of truth: `VITE_API_BASE_URL`
  - existing FE route paths like `/api/rooms` now resolve to `https://api.meetqapp.com/api/rooms`
- Gateway WebSocket origin:
  - `wss://api.meetqapp.com`
  - source of truth: `VITE_WS_BASE_URL`
  - relative backend WS payloads like `/ws/rooms/...` now resolve to `wss://api.meetqapp.com/ws/rooms/...`
- LiveKit signaling:
  - `wss://rtc.meetqapp.com`
  - source of truth: backend `join.livekit.url`, with `VITE_LIVEKIT_WS_URL` as the production-safe fallback

### Runtime Resolution Strategy

- `FE/src/lib/urls.ts`
  - production defaults are now explicit:
    - `PRODUCTION_APP_ORIGIN=https://meetqapp.com`
    - `PRODUCTION_API_BASE_URL=https://api.meetqapp.com`
    - `PRODUCTION_GATEWAY_WS_BASE_URL=wss://api.meetqapp.com`
    - `PRODUCTION_LIVEKIT_WS_URL=wss://rtc.meetqapp.com`
  - `getPublicAppOrigin()` no longer uses browser origin as production fallback.
  - `getApiBaseUrl()` no longer falls back to app origin in production.
  - `resolveGatewayWebSocketUrl()` no longer derives production WS from the FE CDN origin.
  - absolute backend-returned WS URLs are still preserved as-is.
  - old aliases remain readable for compatibility:
    - `VITE_PUBLIC_APP_URL`
    - `VITE_GATEWAY_WS_BASE_URL`
- `FE/src/lib/api.ts`
  - still calls local route paths (`/api/...`) but resolves them through the explicit API origin.
- `FE/src/lib/ws.ts`
  - room WebSocket connects through `resolveGatewayWebSocketUrl(...)`.
- `FE/src/lib/livekit.ts`
  - LiveKit connect still prioritizes backend join payload URL and only uses RTC fallback when payload is empty/relative.
- `FE/src/features/test/useMicTest.ts`
  - mic-test WebSocket uses the same Gateway WS resolver.
- `FE/src/features/test/useTranslationTest.ts`
  - translation-test WebSocket uses the same Gateway WS resolver.

### Env / Config Files

- `FE/.env.example`
  - documents local dev and production multi-origin values.
- `FE/.env.development`
  - `VITE_APP_ORIGIN=http://localhost:3000`
  - `VITE_API_BASE_URL=http://localhost:8000`
  - `VITE_WS_BASE_URL=ws://localhost:8000`
  - `VITE_LIVEKIT_WS_URL=ws://localhost:7880`
- `FE/.env.production`
  - `VITE_APP_ORIGIN=https://meetqapp.com`
  - `VITE_API_BASE_URL=https://api.meetqapp.com`
  - `VITE_WS_BASE_URL=wss://api.meetqapp.com`
  - `VITE_LIVEKIT_WS_URL=wss://rtc.meetqapp.com`
- `FE/src/vite-env.d.ts`
  - added `VITE_APP_ORIGIN` and `VITE_WS_BASE_URL` typings.
- `FE/Dockerfile`
  - build args/env defaults now match the multi-origin production values.

### Localhost Assumption Review

- Production-facing same-origin assumption removed from API/WS defaults.
- Remaining localhost references are intentional local development config only:
  - `FE/.env.development`
  - local-dev section of `FE/.env.example`
  - local-dev constants in `FE/src/lib/urls.ts`
- Search covered:
  - `localhost`
  - `127.0.0.1`
  - `:3000`
  - `:8000`
  - `:7880`
  - `meetqapp.com`
  - `api.meetqapp.com`
  - `rtc.meetqapp.com`
  - old env aliases

### CORS Assumption

- FE now behaves as a cross-origin frontend for production API/WS calls.
- Backend production must allow browser origin `https://meetqapp.com`.
- No backend files were changed in this turn.

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests not modified.
- Lightweight checks run:
  - `git diff --check`
  - `npm exec tsc -- -p tsconfig.app.json` from `FE/`
- Typecheck status: passed.

## Turn Update: 2026-05-02 MeetQ Production Domain Runtime Config (Kickoff)

- Time: 2026-05-02T03:29:32+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction; no full test suite and no new tests

### Objective Locked

- Make the frontend production-ready for `https://meetqapp.com`.
- Keep Gateway REST/WS on app origin in production.
- Use backend/join payload LiveKit URL, with production-safe support for `wss://rtc.meetqapp.com`.
- Remove production-facing localhost assumptions while preserving local dev fallback.

### Mandatory Read Status

- Read required docs:
  - `docs/frontend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Read required FE runtime/config files:
  - `FE/src/lib/api.ts`
  - `FE/src/lib/ws.ts`
  - `FE/src/lib/livekit.ts`
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/types/api.ts`
  - `FE/src/types/ws.ts`
  - `FE/vite.config.ts`
  - `FE/vite.config.js`
  - `FE/vite.config.d.ts`
  - `FE/package.json`
  - `FE/src/main.tsx`
  - `FE/src/App.tsx`
  - related room/create/session files:
    - `FE/src/pages/HomePage.tsx`
    - `FE/src/pages/RoomPage.tsx`
    - `FE/src/state/session.tsx`
- Current finding:
  - no existing `FE/.env*` files are present.
  - FE already resolves relative Gateway WS from API origin.
  - API base now has same-origin production fallback, but URL behavior is not centralized or documented in FE env templates.
  - LiveKit room flow uses `join.livekit.url`; no direct production LiveKit fallback should point to local ports.

### Initial Implementation Plan

- Add a small FE URL helper for app origin, API base, Gateway WS, LiveKit URL, and invite/share URL resolution.
- Update API and WS code to use that helper and keep local dev fallback isolated.
- Add FE env templates for local dev and production domain values.
- Adjust create/join/share behavior so production invite links resolve to `https://meetqapp.com`.
- Search FE hardcoded `localhost`, `127.0.0.1`, `:3000`, `:8000`, and `:7880`; keep only dev-only config/template references.
- Final state update will document production URL strategy, files changed, and verification status.

### Final Sync

- Time: 2026-05-02T03:34:00+07:00
- Final status: frontend production URL/runtime config is ready for `https://meetqapp.com` and `wss://rtc.meetqapp.com`.

### Production Domain Strategy

- App public origin:
  - canonical production app origin is `https://meetqapp.com`
  - production invite/share URL helper resolves room paths against `https://meetqapp.com`
- Gateway REST:
  - FE calls existing `/api/...` route paths through centralized `buildApiUrl(...)`
  - production default API base resolves to app public origin, so requests go to `https://meetqapp.com/api/...`
  - local development uses `http://localhost:8000`
- Gateway WebSocket:
  - room/test WS URLs now use centralized `resolveGatewayWebSocketUrl(...)`
  - absolute backend URLs are preserved
  - relative backend URLs resolve from the API/app origin, so production becomes `wss://meetqapp.com/ws/...`
  - local development resolves to `ws://localhost:8000/ws/...`
- LiveKit:
  - room join still uses backend `join.livekit.url` as the authoritative URL
  - LiveKit connect now passes the URL through `resolveLiveKitUrl(...)`
  - empty/relative fallback is production-safe: `wss://rtc.meetqapp.com`
  - local development fallback remains `ws://localhost:7880`

### Files Modified / Added

- `FE/src/lib/urls.ts`
  - added centralized URL helpers:
    - `getPublicAppOrigin`
    - `getApiBaseUrl`
    - `buildApiUrl`
    - `resolveGatewayWebSocketUrl`
    - `resolveLiveKitUrl`
    - `resolveInviteUrl`
    - `buildRoomInviteUrl`
- `FE/src/lib/api.ts`
  - API URL building now delegates to `FE/src/lib/urls.ts`
  - preserves public exports for existing callers
- `FE/src/lib/ws.ts`
  - Gateway room socket now resolves URLs through `resolveGatewayWebSocketUrl`
- `FE/src/lib/livekit.ts`
  - `connectLiveKit` now resolves backend/fallback LiveKit URLs through `resolveLiveKitUrl`
  - insecure-context message no longer mentions localhost in user-facing runtime copy
  - added a small track-name cast helper so the current LiveKit SDK types pass typecheck
- `FE/src/features/test/useMicTest.ts`
  - mic test WebSocket resolution now uses centralized Gateway WS helper
- `FE/src/features/test/useTranslationTest.ts`
  - translation test WebSocket resolution now uses centralized Gateway WS helper
- `FE/src/vite-env.d.ts`
  - added env typing for:
    - `VITE_PUBLIC_APP_URL`
    - `VITE_API_BASE_URL`
    - `VITE_GATEWAY_WS_BASE_URL`
    - `VITE_LIVEKIT_WS_URL`
- `FE/.env.example`
  - documented local development and production public URL values
- `FE/.env.development`
  - local dev defaults:
    - `VITE_API_BASE_URL=http://localhost:8000`
    - `VITE_PUBLIC_APP_URL=http://localhost:3000`
    - `VITE_LIVEKIT_WS_URL=ws://localhost:7880`
- `FE/.env.production`
  - production defaults:
    - `VITE_API_BASE_URL=`
    - `VITE_PUBLIC_APP_URL=https://meetqapp.com`
    - `VITE_LIVEKIT_WS_URL=wss://rtc.meetqapp.com`
- `.gitignore`
  - whitelisted the public FE env files so production/development URL templates can be tracked.

### Localhost Assumption Review

- Production-facing localhost assumptions removed from runtime API/WS/LiveKit resolution paths.
- Remaining localhost references in FE are limited to:
  - `FE/.env.development`
  - local-development section of `FE/.env.example`
  - local-dev fallback constants in `FE/src/lib/urls.ts`
- Search covered:
  - `localhost`
  - `127.0.0.1`
  - `:3000`
  - `:8000`
  - `:7880`
  - `ws://`
  - `wss://`
  - `meetqapp.com`
  - `rtc.meetqapp.com`

### Verification

- Full test suite not run, per CODE-ONLY instruction.
- New tests not added.
- Existing tests not modified.
- Lightweight checks run:
  - `git diff --check`
  - `npm exec tsc -- -p tsconfig.app.json` from `FE/`
- Typecheck status:
  - passes after the small LiveKit track-name type compatibility helper.

## Turn Update: 2026-05-02 MeetQ Frontend Branding Rename (Kickoff)

- Time: 2026-05-02T03:06:33+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction; no tests, build, typecheck, or runtime verification will be run this turn

### Objective Locked

- Rename user-facing frontend product branding from the old `brseAI` brand to `MeetQ`.
- Replace user-facing monogram/logo text with `MQ`.
- Update browser title/tab branding.
- Preserve room/create/join/meeting runtime behavior and keep BRSE/AI relay terminology only where it is feature semantics.

### Mandatory Read Status

- Read required docs/files:
  - `docs/frontend/IMPLEMENTATION_STATE.md`
  - `FE/index.html`
  - `FE/package.json`
  - `FE/src/App.tsx`
  - `FE/src/main.tsx`
  - `FE/src/pages/*`
  - `FE/src/components/*`
  - `FE/src/index.css`
- `FE/public` has no files in this workspace.
- Searched `FE/src`, `FE/index.html`, `FE/package.json`, and Vite config for title/brand/logo/old-brand strings.

### Branding Strategy

- Change product surfaces:
  - browser title: `MeetQ`
  - landing brand mark: `MQ`
  - meeting top-bar brand mark: `MQ`
- Keep/clarify relay feature semantics:
  - `BRSE relay`
  - `AI relay participant`
  - internal `brse_*` protocol/type/runtime identifiers
- Replace ambiguous user-facing `BRSE AI` labels with `AI relay` / `AI Relay` so they no longer read like old product branding.
- Do not rename backend-facing or protocol identifiers.

### Final Sync

- Time: 2026-05-02T03:08:09+07:00
- Final status: frontend branding rename implemented.

### Branding Applied

- Product name:
  - Browser title changed from `brseAI Meeting` to `MeetQ`.
  - Landing header product text changed to `MeetQ`.
  - FE package metadata changed to `meetq-frontend`.
- Monogram/logo:
  - Landing brand mark changed from `brseAI` to `MQ`.
  - Meeting top-bar brand mark changed from `brseAI` to `MQ`.
- Relay/virtual participant wording:
  - User-facing `BRSE AI` labels were normalized to `AI relay` / `AI Relay`.
  - `BRSE relay` remains where it describes the room mode/feature.
  - Internal protocol/runtime identifiers such as `brse_ai`, `virtual_brse`, `brse_enabled`, and `room.brse_*` were intentionally kept.

### Files Modified

- `FE/index.html`
- `FE/package.json`
- `FE/package-lock.json`
- `FE/src/pages/HomePage.tsx`
- `FE/src/components/RoomTopBar.tsx`
- `FE/src/components/JoinRoomCard.tsx`
- `FE/src/components/ParticipantList.tsx`
- `FE/src/components/ParticipantTile.tsx`
- `FE/src/components/BrseRelayPanel.tsx`
- `FE/src/components/InterpreterStatusPanel.tsx`
- `FE/src/features/room/transcripts.ts`
- `FE/src/features/room/interpreter.ts`
- `FE/src/lib/livekit.ts`
- `docs/frontend/IMPLEMENTATION_STATE.md`

### Search / Residuals

- Searched `FE` excluding `node_modules`; no remaining `brseAI`, `brseAi`, `brseai`, `BRSE AI`, or `brse AI` strings.
- Remaining `BRSE relay` and `brse_*` strings are feature/protocol semantics, not product branding.

### Testing

- Deferred per instruction:
  - no tests run
  - no tests written
  - no tests changed
  - no build/typecheck/runtime verification run

---

## Turn Update: 2026-05-02 Create + Join Copy Reduction Redesign (Kickoff)

- Time: 2026-05-02T02:58:15+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction; no tests, build, typecheck, or runtime verification will be run this turn

### Objective Locked

- Reduce copy and visual noise on the create-room landing screen and join-room screen.
- Preserve create room, open existing room, room fetch, join, expiry, meeting language pair, BRSE mode, and participant preview runtime flows.
- Keep full language names everywhere user-facing language choices appear.

### Mandatory Read Status

- Read required docs:
  - `docs/frontend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Read required FE paths:
  - `FE/src/pages/HomePage.tsx`
  - `FE/src/pages/RoomPage.tsx`
  - `FE/src/components/JoinRoomCard.tsx`
  - `FE/src/types/api.ts`
  - `FE/src/lib/api.ts`
  - `FE/src/lib/languages.ts`
  - `FE/src/index.css`
- Related create/join component search completed across `FE/src/components` and `FE/src/pages`.

### Initial Text Reduction Strategy

- Create room:
  - Replace marketing-style intro with one short action title.
  - Remove long subtitle/proof text and repeated meeting bridge explanation.
  - Keep language pair selection, compact duration/mode badges, Create Room CTA, and a small open-existing row.
- Join room:
  - Remove duplicate room summary panel.
  - Keep one compact context strip for room id, full language bridge, mode, and time.
  - Keep form copy to labels only plus the Join CTA.
  - Make "Already inside" a compact preview, not a dashboard panel.

### Final Sync

- Time: 2026-05-02T03:01:46+07:00
- Final status: create-room and join-room copy reduction redesign implemented.

### Layout Strategy Implemented

- Create room:
  - Replaced the previous two-column landing composition with a single compact create-room panel.
  - Header now has only brand + quiet `Mic test` link.
  - Primary action surface now contains: short title, two language selectors, compact `30 min` / `BRSE relay` badges, and `Create Room`.
  - `Open room` is a small secondary panel under the create action.
- Join room:
  - Replaced multi-panel join layout with one primary join card.
  - Context is now a single compact strip: room id badge, language bridge, mode, time.
  - Form has only `Your name`, `Your language`, and `Join Meeting`.
  - Participant preview sits below the form as compact supporting context.

### Components / Refactor

- `FE/src/pages/HomePage.tsx`
  - Added local `CreateRoomPanel`.
  - Added local `JoinExistingRoomPanel`.
  - Kept `LanguageSelectCard` but reduced surrounding copy.
- `FE/src/components/JoinRoomCard.tsx`
  - Removed `RoomMetadataList`.
  - Added local `CompactMeta` for the single metadata strip.
  - Kept `RoomModeBadge` and `ParticipantPreviewList`, with shorter labels/copy.

### Text / Duplication Reduction

- Removed from create screen:
  - long landing headline
  - long explanatory subtitle
  - proof pill row
  - repeated `Meeting bridge` preview
  - standalone 30-minute explanation block
- Removed from join screen:
  - explanatory header paragraph
  - duplicated room summary panel
  - duplicated meeting language summary inside the form
  - duplicated room mode / room id / time rows
  - long empty participant explanation
- Kept full language names through existing language helpers and select options.
- Room policy and BRSE state are now compact badges/metadata only.

### Files Modified

- `FE/src/pages/HomePage.tsx`
- `FE/src/components/JoinRoomCard.tsx`
- `FE/src/index.css`
- `docs/frontend/IMPLEMENTATION_STATE.md`

### Testing

- Deferred per instruction:
  - no tests run
  - no tests written
  - no tests changed
  - no build/typecheck/runtime verification run

---

## Turn Update: 2026-05-02 Join Room Product Redesign (Kickoff)

- Time: 2026-05-02T02:47:45+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction; no tests, build, typecheck, or runtime verification will be run this turn

### Objective Locked

- Redesign the pre-join room screen so the join form is the primary action.
- Keep room fetch, join contract, room expiry, meeting language pair, BRSE mode, and participant preview behavior unchanged.
- Reduce room id prominence from hero headline to compact metadata.
- Present room metadata, meeting languages, BRSE/normal mode, and "already inside" as scan-friendly supporting context.

### Mandatory Read Status

- Read required docs:
  - `docs/frontend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Read required FE paths:
  - `FE/src/pages/HomePage.tsx`
  - `FE/src/pages/RoomPage.tsx`
  - `FE/src/components/JoinRoomCard.tsx`
  - `FE/src/components/RoomTopBar.tsx`
  - `FE/src/components/ParticipantList.tsx`
  - `FE/src/types/api.ts`
  - `FE/src/lib/api.ts`
  - `FE/src/lib/languages.ts`
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/index.css`

### Initial Layout Strategy

- Replace the current split hero/card layout with a compact pre-join product surface.
- Put a room summary strip above the action area: room id badge, full language bridge, mode badge, participant count, expiry.
- Make the join form the largest and most visually weighted card.
- Move participants into a secondary preview panel with compact empty/human/virtual states.

### Final Sync

- Time: 2026-05-02T02:53:59+07:00
- Final status: join room product redesign implemented in the FE runtime path.

### Layout Strategy Implemented

- `JoinRoomCard` no longer uses a split dark hero where `room_id` is the main headline.
- The screen now uses a compact hierarchy:
  - top summary: "Enter the room", short helper copy, compact room id badge
  - context strip: meeting languages, BRSE/normal mode, participant count, time remaining
  - primary card: join form
  - secondary context: room summary metadata and participant preview
- Desktop layout uses the form as the visual anchor with room metadata and participants in a narrower support column.
- Responsive layout stacks the summary, form, metadata, and participant preview without preserving the old unbalanced split.

### Components / Refactor

- `FE/src/components/JoinRoomCard.tsx`
  - Refactored presentation into local subcomponents:
    - `RoomModeBadge`
    - `RoomMetadataList`
    - `ParticipantPreviewList`
  - Kept existing props and `onJoin` payload unchanged.
  - Kept display-name validation, meeting-language validation, expired-room block, and join submit flow unchanged.

### Room Metadata Presentation

- Room id is now a compact badge and metadata row, not hero text.
- Meeting languages use full language names via `formatMeetingLanguageBridge`.
- BRSE state is shown as `BRSE relay enabled`; BRSE off shows `Normal meeting`.
- Metadata is presented as a scan-friendly list:
  - Room ID
  - Meeting languages
  - Mode
  - Participants
  - Time remaining / expiry
  - Host when available from snapshot participants

### Already Inside Handling

- Human participants are counted separately from virtual participants.
- Empty human state is compact: "No human participants yet" plus a small BRSE AI note when the virtual participant exists.
- Human participants render in a compact list with status, language, and host badge when applicable.
- BRSE AI renders as a clearly labeled virtual relay participant and no longer dominates the pre-join screen.

### Files Modified

- `FE/src/components/JoinRoomCard.tsx`
- `FE/src/index.css`
- `docs/frontend/IMPLEMENTATION_STATE.md`

### Testing

- Deferred per instruction:
  - no tests run
  - no tests written
  - no tests changed
  - no build/typecheck/runtime verification run

---

## Turn Update: 2026-05-01 Room Policy UI — 30-Min Duration + No Participant Cap (Completed)

- Time: 2026-05-01T21:00:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes, per instruction

### Objective

Reflect new room policy on the frontend:
1. Meeting duration is 30 minutes — users must see this clearly at create/join/in-room stages.
2. `participant_limit` is now `null` (no hard cap) — remove all `/8`-style cap UI.
3. Room expiry is the source of truth — FE uses `expires_at` from backend.
4. Expired room handling: block join, show clear state, handle in-room expiry gracefully.

### Strategy

**Expiry/Timer UX:**
- Create `useRoomExpiry(expiresAt)` hook that computes `remainingMs`, `remainingLabel`, and `isExpired` on a 1-second ticker.
- `expiresAt` comes from `room.expires_at` in the room snapshot/join response.
- Countdown format: `MM:SS` when < 10 min, `Xm` when > 10 min.
- When expired: ticker stops, `isExpired = true`, UI switches to expired state.
- Room timer shown in `RoomTopBar` in place of bare participant count.
- Join card shows `expires_at` as a human-readable "expires at HH:MM" context.
- Create room page shows "Meetings last 30 minutes" hint near the CTA.

**Participant-Cap UI Changes:**
- `RoomSummary.participant_limit` typed as `number | null` (was `number`).
- All `{count}/{limit}` patterns removed from `JoinRoomCard`.
- `RoomTopBar` participant count shown without any cap suffix.
- `room.snapshot` WS type updated: `participant_limit: number | null`.
- No new cap-related wording added anywhere.

**Expired-Room Handling:**
- `mapRoomSnapshotError` handles `410 / room_expired` → "This room has expired."
- `mapJoinError` handles `room_expired` → clear message, disables join.
- `JoinRoomCard` receives `isExpired` prop; when true: disables form, shows banner.
- `useMeetingRoom` handles `room.expired` WS event: sets `isRoomExpired = true`, locks UI actions.
- `RoomPage` checks expiry at load (from snapshot `expires_at`) and during session (from `useMeetingRoom`).

### Files to Modify

- `FE/src/types/api.ts` — `participant_limit: number | null`
- `FE/src/types/ws.ts` — `participant_limit: number | null` in snapshot room, add `RoomExpiredEvent`
- `FE/src/features/room/useRoomExpiry.ts` — new hook (countdown + expired state)
- `FE/src/features/room/useMeetingRoom.ts` — expose `expiresAt`, `isRoomExpired`; handle `room.expired` WS event
- `FE/src/components/JoinRoomCard.tsx` — remove cap display, show expiry context, handle expired
- `FE/src/pages/HomePage.tsx` — add "Meetings last 30 minutes" hint
- `FE/src/components/RoomTopBar.tsx` — show time remaining, remove cap suffix
- `FE/src/pages/RoomPage.tsx` — wire expiry hook, pass `isExpired` + `expiresAt`, handle 410 on load/join
- `FE/src/index.css` — timer chip styles, expiry banner styles

### Files Modified

- `FE/src/types/api.ts` — `participant_limit: number | null`
- `FE/src/types/ws.ts` — `participant_limit: number | null` in snapshot room; added `expires_at?`; added `RoomExpiredEvent`; `RoomExpiredEvent` added to `ServerEvent` union
- `FE/src/features/room/useRoomExpiry.ts` — new hook: countdown ticker, `remainingLabel`, `isExpired`, `formatExpiresAtHuman`
- `FE/src/features/room/useMeetingRoom.ts` — imported `RoomExpiredEvent`; added `isRoomExpired` state; handles `room.expired` WS event via `applyRoomExpired`; `applyRoomSnapshot` now propagates `expires_at` from WS payload; return object exposes `expiresAt` and `isRoomExpired`; session reset clears `isRoomExpired`
- `FE/src/components/JoinRoomCard.tsx` — removed `{count}/{limit}` display; shows `participant_count` only; shows `expires_at` as "Expires at HH:MM"; accepts `isExpired` prop; when expired renders `room-expired-state` block and disables form
- `FE/src/pages/HomePage.tsx` — added "Meetings last 30 minutes" `create-room-policy-note` above Create Room CTA
- `FE/src/components/RoomTopBar.tsx` — accepts `expiresAt` prop; uses `useRoomExpiry`; shows `room-timer-chip` in meta line ("Xm left" / "MM:SS left" / "Meeting ended")
- `FE/src/pages/RoomPage.tsx` — uses `useRoomExpiry`; derives `isRoomExpired` from timer + backend + WS; shows dedicated expired page when room is expired pre-join; passes `isExpired` to `JoinRoomCard`; passes `expiresAt` to `RoomTopBar`; shows `banner-room-expired` in-room when expired; maps `room_expired` (410) in both `mapRoomSnapshotError` and `mapJoinError`; disables chat send and screen share toggle when expired; `canToggleBrse` respects `isRoomExpired`
- `FE/src/index.css` — added `.room-timer-chip`, `.room-timer-chip-expired`, `.create-room-policy-note`, `.expiry-label`, `.expiry-label-expired`, `.room-expired-state`, `.room-expired-icon`, `.room-expired-page`, `.banner-room-expired`

### TypeScript

- 0 new errors introduced
- 3 pre-existing errors in `FE/src/lib/livekit.ts` (`track.name`) remain unchanged — deferred per prior sessions

### Testing

- Deferred per instruction (CODE-ONLY mode).

---

## Turn Update: 2026-05-01 Transcript/Relay Panel UX Fix (Completed)

- Time: 2026-05-01T20:19:00+07:00
- Mode: CODE-ONLY
- Testing deferred: yes

### Problem

Relay/transcript panel appended entries without limit, causing:
- Panel grew infinitely tall, pushing room layout out of control
- Side panel `.transcript-list` had `max-height: none; overflow: visible` — no scroll containment
- No pruning in state or render layer — all entries rendered regardless of count
- Auto-scroll was simplistic — always forced scroll on any entry change

### Strategy

**State-layer pruning** (chosen over render-only limit because it also reduces memory):
- `MAX_TRANSCRIPT_ENTRIES = 30` — keeps ~2-3 min of active conversation context
- Pruning preserves all active **partial** entries (in-progress utterances) and trims oldest **final** entries first
- Applied inside `mergeTranscriptCollections()` so every state update is bounded

**Render-layer safety net**:
- `MAX_VISIBLE_ENTRIES = 25` in `TranscriptPanel` — ensures DOM never exceeds this many items even if state has more
- Slices from the end (`entries.slice(-25)`) so the most recent are always shown

**Smart auto-scroll**:
- Tracks `isNearBottom` via `onScroll` handler with 120px threshold
- Only auto-scrolls when user is already near the bottom
- Does NOT force-scroll when user is reviewing older entries

**CSS scroll containment restored**:
- `.room-side-content .transcript-list`: `max-height: min(55vh, 440px); overflow-y: auto` — bounded and scrollable
- `.transcript-list` base: `max-height: 480px; scroll-behavior: smooth`

**Compact layout**:
- Transcript items tightened: gap 12→8px (base), 6px (side panel)
- `.transcript-relay` padding reduced: 12px 14px → 8px 12px
- Side panel transcript text: font-size 0.88rem, line-height 1.45
- Side panel badges: font-size 0.72rem, padding 4px 8px
- Side panel header text sized down for density

### Changes Made

- `FE/src/features/room/transcripts.ts`:
  - Added `MAX_TRANSCRIPT_ENTRIES = 30` constant
  - Added `pruneTranscriptCollection()` function
  - `mergeTranscriptCollections()` now calls `pruneTranscriptCollection()` after merge
- `FE/src/components/TranscriptPanel.tsx`:
  - Added `MAX_VISIBLE_ENTRIES = 25` render limit
  - Smart auto-scroll: `isNearBottomRef` + `onScroll` handler with `AUTO_SCROLL_THRESHOLD = 120`
  - Visible entry count badge in panel header
  - `useMemo` for `visibleEntries` to avoid unnecessary re-renders
- `FE/src/index.css`:
  - `.transcript-panel`: `min-height: 420px → 280px`
  - `.transcript-list`: `max-height: 520px → 480px`, added `scroll-behavior: smooth`
  - `.transcript-item`: gap `12px → 8px`
  - `.transcript-relay`: padding `12px 14px → 8px 12px`, font-size `0.92rem`
  - `.room-side-content .transcript-list`: `max-height: min(55vh, 440px); overflow-y: auto` (was `none`/`visible`)
  - `.room-side-content .transcript-item`: padding `13px → 10px 12px`, gap `6px`
  - Added compact overrides for `.room-side-content` transcript text, headers, badges

### Partial/Final Merge Behavior

No changes needed. The existing `choosePreferredTranscript()` in `transcripts.ts` already:
- Keeps final over partial when both exist for same `transcript_id`
- Updates in-place via Map keyed by `transcriptId`
- Does NOT create duplicate rows for the same utterance

The issue was NOT merge behavior — it was the absence of pruning and scroll containment.

### Files Modified

- `FE/src/features/room/transcripts.ts`
- `FE/src/components/TranscriptPanel.tsx`
- `FE/src/index.css`
- `docs/frontend/IMPLEMENTATION_STATE.md`

### Testing Status

- Testing deferred by instruction: no tests run, no test files modified.
- TypeScript: `tsc --noEmit` passes with 0 errors.

## Turn Update: 2026-05-01 Full Product UI Redesign + Camera Toggle (Kickoff)

- Time: 2026-05-01T19:37:46+07:00
- Mode: CODE-ONLY
- Testing deferred: yes; no tests, build, or runtime verification will be run this turn

### Objective Locked

- Redesign the three main FE screens:
  - Landing / create room
  - Join room
  - Meeting room
- Tighten the room information architecture so the main panel focuses on `Relay`, `Chat`, and `People`.
- Move `Settings` out of the main tab set into a secondary drawer/popover launched from a gear-style control.
- Add a clear camera on/off control and FE runtime path while preserving existing mic, BRSE, screen share, chat, transcript, people, and host mute flows.

### Mandatory Read Status

- Read required docs and state:
  - `docs/frontend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
- Read FE pages:
  - `FE/src/pages/HomePage.tsx`
  - `FE/src/pages/RoomPage.tsx`
  - `FE/src/pages/TestPage.tsx`
- Read FE room components:
  - `FE/src/components/JoinRoomCard.tsx`
  - `FE/src/components/RoomTopBar.tsx`
  - `FE/src/components/RoomControlBar.tsx`
  - `FE/src/components/RoomSidePanel.tsx`
  - `FE/src/components/MeetingStage.tsx`
  - `FE/src/components/ParticipantTile.tsx`
  - `FE/src/components/BrseRelayPanel.tsx`
  - `FE/src/components/TranscriptPanel.tsx`
  - `FE/src/components/ChatPanel.tsx`
  - `FE/src/components/ParticipantList.tsx`
  - `FE/src/components/AudioDevicePanel.tsx`
  - existing support components in `FE/src/components/`
- Read FE runtime/types/style:
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/lib/api.ts`
  - `FE/src/lib/ws.ts`
  - `FE/src/lib/livekit.ts`
  - `FE/src/types/api.ts`
  - `FE/src/types/ws.ts`
  - `FE/src/types/livekit.ts`
  - `FE/src/index.css`

### Planned Product IA

- Landing:
  - compact product shell with clear create-room and join-existing actions in one cohesive layout
  - language pair selectors upgraded from generic form fields into first-class selectable controls
  - test utilities demoted to a quiet secondary action
- Join:
  - focused join panel with compact room metadata, clear meeting pair, name input, language selection, and subdued participant preview
  - BRSE AI/virtual participants should not dominate the pre-join experience
- Meeting:
  - top bar remains compact for identity/language/connection/BRSE mode
  - control bar becomes meeting-app-style controls: mic, camera, share, relay/chat/people shortcuts, settings gear, leave
  - side panel main tabs become `Relay`, `Chat`, `People` only
  - audio settings move to secondary settings drawer
  - BRSE state remains visible but does not occupy oversized stage space unless useful

### Camera Toggle Plan

- Add LiveKit helper support for local camera lookup and muted/unmuted toggling.
- Add hook state:
  - `isCameraOff`
  - `isTogglingCamera`
  - `cameraToggleError`
  - `toggleCameraEnabled()`
- Keep local video tile fallback productized when camera is off.

## Turn Update: 2026-05-01 Full Product UI Redesign + Camera Toggle (Final Sync)

- Time: 2026-05-01T19:47:14+07:00
- Mode: CODE-ONLY
- Testing deferred: yes; no tests, build, typecheck, or browser/runtime verification were run by explicit instruction

### Layout Strategy Implemented

- Landing / create room:
  - Reworked `FE/src/pages/HomePage.tsx` into a compact product shell.
  - Primary hierarchy is now product purpose → create room → join existing room → test utility.
  - `Mic & Translation Test` is demoted to a quiet header utility link.
  - Create flow now uses first-class language-pair selector cards with full language names and a clear meeting bridge preview.
  - Join-existing is a secondary row in the same launch surface, not a competing hero block.
- Join room:
  - Reworked `FE/src/components/JoinRoomCard.tsx` into a focused pre-join composition.
  - Room id, meeting languages, participant count, room state, and BRSE/normal mode are summarized before the form.
  - Name and language selection are grouped as the user's setup.
  - Human participants are previewed compactly; virtual BRSE AI no longer takes visual spotlight in the pre-join state.
- Meeting room:
  - Kept `FE/src/pages/RoomPage.tsx` as the orchestration layer while moving presentation into room components.
  - `RoomTopBar` stays compact for room identity, language, connection state, and BRSE toggle.
  - `MeetingStage` remains the primary canvas for screen share/video.
  - `RoomControlBar` now owns meeting actions: mic, camera, screen share, Relay/Chat/People shortcuts, Settings, and Leave.

### Panel Architecture

- Main side panel now has only:
  - `Relay`
  - `Chat`
  - `People`
- `Settings` was removed from the primary tab set in `FE/src/components/RoomSidePanel.tsx`.
- Audio/device settings moved into new `FE/src/components/SettingsDrawer.tsx`.
- `RoomPage` opens the settings drawer from the control bar and embeds `AudioDevicePanel` there.
- This keeps the main meeting surface focused on active meeting work instead of secondary device configuration.

### Camera Toggle Runtime Path

- `FE/src/types/livekit.ts`
  - Added `VideoFeed.isCameraOff`.
- `FE/src/lib/livekit.ts`
  - Added `getLocalCameraTrack`.
  - Added `isCameraMuted`.
  - Added `setLocalCameraMuted`.
  - Added `publishLocalCameraTrack` so the camera button can publish a camera track if one is missing.
  - `buildMediaSnapshot` now marks local and remote video feeds as camera-off when no video track exists or the track is muted.
- `FE/src/features/room/useMeetingRoom.ts`
  - Added `isCameraOff`, `isTogglingCamera`, `cameraToggleError`.
  - Added `toggleCameraEnabled()`.
  - Camera state refreshes from LiveKit publications alongside mic/media snapshot refresh.
  - Toggle behavior now mutes/unmutes an existing camera track or publishes a new local camera track when needed.
- `FE/src/components/RoomControlBar.tsx`
  - Added visible camera on/off control in the primary meeting controls.
- `FE/src/components/ParticipantTile.tsx`
  - Local camera-off state renders a deliberate fallback instead of an awkward blank tile.

### Component / Style Changes

- New component:
  - `FE/src/components/SettingsDrawer.tsx`
- Refactored components:
  - `FE/src/pages/HomePage.tsx`
  - `FE/src/components/JoinRoomCard.tsx`
  - `FE/src/pages/RoomPage.tsx`
  - `FE/src/components/RoomTopBar.tsx`
  - `FE/src/components/RoomControlBar.tsx`
  - `FE/src/components/RoomSidePanel.tsx`
  - `FE/src/components/ParticipantTile.tsx`
- Style updates:
  - `FE/src/index.css` now includes the product redesign pass for landing, join, meeting controls, camera fallback, side-panel tab count, and settings drawer.

### Deferred Verification

- Not run by instruction:
  - tests
  - test edits
  - build
  - typecheck
  - browser/dev-server/runtime verification

## Turn Update: 2026-05-01 Room Meeting UI Redesign + BRSE Toggle (Kickoff)

- Time: 2026-05-01T19:14:45+07:00
- Mode: CODE-ONLY
- Testing deferred: yes; no tests will be run, written, or edited this turn

### Objective Locked

- Redesign the room meeting page around a meeting-first hierarchy instead of stacked dashboard cards.
- Keep existing join/session, gateway websocket, LiveKit media, mic/cam, screen share, transcript, BRSE relay, chat, participant, host mute, and audio settings runtime paths.
- Add explicit in-room BRSE mode control wired to the backend `brse_enabled` contract.

### Mandatory Read Status

- Read required state/contract/runtime files:
  - `docs/frontend/IMPLEMENTATION_STATE.md`
  - `docs/backend/API_CONTRACT.md`
  - `docs/backend/IMPLEMENTATION_STATE.md`
  - `FE/src/pages/RoomPage.tsx`
  - `FE/src/features/room/useMeetingRoom.ts`
  - `FE/src/lib/api.ts`
  - `FE/src/lib/ws.ts`
  - `FE/src/types/api.ts`
  - `FE/src/types/ws.ts`
  - `FE/src/index.css`
- Read room-rendering components in `FE/src/components/`:
  - `AudioDevicePanel.tsx`
  - `ChatPanel.tsx`
  - `ConnectionBadge.tsx`
  - `InterpreterStatusPanel.tsx`
  - `JoinRoomCard.tsx`
  - `MediaElements.tsx`
  - `MicLevelMeter.tsx`
  - `ParticipantList.tsx`
  - `ParticipantTile.tsx`
  - `TranscriptPanel.tsx`

### Planned Layout Strategy

- Replace the oversized header + card stack with:
  - compact top bar for room identity, language pair, connection, user language, BRSE toggle, and leave action
  - dominant meeting stage for active screen share first, otherwise video grid
  - bottom meeting control bar for mic and screen share
  - tabbed side panel for relay/transcript, chat, participants, and settings
- Move audio device settings out of the main canvas into the side panel settings tab.
- Treat BRSE as mode state:
  - ON: show productized relay activity/status and relay transcript surface
  - OFF: show normal meeting state, hide/de-emphasize relay activity, keep transcript/chat usable where available

### BRSE Toggle Contract Plan

- Add `brse_enabled` to FE room summary/snapshot/join types.
- Add REST methods for `POST /api/rooms/{room_id}/brse/enable|disable`.
- Add WS client methods/types for `room.brse.enable|room.brse.disable` and server event type `room.brse_updated`.
- In `useMeetingRoom`, expose `brseEnabled`, `isTogglingBrse`, `brseToggleError`, `canToggleBrse`, and `toggleBrseMode`.
- Prefer REST toggle confirmation and also handle `room.brse_updated` / `room.snapshot` as source of truth.

### Batch 1: Runtime Contract + IA Refactor (Completed)

- Time: 2026-05-01T19:27:17+07:00
- Added FE contract support:
  - `FE/src/types/api.ts` now exposes optional `brse_enabled` on `RoomSummary` and create-room payload compatibility.
  - `FE/src/types/ws.ts` now types `room.brse.enable`, `room.brse.disable`, and `room.brse_updated`.
  - `FE/src/lib/api.ts` now has REST `enableBrse()` / `disableBrse()` methods.
  - `FE/src/lib/ws.ts` now has WS `enableBrse()` / `disableBrse()` helpers for the documented gateway contract.
- Updated `FE/src/features/room/useMeetingRoom.ts`:
  - hydrates `brse_enabled` from join, REST snapshot, and WS snapshot
  - handles `room.brse_updated`
  - exposes `brseEnabled`, `canToggleBrse`, `isTogglingBrse`, `brseToggleError`, and `toggleBrseMode`
  - hides stale BRSE relay audio/video/status/transcript surfaces when BRSE is off
  - ignores relay transcript/status events while BRSE is off
- Replaced room page information architecture:
  - compact `RoomTopBar` for room identity, language pair, current language, connection state, BRSE toggle, and leave action
  - `MeetingStage` for screen-share-first stage and video grid/strip
  - `RoomControlBar` for mic and screen-share meeting controls plus quick panel switching
  - `RoomSidePanel` tabs for relay/transcript, chat, participants, and settings
  - `BrseRelayPanel` for BRSE on/off state and relay activity summary
- Existing feature surfaces were preserved and embedded into the new IA:
  - `ChatPanel` embedded under Chat
  - `TranscriptPanel` embedded under Relay
  - `ParticipantList` embedded under People with host mute controls
  - `AudioDevicePanel` moved under Settings
- Visual direction updated in `FE/src/index.css`:
  - dark meeting canvas for primary stage
  - compact glass top bar/control bar
  - light tabbed side panel for secondary workflows
  - productized BRSE relay tile/status treatment
  - responsive collapse to single-column room layout
- Testing remains deferred by instruction.

### Final Sync: Room Meeting UI Redesign + BRSE Toggle

- Time: 2026-05-01T19:29:08+07:00
- Final status: FE room page has been redesigned and BRSE toggle wiring has been added without backend changes.

### Final Layout Strategy

- The room page now prioritizes the meeting experience:
  - `RoomTopBar`: compact room identity, language pair, current language selector, participant count, connection state, BRSE toggle, leave action
  - `MeetingStage`: primary stage for active screen share; falls back to video grid when no one is sharing
  - `RoomControlBar`: primary meeting controls for microphone and screen sharing, plus quick access to side-panel tabs
  - `RoomSidePanel`: tabbed secondary workspace for `Relay`, `Chat`, `People`, and `Settings`
- The old right-column stack of separate cards is removed from the room page render path.
- Audio settings moved out of the main canvas into the `Settings` tab.
- Participants and host mute controls moved into the `People` tab.
- Chat now occupies a full side-panel tab with scrollable message history and a stable input bar.
- Transcript and BRSE relay state live together in the `Relay` tab.

### BRSE Toggle Behavior

- Toggle placement: `RoomTopBar`, next to connection state and before Leave.
- Visible states:
  - `BRSE On`: AI relay active/available
  - `BRSE Off`: normal meeting mode
  - `Updating`: pending backend confirmation
- Runtime behavior:
  - REST `enableBrse()` / `disableBrse()` is used for toggle confirmation.
  - WS `room.brse_updated` is handled as a live source of truth.
  - WS `room.snapshot` continues to hydrate `brse_enabled`.
  - When BRSE turns off, FE hides stale BRSE virtual participant video, BRSE audio sinks, interpreter statuses, and relay transcript rows.
  - When BRSE is off, the relay tab degrades to normal meeting/transcript state instead of showing a dead BRSE panel.

### Components Added

- `FE/src/components/BrseToggleControl.tsx`
- `FE/src/components/RoomTopBar.tsx`
- `FE/src/components/MeetingStage.tsx`
- `FE/src/components/RoomControlBar.tsx`
- `FE/src/components/RoomSidePanel.tsx`
- `FE/src/components/BrseRelayPanel.tsx`

### Components Refactored

- `FE/src/pages/RoomPage.tsx`
- `FE/src/features/room/useMeetingRoom.ts`
- `FE/src/components/ChatPanel.tsx`
- `FE/src/components/TranscriptPanel.tsx`
- `FE/src/components/ParticipantList.tsx`
- `FE/src/components/ParticipantTile.tsx`
- `FE/src/components/AudioDevicePanel.tsx`
- `FE/src/index.css`
- `FE/src/lib/api.ts`
- `FE/src/lib/ws.ts`
- `FE/src/types/api.ts`
- `FE/src/types/ws.ts`

### Testing Status

- Testing deferred by instruction:
  - no tests run
  - no tests written
  - no tests edited
  - no build/runtime verification run

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
