# Auth backend contract (user + admin)

The sign-in contract between the MeetQ frontend (`FE/src/auth/`, `FE/src/admin/auth/`) and backend (`BE/server/service/auth/`). Both sides implement it; tests: `BE/tests/test_auth_api.py`, `FE/src/auth/auth.test.tsx`, `FE/src/admin/AdminApp.test.tsx`.

## Backend implementation and configuration

| Piece | Where |
| --- | --- |
| Endpoints | `server/service/auth/api.py` (`/api/auth/*`, `/api/admin/auth/*`) |
| Google ID token verification (RS256 via Google JWKS, `aud`, `iss`, `exp`, `email_verified`, domain allow-list) | `server/service/auth/google.py` |
| Opaque sessions in Redis (only SHA-256 of the token is stored) | `server/service/auth/sessions.py` |
| Cookies | `server/service/auth/cookies.py` |
| `current_user` / `require_user` / `current_admin` dependencies | `server/service/auth/dependencies.py` |
| Admin password hashing (scrypt, stdlib) | `server/service/auth/passwords.py` |
| CORS allow-list + CSRF origin check | `server/service/gateway/origins.py`, middleware in `gateway/main.py` |

| Env var | Default | Meaning |
| --- | --- | --- |
| `GOOGLE_CLIENT_ID` | — | Web client ID (same as `VITE_GOOGLE_CLIENT_ID`); without it `/api/auth/google` returns `503 auth_unavailable` |
| `GOOGLE_ALLOWED_DOMAINS` | empty | Comma-separated email domains allowed; empty = any verified Google account |
| `USER_SESSION_TTL_SECONDS` | `1209600` (14 d) | User session lifetime (fixed, not sliding) |
| `USER_AUTH_REQUIRED` | `true` | Room create/view/join, summaries and `/api/test/*` need a user session |
| `ADMIN_USERNAME` | — | Admin portal is disabled (`503 admin_disabled`) until this and a password are set |
| `ADMIN_PASSWORD_HASH` | — | `scrypt$…` hash: `docker compose exec gateway python -m server.service.auth.passwords` |
| `ADMIN_PASSWORD` | — | Plain-text alternative for local development only (ignored when the hash is set) |
| `ADMIN_SESSION_TTL_SECONDS` | `43200` (12 h) | Admin session lifetime |
| `AUTH_COOKIE_SECURE` | `true` | `false` only for plain-http setups (local compose sets `false`) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Exact frontend origins (CORS + CSRF) |

Users are upserted into MongoDB `users` (`_id = usr_…` derived from the Google `sub`) when MongoDB is configured. Room tokens (`/api/rooms/{id}/…` after join, WebSocket) are unchanged.

Two independent realms:

| Realm | Who | Sign-in | Session | Frontend routes |
| --- | --- | --- | --- | --- |
| **User** | Meeting users | Google Identity Services ID token | `meetq_session` cookie (suggested name) | `/`, `/login`, `/rooms/:roomId`, `/test` |
| **Admin** | Operators | Username + password | `meetq_admin_session` cookie (suggested name) | `/admin/login`, `/admin/*` |

A Google-signed-in user never gets admin access through the user session, and signing out of one realm must not end the other. Use **different cookies** (and different server-side session stores or a `realm` field) for the two.

---

## 1. Conventions

### Requests

- JSON bodies with `Content-Type: application/json`.
- Every request is sent with `credentials: "include"` (cookies travel cross-origin from the SPA to the API).
- The frontend never sends an `Authorization` header for user or admin sessions. (Room tokens for `/api/rooms/*` keep using `Authorization: Bearer <room token>`; unchanged.)

### Error envelope

Same shape as the rest of the API:

```json
{ "error": { "code": "auth_required", "message": "Sign in required.", "request_id": "req_..." } }
```

### 401 codes the frontend acts on

| Realm | Code | Frontend behaviour |
| --- | --- | --- |
| User | `auth_required`, `session_expired`, `invalid_session` | From **any** non-admin endpoint: clears the user, shows `/login` ("Your session ended…"), keeps the current page in `next` |
| User | any other 401 code (e.g. room token `invalid_token`) | Not treated as a sign-out |
| Admin | any 401 from `/api/admin/*` | Clears the admin session, shows `/admin/login`; `admin_session_expired` shows "Your admin session expired." |

So: return `401` with one of the user codes above when a protected user endpoint has no valid user session; do **not** reuse those codes for room-token failures.

---

## 2. User realm (Google)

### `POST /api/auth/google`

Exchanges a Google ID token (the `credential` from Google Identity Services) for a MeetQ session.

Request:

```json
{ "credential": "<google-id-token (JWT)>" }
```

Backend must:

1. Verify the ID token signature against Google's keys (e.g. `google.oauth2.id_token.verify_oauth2_token` in Python, or Google's JWKS).
2. Check `aud` == your Web client ID (`GOOGLE_CLIENT_ID`, same value as the frontend's `VITE_GOOGLE_CLIENT_ID`).
3. Check `iss` ∈ {`accounts.google.com`, `https://accounts.google.com`} and `exp` not passed.
4. Require `email_verified == true`.
5. Optionally restrict who may sign in (allowed domains via `hd`, allow-list) → `403`.
6. Upsert the user by Google `sub` (not by email); store `email`, `name`, `picture`.
7. Create a server-side session (or a signed, short-lived token) and set it as an HttpOnly cookie.
8. Never log the credential.

Responses:

| Status | Body | When |
| --- | --- | --- |
| `200` | `{ "user": User }` + `Set-Cookie` | Signed in |
| `400` | `invalid_request` | Missing/empty `credential` |
| `401` | `invalid_google_credential` | Bad signature, wrong `aud`/`iss`, expired, unverified email |
| `403` | `account_not_allowed` (message shown to the user) | Account not allowed to use MeetQ |
| `429` | `too_many_attempts` | Rate limit |

`User`:

```json
{
  "id": "usr_7f3a…",
  "email": "user@example.com",
  "name": "Nguyen Gia Huy",
  "avatar_url": "https://lh3.googleusercontent.com/…"
}
```

`name` and `avatar_url` may be `null`. The frontend uses `name` to pre-fill the lobby display name.

After a `200`, the frontend immediately calls `GET /api/auth/me`. If that returns `401`, it tells the user the browser didn't keep the session (cookie blocked / misconfigured), so cookie and CORS setup are verified on every sign-in.

### `GET /api/auth/me`

The source of truth for "is this browser signed in". Called on app start for every user route.

| Status | Body |
| --- | --- |
| `200` | `{ "user": User }` |
| `401` | `auth_required` (no cookie) / `session_expired` / `invalid_session` |

The frontend renders nothing protected until this returns. `404`/`501` are shown as "Sign-in isn't available on this MeetQ server yet."; network errors as "Couldn't reach MeetQ".

### `POST /api/auth/logout`

Request body: `{}`. Ends the **user** session only (delete it server-side; clear the cookie with the same `Path`/`Domain` attributes and `Max-Age=0`).

| Status | When |
| --- | --- |
| `204` (or `200`) | Always, also when already signed out (idempotent) |

The frontend clears its state and goes to `/login` even if this call fails, and calls Google's `disableAutoSelect()`.

---

## 3. Admin realm (username + password)

No Google sign-in, no default credentials (no `admin/admin`), no credentials in the frontend.

### `POST /api/admin/auth/login`

```json
{ "username": "ops", "password": "…" }
```

Backend must:

- Store admin passwords with a slow hash (MeetQ: scrypt, N=2^15, r=8); compare in constant time; same error for unknown user and wrong password.
- Rate-limit failed attempts per username and per IP (→ `429 too_many_attempts`).
- Never log the password or the request body.
- Bootstrap the admin out of band, never a hard-coded default. MeetQ reads one account from `ADMIN_USERNAME` + `ADMIN_PASSWORD_HASH`.

| Status | Body | When |
| --- | --- | --- |
| `200` | `AdminAuth` + `Set-Cookie: meetq_admin_session=…` | Signed in |
| `401` | `invalid_credentials` | Wrong username or password (frontend shows "Incorrect username or password.") |
| `429` | `too_many_attempts` | Rate limited |
| `503` | `admin_disabled` | Admin portal turned off |

`AdminAuth`:

```json
{
  "admin": { "id": "adm_1", "username": "ops", "display_name": "Ops Admin" },
  "expires_at": "2026-10-03T22:00:00Z"
}
```

`display_name` and `expires_at` are optional.

### `GET /api/admin/auth/me`

| Status | Body |
| --- | --- |
| `200` | `AdminAuth` |
| `401` | `admin_auth_required` / `admin_session_expired` |

### `POST /api/admin/auth/logout`

Ends the admin session only. `204`, idempotent.

### Existing admin data endpoints

`/api/admin/health`, `/overview`, `/rooms`, `/meetings`, … keep their responses and authenticate with the **admin cookie** (`server/service/admin/dependencies.py::require_admin`). The legacy `POST /api/admin/session` bearer flow has been removed.

---

## 4. Cookies

| Attribute | User cookie | Admin cookie |
| --- | --- | --- |
| Name (suggested) | `meetq_session` | `meetq_admin_session` |
| `HttpOnly` | yes | yes |
| `Secure` | yes (browsers accept `Secure` on `http://localhost`) | yes |
| `SameSite` | `Lax` | `Strict` (or `Lax`) |
| `Path` | `/` | `/api/admin` (keeps it off user endpoints) |
| `Domain` | omit (host-only on the API host) | omit |
| Lifetime | e.g. 7–30 days sliding, server-side expiry | e.g. 8–12 h, no sliding beyond a max |

Why `SameSite=Lax` works: the SPA (`https://meetq.example.com`) and API (`https://api.meetq.example.com`) are **same-site** (same registrable domain), so cookies are sent on `fetch` with `credentials: "include"`. Locally, `http://localhost:3000` → `http://localhost:8000` is also same-site.

If the frontend and API are on **different sites** (e.g. `meetq.pages.dev` → `api.example.com`), `SameSite=None; Secure` is required and third-party-cookie blocking (Safari, Chrome phase-out) can break sign-in. Keep both on one registrable domain.

Store only an opaque session ID in the cookie (or a signed token with a server-side revocation list); never the Google ID token.

---

## 5. CORS

Cookie sessions need an explicit origin allow-list:

```http
Access-Control-Allow-Origin: https://meetq.example.com
Access-Control-Allow-Credentials: true
Vary: Origin
```

- Never `Access-Control-Allow-Origin: *` together with credentials; browsers reject it.
- The gateway reads the list from `CORS_ALLOWED_ORIGINS` (comma-separated, exact origins, `*` is ignored): see `BE/server/service/gateway/main.py`. Defaults to `http://localhost:3000,http://127.0.0.1:3000`; set it per environment, e.g. `CORS_ALLOWED_ORIGINS=https://meetq.example.com,https://dev.meetq.example.com`.
- Preflight (`OPTIONS`) must allow `Content-Type` and methods `GET, POST, PATCH, DELETE`.

---

## 6. CSRF

With cookie auth, protect every state-changing request (`POST`, `PATCH`, `PUT`, `DELETE`):

1. **Origin check** (required): reject when `Origin` (or `Referer` if `Origin` is absent) is not in `CORS_ALLOWED_ORIGINS`.
2. **JSON only**: require `Content-Type: application/json`. Cross-site HTML forms cannot send it, and it forces a CORS preflight that the allow-list rejects.
3. `SameSite=Lax`/`Strict` cookies as a second layer.

Optional: a double-submit token header (`X-CSRF-Token`) if you ever accept non-JSON bodies. The frontend does not send one today.

`POST /api/auth/google` must also apply the Origin check (prevents login CSRF). Google Identity Services popup mode does not set the `g_csrf_token` cookie, so don't require it.

---

## 7. Session expiry and logout

- Expired or revoked session → `401 session_expired` (user) / `401 admin_session_expired` (admin). The frontend then signs the person out of that realm only.
- Logout deletes the server-side session and clears the cookie. A second logout is a no-op `204`.
- Rotate the session ID on sign-in (no session fixation).
- Optionally re-verify the user (`email_verified`, allow-list) when refreshing a sliding session.

---

## 8. Quick checks

```bash
# Signed out → 401 auth_required
curl -i https://api.meetq.example.com/api/auth/me -H 'Origin: https://meetq.example.com'

# CORS preflight echoes the origin with credentials
curl -i -X OPTIONS https://api.meetq.example.com/api/auth/google \
  -H 'Origin: https://meetq.example.com' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'

# Admin login (password from your secret store, not shell history in production)
curl -i -c /tmp/admin.jar https://api.meetq.example.com/api/admin/auth/login \
  -H 'Origin: https://meetq.example.com' -H 'Content-Type: application/json' \
  -d '{"username":"ops","password":"…"}'
curl -i -b /tmp/admin.jar https://api.meetq.example.com/api/admin/auth/me
```

Frontend tests that encode this contract: `FE/src/auth/auth.test.tsx`, `FE/src/admin/AdminApp.test.tsx`.
