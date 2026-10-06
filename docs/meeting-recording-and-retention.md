# Meeting recording, meeting archive and retention

MeetQ can record a meeting server-side, archives every ended meeting to a private S3
bucket, and deletes the whole archive when its retention ends.

Three invariants:

1. **No hidden recording.** Recording starts only from inside a meeting, after a confirmation. Everyone in the room sees it, and people joining later are told.
2. **S3 is private.** Public access is blocked and nothing is public. The only way to read an object is a short-lived presigned URL, issued after authorization.
3. **Expired content is really deleted.** That covers S3 objects (media + JSON) and MongoDB meeting content. Only a content-free tombstone remains.

## Discovered architecture

| Area | Finding |
| --- | --- |
| Realtime provider | Self-hosted **LiveKit** (`livekit-server`, Redis-backed). Room name = MeetQ `room_id` |
| Recording capability | LiveKit **Egress** (Room Composite). It was **not deployed** before this feature; it's now a service in both compose files (`livekit/egress`, same Redis) |
| Live data | Redis room state (TTL) + MongoDB (`rooms`, `room_participants`, `room_messages`, `meeting_summaries`) |
| Meeting end | Last real participant leaves (`state=empty`) or the room expires. Both mark `rooms.status_summary.terminal` and trigger the final summary |
| Background jobs | None besides in-process asyncio tasks. The gateway now runs an archive worker (below) |
| Auth | Google sign-in sessions (`user.id` is stable) and a separate admin session |
| AWS | No AWS infrastructure for MeetQ before this. New: `infra/terraform/storage` |

## Recording

```text
Host / co-host clicks Record → confirm → POST /api/rooms/{id}/recordings
        │
        ▼
Gateway RecordingService ──(LiveKit API)──► Egress: Room Composite, layout "speaker"
        │                                     │ joins as hidden recorder, mixes every track:
        │                                     │ participant audio/video, screen share, BRSE AI voice
        │                                     ▼
        │                                MP4 uploaded directly to S3 (bytes never pass the gateway)
        ▼
recording.* events on the room channel → every participant's REC indicator
```

- **Room-level state** `starting → recording → stopping → processing → ready | failed` lives in MongoDB `meeting_recordings`. It's broadcast as `recording.starting|started|stopping|stopped|processing|ready|failed` with `{recording}`. Clients keep the highest `version`. On join, reconnect or refresh, the client reads `GET /api/rooms/{id}/recordings/current`, and the lobby reads it from `GET /api/rooms/{id}` (`room.recording`).
- **One active recording per room** is enforced three ways: a per-room lock, a Redis lock, and a partial unique index `{room_id} where active=true`. Start is idempotent and returns the running recording. Stop is idempotent too. Transitions are compare-and-set on status, so stop, room expiry and the poller finalize exactly once.
- **Server-side.** The starter can close the tab, lose the network or leave; the recording continues while the room runs. It stops automatically when the meeting ends (room expiry or the last real participant leaving) through a room-end listener plus the reconciler.
- **Failure isolation.** Egress errors mark the recording `failed`, broadcast `recording.failed` and raise the admin issue `RECORDING_FAILED`. Media, relay and chat are not touched.
- **Segments.** Start → Stop → Start creates a new recording (own ID, own MP4). All segments share the meeting's retention.
- **Permission.** Host and co-hosts only (room token + user session; the role is resolved on the server from the user ID, see `docs/room-roles-and-meeting-history.md`). Participants get `403 permission_denied` but still see the REC indicator and every `recording.*` event. Admins cannot start a recording.
- **Format.** MP4 (H.264/AAC), playable in browsers. The "speaker" layout puts an active screen share in focus.
- **Reconciler** (every 3 s). It polls Egress for every pending recording. On completion it checks the S3 object and records its size, duration and timestamps. It fails a start that never became active (90 s) and stops recordings of rooms that have ended.

## Archive

```text
Meeting ends (terminal in MongoDB, nobody back in the room)
  → wait for the final summary (≤ ARCHIVE_SUMMARY_WAIT_SECONDS, default 300 s)
  → build JSON from MongoDB (consistent snapshot after the end)
  → upload to S3, manifest last
  → status: processing_recording (segments still finalizing) → ready | partial
```

Archive statuses:
- `open`: meeting running; created when a recording starts.
- `finalizing`
- `processing_recording`
- `ready`
- `partial`: meeting data archived, a recording failed.
- `failed`: upload error; retried with exponential backoff up to 1 h, and shown as admin issue `ARCHIVE_FAILED`.
- `deleting`, `deleted`

Meetings without a recording are archived the same way; their recording status is "none".

### S3 layout

```text
s3://<bucket>/meetings/<room_id>/<archive_id>/
  manifest.json          what the archive contains, retention, recordings
  meeting.json           room metadata + counts
  participants.json      display name, language, join/leave (no emails, no user IDs)
  transcript.json        source (+ translated) lines
  relay.json             AI relay lines
  chat.json              chat messages
  summaries.json         interim/final summaries
  recordings/<recording_id>.mp4
```

Objects are tagged with identifiers only (`room_id`, `archive_id`, `environment`) and never carry meeting text. MongoDB keeps the metadata used for listing, access, expiry and S3 keys. Pages never read the JSON back from S3.

## Retention

- **Default 7 days.** Comes from `DEFAULT_MEETING_RETENTION_DAYS` until an admin sets it in **Admin → Settings → Data & retention**, which is stored in MongoDB `system_settings`.
- Each archive **snapshots** the default when it's created (`default_retention_days_snapshot`). Changing the global value later affects **new archives only**.
- **Per-meeting override.** Admin → Recordings → archive → *Data retention* sets `retention_override_days`. *Use default* goes back to the archive's snapshot, not the current global value, so expiries never move silently.
- `expires_at = ended_at + effective days`. If `ended_at` is unknown, the archive creation time is used.
- If a change would put `expires_at` in the past, the API returns `409 retention_expires_immediately`. The UI then asks for **Apply and expire** before sending `confirm_expire: true`.
- **Cleanup worker** (hourly; once shortly after start-up). For each archive with `expires_at <= now`:
  1. Mark `deleting`.
  2. Delete every object under the archive prefix (MP4 + JSON + manifest).
  3. Delete `room_messages`, `meeting_summaries`, `room_participants`, `room_memberships`, `meeting_recordings` and `rooms` for the room (this also removes the meeting from My meetings and from search).
  4. Keep a tombstone with `status=deleted`, `deleted_at` and `deletion_reason`, with no files and no participant IDs.

  The job is idempotent: missing objects are fine and a failed run is retried (admin issue `ARCHIVE_DELETE_FAILED`).
- **Delete now** (admin) does the same with `deletion_reason=admin_deleted`, after the admin types `DELETE`.
- **The S3 lifecycle rule is only a safety net** (abort incomplete multipart uploads after 1 day). There is no bucket-wide expiry, because retention differs per meeting. Versioning is intentionally off, so a delete removes the bytes.
- Redis copies of live room data expire with the room (meeting duration + 5 min).

### Migration (existing data)

On first start, the gateway records `system_settings.archive_lifecycle.managed_since`. Meetings that **ended before** it are legacy: they are neither archived nor deleted automatically, and nothing old is purged on deploy. To bring them under retention later, add an explicit one-off job; deleting them is a product decision.

## Access

| Who | Can |
| --- | --- |
| Member (signed-in user who created or joined the room, not removed by the host) | `/meetings` list and detail: recording play/download, summary, full transcript/relay/chat, people with roles, search, expiry. Works after leaving, until expiry |
| Other signed-in users | `404` (display names are never used for access) |
| After expiry/deletion | `410 meeting_archive_expired` / `410 meeting_archive_deleted`; no URL is issued |
| Admin | Archive list/detail, retention, Delete now. **No** start-recording endpoint |

Playback and download use `POST /api/recordings/{id}/playback-url|download-url`. These return a presigned GET valid for `RECORDING_URL_TTL_SECONDS` (default 600 s). URLs are never stored or logged.

## APIs

| Method | Path | Auth |
| --- | --- | --- |
| POST | `/api/rooms/{room_id}/recordings` | room token + user |
| POST | `/api/rooms/{room_id}/recordings/{recording_id}/stop` | room token + user |
| GET | `/api/rooms/{room_id}/recordings/current` | room token + user |
| GET | `/api/meetings`, `/api/meetings/search`, `/api/meetings/{room_id}` and `…/transcript`, `…/relay`, `…/chat`, `…/summary`, `…/participants`, `…/recordings`, `…/search`, `…/messages` | user (member) — see `docs/room-roles-and-meeting-history.md` |
| GET | `/api/recordings/{recording_id}` | user (participant) |
| POST | `/api/recordings/{recording_id}/playback-url`, `/download-url` | user (participant) |
| GET | `/api/admin/recordings?filter=all\|ready\|processing\|failed\|expiring_soon\|expired` | admin |
| GET | `/api/admin/archives/{archive_id}` | admin |
| GET/PATCH | `/api/admin/settings/retention` | admin |
| PATCH | `/api/admin/archives/{archive_id}/retention` `{retention_days \| use_default, confirm_expire}` | admin |
| DELETE | `/api/admin/archives/{archive_id}` `{confirm: "DELETE"}` | admin |

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `MEETING_ARCHIVE_BUCKET` | — | Without it: no recording; archives stay in MongoDB (`storage=none`) and still expire |
| `AWS_REGION` | — | Bucket region |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | AWS chain | Gateway credentials. Prod compose maps them from `ARCHIVE_AWS_*`; an instance or task role also works |
| `MEETING_RECORDING_ENABLED` | `true` | Feature flag for the Record button |
| `DEFAULT_MEETING_RETENTION_DAYS` | `7` | Until an admin sets it |
| `RECORDING_LAYOUT` | `speaker` | Egress template layout |
| `RECORDING_URL_TTL_SECONDS` | `600` | Presigned URL lifetime (60–3600) |
| `ARCHIVE_SUMMARY_WAIT_SECONDS` | `300` | Max wait for the final summary before archiving |
| `ARCHIVE_CLEANUP_INTERVAL_SECONDS` | `3600` | Retention cleanup cadence |
| `S3_ENDPOINT_URL`, `S3_PUBLIC_ENDPOINT_URL`, `S3_FORCE_PATH_STYLE`, `S3_SERVER_SIDE_ENCRYPTION`, `S3_CREATE_BUCKET` | — | Local S3-compatible storage only |

LiveKit Egress reads its upload target from its config (`storage.s3` in `EGRESS_CONFIG_BODY`), so recording requests contain only the object key and never credentials.

## AWS setup (production)

```bash
cd infra/terraform/storage
cp env/prod.tfvars.example env/prod.tfvars
terraform init && terraform workspace select -or-create prod
terraform plan -var-file=env/prod.tfvars
terraform apply -var-file=env/prod.tfvars    # creates the private bucket, policy, IAM user
aws iam create-access-key --user-name "$(terraform output -raw iam_user_name)"   # store in the server's .env only
```

Then set `MEETING_ARCHIVE_BUCKET`, `AWS_REGION`, `ARCHIVE_AWS_ACCESS_KEY_ID` and `ARCHIVE_AWS_SECRET_ACCESS_KEY` in the server's `.env.production` and start the stack (`egress` is included). If the backend later runs on AWS, use `attach_to_role_names` and drop the access key.

## Local development

`make dev` starts the whole stack:
- **RustFS** (`s3`, S3 API on `localhost:9000`, private bucket created by the gateway)
- **LiveKit Egress**
- the gateway worker

Recording works end to end locally. Playback URLs point at `http://localhost:9000`.

## Verified end to end (local)

- Two signed-in users.
- Record → confirmation → both see `REC m:ss`. A late joiner gets the lobby warning.
- The starter leaves and recording continues. The other user stops it.
- Egress uploads a 1280×720 MP4. It reaches `ready` with its size and duration, and plays from a presigned URL.
- After the meeting ends, the archive is built automatically with all JSON files + manifest and expires in 7 days.
- An admin retention change that expires the meeting returns `409`. After confirmation, cleanup removes every S3 object and the MongoDB content, and the user receives `410`.

## Known limitations

- Egress Room Composite needs about 2–4 CPU cores per recording on the server running `egress`. Size the host accordingly.
- The recording mixes all audio published in the room, including both directions of AI voice in a two-language room. It reflects the room, not what one listener heard.
- One archive bucket for recordings and meeting JSON. Database backups belong in a separate bucket.
- No bulk "apply new default to existing archives" action. Legacy (pre-lifecycle) meetings are not managed.
- The local S3 (RustFS) is for development only. MinIO and LocalStack images are no longer freely available.
