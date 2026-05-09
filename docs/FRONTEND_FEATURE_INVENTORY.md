# Frontend Feature Inventory

> **Source:** Derived exclusively from FE code read on 2026-05-09.
> **Scope:** `FE/src/` — pages, components, features, lib, state, types.
> **Mode:** Read-only analysis. No features added, no code changed.

---

## Quick-scan Summary

| Feature Area | Status | Notes |
|---|---|---|
| Landing page / intro slideshow | Complete | 4 animated slides, branded |
| Create room | Complete | Language pair + BRSE mode selection |
| Join room | Complete | Name + language, remembers prefs |
| Room pre-join card | Complete | Shows participants preview, expiry, mode badge |
| In-meeting stage (video grid) | Complete | Grid layout, screen-share layout, filmstrip |
| Screen sharing | Complete | Start/stop, dynamic layout switch |
| Mic / camera controls | Complete | Toggle, host-mute enforcement |
| BRSE relay panel (text) | Complete | Scrolling transcript list, source + relay lines |
| Chat panel | Complete | Send/receive, optional translation toggle |
| Meeting summary panel | Complete | Interim + final, action items, participants |
| People panel | Complete | Participant list, host badge, host-mute action |
| Audio device selection | Complete | Input + output device pickers in settings drawer |
| BRSE modes (Voice+Text / Text Only / Off) | Complete | Create-time selection, top-bar label |
| BRSE enable/disable toggle | Complete | In-room toggle in top bar |
| Language switch (in-room) | Complete | Per-participant language selector in top bar |
| Room expiry countdown | Complete | Live countdown in top bar, expired state |
| Theme (light / dark) | Complete | OS-driven, manual override in settings |
| Layout modes | Complete | Stage-focus / Balanced / Compact |
| Stage focus mode | Complete | Hides side panel, enlarges stage |
| Settings drawer | Complete | Slide-over overlay, view + audio panels |
| Connection badge | Complete | Idle / Connecting / Connected / Reconnecting / Disconnected |
| Mic & translation test page | Complete | Dev tool at `/test` |
| Persistent user prefs | Complete | Name, language, BRSE mode, layout — localStorage |
| Post-meeting ended summary page | Complete | Shown after room expires or user leaves last |
| Interpreter status display | Complete | Component present, not surfaced in main side panel tabs |
| TranscriptPanel component | Complete | Separate from BrseRelayPanel; not wired into current side panel tabs |
| Host moderation (mute participant) | Complete | Host sees mute button per non-virtual participant |

---

## 1. Overview

**meetQ** is a web-based multilingual meeting platform. Its main value proposition is AI-powered real-time relay: participants speak in their own language and the BRSE (Bilingual Real-time Speech Engine) relay translates and optionally speaks the result to participants on the other language side. Rooms are ephemeral (60-minute default) and require no account.

**Routes:**
- `/` — landing + create/join
- `/rooms/:roomId` — pre-join card → in-meeting room
- `/test` — developer mic & translation test tool

---

## 2. Core User Flows

### 2.1 Create Room
Location: `HomePage` right panel → "Create room" card

- User selects **Language A** and **Language B** from a dropdown (7 supported languages: VI, EN, JA, ZH, KO, FR, ES).
- User selects **BRSE output mode**: Voice + Text, Text Only, or Off.
- Validation: both languages required, must be different.
- On success: navigates to `/rooms/:roomId`.
- BRSE mode preference is persisted to localStorage (`meetq:create-brse-mode`) so the next room creation pre-fills the last choice.
- Displays inline error on API failure with mapped human-readable messages.

### 2.2 Join Room
Location: `HomePage` right panel → "Already have a room?" card

- User pastes a room ID (e.g. `rm_…`) or a full room link.
- `extractRoomId` strips the link to the bare ID.
- Navigation goes to `/rooms/:roomId`; the pre-join card handles the rest.

### 2.3 Pre-join (Room Entry)
Location: `RoomPage` → `JoinRoomCard`

Rendered before the participant has joined. Shows:
- Room ID badge.
- Language bridge (e.g. "Vietnamese <-> English").
- BRSE mode badge ("BRSE Voice", "BRSE Text Only", "BRSE Off").
- Room expiry time / countdown.
- Join form: display name input (max 40 chars) + language dropdown (restricted to the room's language pair).
- Already-joined participants preview (up to 5 humans + virtual BRSE participant with mode-aware label).
- Name and language are saved to localStorage on join.
- Expired room: shows "Meeting ended" state instead of join form.

### 2.4 In-Meeting Room
Location: `RoomPage` (post-join)

Full meeting UI with:
- Top bar with identity, meta, BRSE toggle, language selector, connection badge, countdown.
- Alert stack for: room expired, connection errors, media errors, screen share errors, mic toggle errors, camera toggle errors, host-mute notifications, moderation errors.
- Meeting stage (video grid or screen-share layout).
- Control bar (bottom).
- Side panel with tabs: Relay, Chat, Summary, People.
- Settings drawer (slide-over).
- Hidden audio sinks for remote participants and BRSE AI audio.

### 2.5 Post-Meeting
Location: `RoomPage` expired state / leave flow

- If the user leaving is the last human participant → room ended page shows after leaving, attempts to fetch final summary.
- If room expired with no active session → dedicated expired page with final summary panel.
- Both surfaces use `MeetingSummaryPanel` in `roomEnded=true` mode.

---

## 3. Meeting Stage

Component: `MeetingStage` → `ParticipantGrid` / `SharedScreenStage` + `ParticipantFilmstrip`

### Participant Grid
- Responsive CSS grid (`.is-few` variant for ≤ 2 tiles).
- Empty state when no video feeds.
- Each tile: `ParticipantTile`.

### Screen-share Layout
- When any participant is sharing: full-surface screen view (`StageMediaSurface`, 16:9 aspect maintained via `ResizeObserver`) + horizontal filmstrip of all participant tiles.
- Sharer name label shown above stage.
- Connecting placeholder shown while stream is coming in.

### Participant Tile (`ParticipantTile`)
- Camera on: renders live `VideoTrackView`.
- Camera off (human): avatar with initials.
- BRSE virtual participant: cat avatar image (`/cat.jpg`), relay status label, mode-aware caption (AI voice + text relay / Text relay only / Summary capture / Normal meeting).
- Badges: Host, BRSE mode badge, Sharing screen, Muted by host.
- Language pill.
- Speaking indicator ring (`.is-speaking`).

---

## 4. In-Meeting Controls

### Control Bar (`RoomControlBar`)
Bottom bar, always visible:
- **Mic toggle**: mute/unmute. Disabled when host-muted and muted.
- **Camera toggle**: start/stop video.
- **Screen share**: start/stop. Disabled when room expired.
- **Panel tabs**: Relay / Chat / Summary / People — opens/switches side panel.
- **Focus**: "Focus" / "Exit" — activates stage focus mode.
- **Panel toggle** (⇥/⇤): show/hide side panel.
- **Settings** (⚙): opens settings drawer.
- **Leave**: leaves room. If last human → triggers final summary flow.

### Top Bar (`RoomTopBar`)
- Brand mark "MQ".
- Display name + room ID + language bridge + participant count + expiry countdown.
- Language selector: switch your own meeting language (limited to room's language pair).
- Connection badge.
- BRSE toggle control (compact pill, shows mode label + description).

---

## 5. BRSE / AI Features

### BRSE Modes
Defined in `lib/brseModes.ts`. Four resolved states:

| Mode | Meaning |
|---|---|
| `off` | No relay, no AI; normal meeting |
| `voice_text` | BRSE relay text + BRSE AI audio output |
| `text_only` | BRSE relay text, no AI audio |
| `silent_summary` | BRSE listens for summary context, no public relay |

### BRSE Mode Selection (Create Time)
Three user-facing options at room creation:
- **Voice + Text**: text relay + AI voice.
- **Text Only**: text relay, no AI voice.
- **Off**: no BRSE.

Sends `brse_enabled`, `brse_mode`, `brse_output_mode` to backend. The create-time choice is the only point where output mode is selected — no live mode-switching contract exists.

### BRSE Toggle (In-Room)
Top bar toggle pill: enable or disable BRSE for the current room (enable/disable only, no live output-mode switch). Shows current mode label. Disabled when room is expired.

### BRSE Relay Panel (`BrseRelayPanel`)
Side panel Relay tab:
- Scrolling list of up to 25 most recent transcript entries.
- Auto-scrolls when near bottom; stops auto-scroll when user scrolls up.
- Each entry shows: speaker name, language, direction label (e.g. "Vietnamese -> English"), source text, relay/translated text.
- Mode-aware empty state:
  - Off → "Relay is off"
  - Text-only → "Waiting for speech · AI voice is off"
  - Silent summary → "Summary capture"
  - Voice+Text → "Waiting for speech · Text and AI voice relay will appear here"

### BRSE Audio Sinks
Hidden `<AudioTrackSink>` elements in `RoomPage` render audio from:
- All human participants' audio tracks.
- BRSE AI audio feeds — only when `brseAudioExpected` is true (i.e. not text-only, not off, not silent summary).

### Interpreter Status (`InterpreterStatusPanel`)
Component exists and shows per-relay-pair status (speaker name, source/target language, status badge, fallback-used warning). **Not wired into the main side panel tabs** in the current layout — it is a standalone component but not rendered in `RoomSidePanel`.

---

## 6. Chat Panel

Component: `ChatPanel`, side panel tab "Chat"

- Real-time message list from WS events.
- Auto-scrolls to latest message.
- Compose bar: text input (max 2000 chars) + Send button.
- **Translation mode toggle**: "Original" (no translation) or "+ Translate" (requests backend to translate the message). Preference saved to localStorage.
- Messages show: sender name, language pill, timestamp, delivery status badge (Sending / Failed).
- Translated messages show each translation in a block below the original.
- "Translating…" pending state shown while backend processes.
- Disabled when room expired or user has no send permission.
- Depends on backend for translation delivery.

---

## 7. Meeting Summary Panel

Component: `MeetingSummaryPanel`, side panel tab "Summary"

**In-meeting (interim summary):**
- "Generate summary" / "Refresh summary" button — triggers backend generation.
- "Check latest" button — fetches current backend state.
- Shows: pending / generating / skipped / failed / completed states.
- Completed summary shows: summary text, key points / highlights, decisions, action items (with owner and due fields), participant summaries, source stats (message count, transcript count, relay count, chat count, truncated flag).

**Post-meeting (final summary):**
- Shown in side panel when room is expired (active session) or on the standalone ended page.
- "Prepare final" / "Retry final" button — triggers backend final generation.
- "Check latest" polls backend for prepared final.
- Polls automatically up to 8 times with 3-second interval when room expires.
- Shows generated timestamp and summary language.

**Backend dependency:** FE has full UI; content depends on backend summary generation endpoint and BRSE having collected sufficient transcript/chat data.

---

## 8. People Panel

Component: `ParticipantList`, side panel tab "People"

- Lists all participants (human + virtual BRSE).
- Each row: display name, status (or "BRSE text relay participant" / "AI relay participant" etc. depending on mode), badges (Host, BRSE mode badge, Sharing screen, Muted, language pill).
- **Host controls**: host sees a "Mute" button on non-virtual, non-self participants. Button disabled while muting is in-flight.
- "You" suffix on self.
- Panel description copy is mode-aware (reflects whether BRSE is voice+text, text-only, summary, or off).

---

## 9. Audio / Device Features

### Audio Device Panel (`AudioDevicePanel`)
Inside Settings drawer:
- **Mic toggle** (mute/unmute), respects host-mute state.
- **Input device picker**: lists available microphone devices via `enumerateAudioDevices`. Switches via `switchLocalMicrophoneTrack`.
- **Output device picker**: lists available speaker/headphone output devices. Disabled if browser does not support `setSinkId`. Switches output for all audio elements.
- Inline error display for input/output switch failures.

### Audio Output Routing
- Human participant audio tracks: always routed to sinks.
- BRSE AI audio tracks: only routed when `brseAudioExpected` is true.
- All sinks respect the selected output device.

---

## 10. Layout / Theme / UI Customization

### Theme
- **Light / Dark**: driven by OS `prefers-color-scheme`. Applied via `data-theme` on `<html>`. Manual override available in the View settings panel.
- No manual theme preference is persisted (always re-derives from OS on load); the manual toggle is session-only.

### Layout Modes (3 options)
Controlled via Settings → View panel, persisted to localStorage:
- **Stage focus**: more space for video and shared screen.
- **Balanced** (default): stage and panels evenly weighted.
- **Compact panel**: tighter panel width.

Applied as CSS class on `<main class="room-page layout-{mode}">`.

### Stage Focus Mode
- Triggered via "Focus" button in control bar or in View panel.
- Hides side panel, maximizes stage area.
- Exits automatically when side panel is opened.

### Side Panel
- Open/closed state persisted per session (not across page loads).
- Close button (✕) in panel header.
- Width controlled by layout mode.

### Settings Drawer
- Slide-over modal with backdrop dismiss.
- Contains: View panel (theme + layout + stage focus) + Audio Device panel.

---

## 11. Responsive / Mobile Behavior

- CSS in `FE/src/index.css` includes mobile fallback rules for BRSE mode selector and compact states.
- No dedicated mobile-only routes or layouts in JS logic.
- `hp-panel` on home page is positioned as a floating overlay over the full-bleed intro slideshow.
- Room layout modes provide some density control but are not automatically applied for small viewports.

**Note:** Full mobile layout testing not done in this analysis; responsive behavior is partially CSS-driven and not fully validated.

---

## 12. Persistence / Local Preferences

All stored in `localStorage`:

| Key | What | Where |
|---|---|---|
| `meetq:create-brse-mode` | Last BRSE mode selected at room creation | `HomePage` |
| `brse_display_name` | Display name used at last join | `userPrefs.ts` → `JoinRoomCard` |
| `brse_preferred_language` | Language selected at last join | `userPrefs.ts` → `JoinRoomCard` |
| `brseai_room_layout_mode` | Layout mode (stage-focus/balanced/compact) | `uiPreferences.ts` → `RoomPage` |
| `brseai_chat_translation_mode` | Chat translation preference (original_only/translate) | `ChatPanel` |

Theme is not persisted — always re-derived from OS.

Session (room token, participant data, WS URL) is held in React state (`SessionProvider`) and is lost on page reload.

---

## 13. Developer / Test Page

Route: `/test`

### Mic Test
- Requests mic permission, connects to a backend test session.
- Shows real-time audio level meter (20-bar RMS + peak + dB label).
- Status states: idle / requesting_permission / connecting / active / silence / stopped / error.

### Translation Test
- Select source and target language (from supported meeting languages).
- Starts a translation session with the backend.
- Shows partial and final transcript lines side by side (source + translated).
- Plays translated audio if backend returns an audio URL.
- Status states: idle / connecting / listening / translating / stopped / error.

**Dependency:** Both test flows require backend endpoints to be running.

---

## 14. Known Partial / In-Progress Features

### `InterpreterStatusPanel`
- Component fully implemented: shows relay pair status, speaker name, source/target language, fallback badge.
- **Not wired into the main room side panel tabs** in `RoomPage`. It exists as a standalone component but has no route or tab that renders it in the active UI.

### `TranscriptPanel`
- Separate component from `BrseRelayPanel` — more detailed view with source/relay pair in each row, partial/final badges, "BRSE Relay", "Translated", "Human Source" kind labels.
- **Not used in the active side panel.** `BrseRelayPanel` is used for the Relay tab instead. `TranscriptPanel` appears to be a predecessor or alternative view.

### Silent Summary Mode
- `silent_summary` is a recognized `BrseRoomMode` in FE with correct labels and copy in all components (tile, people panel, relay panel, join card, top bar).
- **Cannot be selected at create time** — `BRSE_CREATE_MODE_OPTIONS` only exposes `voice_text`, `text_only`, `off`. Silent summary would need to come from the backend room state.

### Screen Share — Multi-sharer
- FE tracks `activeScreenShareParticipants` and picks `selectedScreenSharer` (prefers self, then first).
- When multiple participants share simultaneously, only one feed is shown in the stage. The filmstrip shows all participant tiles regardless.

---

## 15. Open FE Gaps / Notes

- **No account / auth system**: no login, no user profile. Each join is ephemeral with a name + language.
- **Theme manual override is session-only**: closing and reopening the tab re-applies OS theme. localStorage key exists in code but `saveThemePreference` is a no-op.
- **BRSE mode cannot be switched live**: mode is set at room creation. In-room toggle only enables/disables, does not switch between voice+text and text-only.
- **Interpreter status not surfaced**: `InterpreterStatusPanel` component exists but is not accessible via any UI path in the current room layout.
- **`TranscriptPanel` is dormant**: implemented but unused in current room layout; `BrseRelayPanel` serves the Relay tab instead.
- **Summary depends entirely on backend**: FE has complete summary UI but all content comes from backend endpoint. If the backend has not generated a summary, the panel shows empty/pending states.
- **No offline / reconnect UX beyond banner**: connection state is surfaced via `ConnectionBadge` and a danger banner on `connectionError`, but there is no automatic retry UI or user-visible reconnect action.
