# Room roles, My meetings and meeting search

Technical reference for host / co-host roles, meeting history and keyword search
(added 2026-10-05). Product rules: `docs/system-design/03-product-features-and-workflows.md`
R-70…R-93 and S7.

## 1. Identity

- A signed-in user has a stable ID `usr_<sha256(google sub)[:20]>` (`server/service/auth/api.py`).
  Display names are never an identity.
- A realtime **participant** (`pt_…`) is one join of one user: every join or reconnect
  creates a new participant ID. Roles, removals and history belong to the **user**.
- The room token carries only the participant ID. The server maps it to the user
  (`room:{id}:pusers`), then to the user's membership. No request ever supplies a role.
- Management endpoints also check that the room token belongs to the signed-in account.

## 2. Roles and permissions

`server/service/gateway/room_permissions.py` is the only mapping from role to rights:

| Permission | host | co_host | participant |
| --- | --- | --- | --- |
| `can_manage_ai` (on/off, Voice + Text ↔ Text Only) | ✓ | ✓ | |
| `can_manage_recording` | ✓ | ✓ | |
| `can_mute_participant` | ✓ | ✓ | |
| `can_remove_participant` | ✓ | ✓ | |
| `can_manage_room_security`, `can_lock_room`, `can_manage_password`, `can_assign_cohost`, `can_extend_room` | ✓ | | |

Targeted actions (mute, remove, role change) also need `outranks(actor, target)`: nobody acts
on the host, co-hosts act on participants only, nobody targets themselves.

Every check goes through `RoomService.require_room_permission()` (or the AI wrapper
`_require_ai_permission`) and fails with `403 {"error": {"code": "permission_denied",
"message": "You don't have permission to perform this action."}}`.

Roles are enforced when sign-in is required **and** the room was created by a signed-in user
(`RoomState.roles_enabled`). Without sign-in (`USER_AUTH_REQUIRED=false`, tests only) roles
cannot exist: AI relay and recording stay open to everyone (legacy behaviour) and identity
actions are refused.

## 3. Data model

### Redis (live room, same TTL as the room)

| Key | Content |
| --- | --- |
| `room:{id}:meta` | `RoomState` + `title`, `locked` |
| `room:{id}:participants` | `ParticipantState` + `role`, `muted_by_host` |
| `room:{id}:members` | hash `user_id → {role, joined_at, removed_at, removed_by_user_id}` (authoritative live roles; the creator is written as `host` at creation) |
| `room:{id}:pusers` | hash `participant_id → user_id` |

### MongoDB (history)

| Collection | New fields / documents | Indexes |
| --- | --- | --- |
| `rooms` | `title`, `locked`, `created_by_user_id`, `member_user_ids[]` (creator + joined users, removed users pulled), `joined_user_ids[]`, `history_sort_at_dt` (end time; start time while live), `has_recording`, `archive_expires_at_dt`, `archive_status` | `rooms_by_member_recent (member_user_ids, history_sort_at_dt -1, room_id)`, `rooms_by_creator_recent (created_by_user_id, history_sort_at_dt -1, room_id)` |
| `room_memberships` (new) | one per `(room_id, user_id)`: `role`, `is_creator`, `display_name`, `language`, `first_joined_at`, `last_joined_at`, `left_at`, `removed_at`, `removed_by_user_id` | `uniq_room_membership (room_id, user_id)`, `memberships_by_user (user_id, room_id)` |
| `room_messages` | unchanged | added `room_messages_by_kind_cursor (room_id, kind, created_at, message_id)`, `room_messages_by_utterance (room_id, utterance_id)` |

MongoDB has no migrations framework in this project: indexes are created idempotently by
`ensure_indexes()` at gateway startup, which also runs the one-time backfill below.

`explain()` on MongoDB 7 with 3,000 rooms / 60,000 messages:

| Query | Plan | Keys / docs read |
| --- | --- | --- |
| My meetings page | `LIMIT ← FETCH ← IXSCAN(rooms_by_member_recent)` | 20 / 20 |
| Created by me | `LIMIT ← FETCH ← IXSCAN(rooms_by_creator_recent)` | 9 / 9 |
| Transcript page (50) | `LIMIT ← FETCH ← IXSCAN(room_messages_by_kind_cursor)` | 84 / 84 |
| Translations for a page | `FETCH ← IXSCAN(room_messages_by_utterance)` | 4 / 2 |
| Search this meeting | `SORT ← FETCH ← IXSCAN(room_messages_by_kind)` | one meeting's messages (1,000) |

No query uses a collection scan. My meetings rows use two batched lookups per page
(archives and memberships by `room_id $in`), never one query per row.

## 4. APIs

### Room management (room token + session)

| Method | Path | Who |
| --- | --- | --- |
| GET | `/api/rooms/{room_id}/permissions` | any participant (own role + capabilities) |
| POST | `/api/rooms/{room_id}/lock`, `/unlock` | host |
| PATCH | `/api/rooms/{room_id}/password` `{password}` | host |
| DELETE | `/api/rooms/{room_id}/password` | host |
| POST | `/api/rooms/{room_id}/participants/{participant_id}/mute` | host, co-host (target below them) |
| POST | `/api/rooms/{room_id}/participants/{participant_id}/remove` | host, co-host (target below them) |
| PATCH | `/api/rooms/{room_id}/participants/{participant_id}/role` `{role: co_host|participant}` | host |
| POST | `/api/rooms/{room_id}/moderation/mute` `{target_participant_id}` | older clients; same checks |

Changed: `POST /api/rooms` accepts `title` and records the signed-in creator as host;
`POST /api/rooms/{id}/join` returns `participant.role` and refuses `403 removed_from_room`
and `403 room_locked`; BRSE enable/disable, relay mode and recording start/stop now require
the permission. Routes use the participant ID (what clients know) instead of the user ID,
so user IDs are never exposed to other participants.

### History and search (user session)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/meetings?page&page_size&q&filter=all|created|recorded|summary&range=all|today|7d|30d` | 20 per page, newest first |
| GET | `/api/meetings/search?q&page` | content search across your meetings (most recent 200) |
| GET | `/api/meetings/{room_id}` | overview + recordings + participants + counts + final summary |
| GET | `/api/meetings/{room_id}/transcript|relay|chat?cursor|before|start&limit` | cursor pages (default 50, max 200), oldest first; `start` is inclusive for jumps |
| GET | `/api/meetings/{room_id}/summary`, `/participants`, `/recordings` | |
| GET | `/api/meetings/{room_id}/search?q&page` | transcript, relay, chat, summary |
| GET | `/api/meetings/{room_id}/messages?kind&page` | kept for older clients |

Access (`MeetingHistoryService.access`): membership in `room_memberships`, or the user ID in
the archive's `participant_user_ids`, or in `room_participants` (older meetings). Removed users
are refused. Not yours → `404 meeting_not_found` (existence is not revealed). Retention over →
`410 meeting_archive_expired` / `410 meeting_archive_deleted`. Recording URLs are presigned
only after the same check.

## 5. Realtime events (existing gateway WebSocket)

| Event | Payload |
| --- | --- |
| `participant.role_changed` | `room_id, participant_id, participant_ids[], old_role, new_role, changed_by, changed_by_name, changed_at` |
| `participant.removed` | `participant_id, removed_by, removed_by_participant_id, removed_at, reason`; the gateway holding that socket then closes it with code **4409** |
| `moderation.participant_muted` | `participant_id, muted_by_host, muted_by, timestamp` |
| `room.lock_changed` | `room_id, locked, changed_by, changed_by_name, changed_at` |
| `room.access_updated` | `room_id, password_required, …` (never the password) |
| `participant.updated` | now carries `role`, `muted_by_host` |
| `room.snapshot` | `self.role`, `self.permissions`, `self.permissions_enforced`; room `title`, `locked` |

Client → server: `participant.self_unmuted` clears "Muted by host" when the user unmutes.

The payload uses participant IDs rather than the `user_id` the spec suggested, for the same
reason as the routes.

## 6. Moderation on the media server

`server/service/gateway/livekit_moderation.py` calls LiveKit's server API:
`mute_published_track` for every microphone track of the target and `remove_participant`.
Both are best effort with a 3 s timeout; the target's client is also told to mute / leave,
and removal revokes room state regardless. LiveKit lets the publisher unmute again, which is
the intended policy (nobody can force someone's microphone on).

## 7. Search

Plain keyword search: case-insensitive substring match (`$regex` on the escaped query,
NFC-normalized), **not** semantic and not stemmed. Substring matching is deliberate:
Japanese, Chinese and Korean have no spaces, so MongoDB `$text` (word tokens) would miss most
matches, and English stemming would be wrong for Vietnamese. Minimum 2 characters (1 for CJK
characters), maximum 100.

Scoping happens before matching: per-meeting search filters by one `room_id` after the access
check; global search first lists the user's own, unexpired rooms (`member_user_ids`) and only
then matches inside those IDs. Results are compact snippets with `[start, end]` highlight
offsets; the frontend renders them as text nodes plus `<mark>` (no HTML from the server).

Known limits: the regex can't use an index, so cost grows with the size of the meetings in
scope (one meeting for "Search this meeting", the user's 200 most recent meetings globally);
no accent-insensitive matching ("trien khai" does not match "triển khai").

## 8. Retention

- The archive's `expires_at` is mirrored to `rooms.archive_expires_at_dt` whenever it changes,
  so My meetings and search hide a meeting the moment its retention ends, before cleanup runs.
- Cleanup (`ArchiveService.delete_archive`) now also deletes `room_memberships`; it already
  deleted `rooms`, `room_messages`, `meeting_summaries`, `room_participants` and recordings.
  Search reads these collections directly, so there is no separate index to clean and no
  ghost result can remain.
- The archive's `participant_user_ids` now includes the creator and excludes removed users.

## 9. Migration

- New rooms: the creator's user ID becomes host at creation.
- Rooms already running when this ships have no recorded creator. They carry
  `RoomState.roles_enabled = false`, so until they end (at most the room duration) they keep the
  previous behaviour: anyone in them can control AI relay and recording, and identity actions
  (mute, remove, lock, password, co-host) are unavailable. Nobody is promoted to host.
- Older meetings: `migrate_membership_history()` runs once at startup (marker
  `system_settings._id = "history_membership_v1"`) and links meetings to users **only** through
  the user ID stored at join time (`room_participants.user_id`), as `participant`. Guests
  without an account and display names are never matched to accounts; nobody becomes host of
  an old room.
- Meetings that ended before the archive lifecycle started (legacy) are not archived, so they
  have no expiry and are not deleted automatically (unchanged behaviour).

## 10. Limitations

- No host transfer; a removed user cannot be let back in; co-hosts can only be assigned to
  people who are in the room.
- Live roles live in Redis for the room's lifetime; the MongoDB copy is written asynchronously
  for history.
- Long transcripts load 50 items per page ("Load more"); the list is not virtualized, so a user
  who loads thousands of rows keeps them all in the DOM.
