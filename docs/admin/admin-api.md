# MeetQ Admin API

> **Auth (2026-10-04):** operators sign in at `/admin/login` with **Username + Password** (`POST /api/admin/auth/login`), and every `/api/admin/*` route is authorized by the HttpOnly **`meetq_admin_session`** cookie (`Path=/api/admin`, `SameSite=Strict`), checked with `GET /api/admin/auth/me` and ended with `POST /api/admin/auth/logout`. Configure `ADMIN_USERNAME` + `ADMIN_PASSWORD_HASH` (see [../auth-backend-contract.md](../auth-backend-contract.md)). The former password-only `POST /api/admin/session` → bearer-token flow and `ADMIN_SESSION_SECRET` have been removed.


Base path `/api/admin`. Implementation: `BE/server/service/admin/api.py`; response models: `BE/server/service/admin/schemas.py` (mirrored in `FE/src/admin/api/types.ts`).

## Conventions

- **Auth**: every route requires the `meetq_admin_session` cookie from `POST /api/admin/auth/login` (send requests with `credentials: "include"`).
- **Errors** use the gateway envelope: `{"error": {"code": "...", "message": "...", "details"?: {...}}}`.

| Status | Code | When |
| --- | --- | --- |
| 401 | `admin_auth_required`, `admin_session_expired`, `invalid_credentials` | no / expired admin session, wrong username or password |
| 403 | `origin_not_allowed` | state-changing request from an origin outside `CORS_ALLOWED_ORIGINS` |
| 404 | `room_not_found`, `meeting_not_found`, `issue_not_found` | unknown id |
| 409 | `meeting_summary_not_ready` | regenerate final summary while the meeting is live |
| 422 | `invalid_request`, `invalid_window`, … | bad query values (patterns validated server-side) |
| 429 | `too_many_attempts` | sign-in rate limit |
| 503 | `admin_disabled`, `history_unavailable`, `service_unavailable` | `ADMIN_USERNAME`/password not set, MongoDB unavailable |

- **Pagination**: `page` (1-based), `page_size` (≤ 100). Paged responses: `{items, page, page_size, total}`.
- **Times** are ISO-8601 UTC strings. Filters accept ISO-8601.
- Enumerations: room `status` ∈ `live|empty|error|expired`; `ai_mode` ∈ `voice_text|text_only|captions|summary_capture|off`; `language` ∈ `vi|en|ja|zh|ko|fr|es`; `window` ∈ `15m|1h|24h|7d|30d`.

## Session

| Method | Path | Body / query | Response |
| --- | --- | --- | --- |
| POST | `/auth/login` | `{"username": "...", "password": "..."}` | `{admin: {id, username, display_name}, expires_at}` + `Set-Cookie: meetq_admin_session` |
| GET | `/auth/me` | — | `{admin, expires_at}` or `401` |
| POST | `/auth/logout` | `{}` | `204`, clears the cookie |

## Health & overview

| Method | Path | Query | Response |
| --- | --- | --- | --- |
| GET | `/health` | — | `SystemHealth {checked_at, overall, components[{key,label,status,detail}]}` (Redis, BRSE runtime heartbeat, MongoDB, LiveKit) |
| GET | `/overview` | `today_start` (start of the operator's local day) | `{generated_at, history_available, kpis{active_rooms, open_rooms, participants_online, ai_enabled_rooms, rooms_with_errors, meetings_today, relay_errors_1h, summary_failures_today}, live_rooms[≤10], system_health, ai_health, recent_issues[]}` — each KPI is `{value, previous, available, note}`; `available=false` when history storage is down |

## Live rooms (Redis + LiveKit)

| Method | Path | Query | Response |
| --- | --- | --- | --- |
| GET | `/rooms` | `q`, `status`, `ai_mode`, `language`, `page`, `page_size` | `Page<LiveRoomRow> + counts_by_status, runtime_online` |
| GET | `/rooms/{room_id}` | — | `LiveRoomDetail {room, participants[] (with media: connection/microphone/camera/screen_share), media_source, brse{state, current_speaker, queue_depth, speakers[], latency{last, stt_ms/first_text_ms/first_audio_ms/total_ms summaries}, last_success_at, last_error, …}}` |
| GET | `/rooms/{room_id}/timeline` | `limit` ≤ 150 | `{source: "live"|"history", items[TimelineItem]}` newest first — relay traces with `stages[{key,label,status,ms,note}]`, joined `source_text`/`relay_text`, and AI errors. Falls back to MongoDB when the room left the live store. |
| GET | `/rooms/{room_id}/transcript` | `kind` = `all|source|relay|chat|system`, `limit` ≤ 200 | `{items[TranscriptLine], limit_note}` (live store keeps 50 lines / 100 chat) |

`LiveRoomRow`: `room_id, state, status, room_languages, participants_online, participants_total, ai_mode, brse_enabled, brse_state, runtime_attached, created_at, activated_at, expires_at, seconds_left, recent_error_count, last_error_at`.

## Meetings (MongoDB)

| Method | Path | Query / body | Response |
| --- | --- | --- | --- |
| GET | `/meetings` | `q` (room id or participant name), `from`, `to`, `language`, `ai_mode`, `summary_status` (`completed|failed|skipped|pending|none`), `status` (`live|ended`), `page`, `page_size` | `Page<MeetingRow>` sorted by creation, newest first |
| GET | `/meetings/{room_id}` | — | `MeetingDetail {meeting, activated_at, expires_at, brse_mode, brse_output_mode, counts{source,relay,translated,chat,messages,participants}, summaries{final,interim} (status only), is_live_in_runtime_store}` — counts come from the room document, no message scan |
| GET | `/meetings/{room_id}/transcripts` | `page`, `page_size` | `Page<TranscriptLine>` source lines, chronological |
| GET | `/meetings/{room_id}/relays` | `page`, `page_size` | `Page<RelayRow>` with `delivery_state`, `delivery_reason`, `latency_ms`, `voice_delivered` joined from traces in one `$in` query |
| GET | `/meetings/{room_id}/chat` | `page`, `page_size` | `Page<TranscriptLine>` with `translations[]` |
| GET | `/meetings/{room_id}/summaries` | — | `{final, interim}` full summary documents |
| POST | `/meetings/{room_id}/summaries/final` | `{"language": "vi" | null}` | regenerated final summary (existing summary service; only after the meeting ended) |
| GET | `/meetings/{room_id}/participants` | — | `MeetingParticipantRow[]` |

## AI, issues, analytics, config

| Method | Path | Query | Response |
| --- | --- | --- | --- |
| GET | `/ai/metrics` | `window` | `{stages{stt,translation,voice,delivery: {requests, success, errors, success_rate, error_rate, latency{samples,avg,p50,p95,p99}, error_breakdown[]}}, summary{requests, completed, failed, skipped, pending, latency}, language_pairs[], health, sampled, truncated, percentile_min_samples}` |
| GET | `/issues` | `window`, `include_info` | `{items[IssueAggregate{code,title,stage,severity,description,occurrences,affected_rooms,first_at,latest_at,top_language_pair}], truncated}` |
| GET | `/issues/{code}` | `window`, `page`, `page_size` | `{issue, occurrences: Page<IssueOccurrence>}` |
| GET | `/analytics` | `from`, `to` (≤ 366 days), `tz_offset_minutes` | `{totals{rooms_created, meetings, avg_duration_seconds, avg_participants, total_participants, source_lines, relay_lines, chat_messages, live_summaries, final_summaries}, meetings_over_time[{date, meetings}], language_distribution[], ai_mode_usage[], feature_usage{translated_chat_messages, live_summaries, final_summaries, screen_share(available=false)}}` |
| GET | `/config` | — | `{editable: false, room[], ai[], languages[], notifications[], operations[]}`; every item has `source` (`environment`, `backend constant`, `frontend constant`) |

## Public

| Method | Path | Response |
| --- | --- | --- |
| GET | `/api/config` (no auth) | `{room_meeting_duration_seconds, supported_languages}` — used by the Home page |

## Example

```bash
curl -s -c /tmp/admin.jar -X POST localhost:8000/api/admin/auth/login \
  -H 'content-type: application/json' -d '{"username":"dev-admin","password":"dev-admin-password"}'

curl -s -b /tmp/admin.jar "localhost:8000/api/admin/rooms?status=error"
curl -s -b /tmp/admin.jar "localhost:8000/api/admin/rooms/rm_xxx/timeline?limit=20"
curl -s -b /tmp/admin.jar "localhost:8000/api/admin/issues/RELAY_TOO_LATE?window=24h"
```
