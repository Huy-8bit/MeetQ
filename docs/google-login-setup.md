# Google sign-in setup (one time)

MeetQ users sign in with **Google Identity Services** (GIS), "Sign in with Google" button, **popup mode, ID-token flow**:

1. The browser loads `https://accounts.google.com/gsi/client`.
2. The user clicks **Continue with Google** and picks an account in Google's popup.
3. GIS hands the page an **ID token** (`credential`).
4. The frontend posts it to `POST /api/auth/google`; the backend verifies it and sets the session cookie ([auth-backend-contract.md](auth-backend-contract.md)).

There is no OAuth authorization-code redirect, so **no redirect URI** is needed and **no client secret** is used anywhere in the frontend. Code: `FE/src/auth/google.ts`, `FE/src/auth/GoogleSignInButton.tsx`.

## 1. Create the OAuth client

In [Google Cloud Console](https://console.cloud.google.com/) → your project:

1. **APIs & Services → OAuth consent screen** (Google Auth Platform → Branding/Audience):
   - App name `MeetQ`, support email, app logo (optional).
   - Authorized domain: your registrable domain, e.g. `example.com`.
   - Scopes: the defaults `openid`, `email`, `profile` are enough.
   - Audience: **External**. While in *Testing*, only listed test users can sign in; **publish** the app for everyone.
2. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**.
   - Name: `MeetQ web`.
   - **Authorized JavaScript origins** (scheme + host + port, no path, no trailing slash):

     | Environment | Origin |
     | --- | --- |
     | Local dev | `http://localhost:3000` and `http://localhost` |
     | Dev | `https://dev.meetq.example.com` (if you deploy dev) |
     | Production | `https://meetq.example.com` (the Terraform `domain_name`) |

     Google requires `http://localhost` in addition to `http://localhost:<port>` for local testing with the GIS button.
   - **Authorized redirect URIs**: leave empty (popup ID-token flow).
3. Copy the **Client ID** (`…apps.googleusercontent.com`). You do not need the client secret for this flow; keep it out of the repo and the frontend.

Changes to origins can take a few minutes to apply. A missing origin shows Google's `origin_mismatch` / "The given origin is not allowed for the given client ID" in the popup or console.

## 2. Configure MeetQ

The client ID is public (it is compiled into the JS bundle).

| Where | Variable | Value |
| --- | --- | --- |
| Local dev | `FE/.env.development.local` (git-ignored) | `VITE_GOOGLE_CLIENT_ID=<client id>` |
| Deploys | `config/frontend/<env>.env` (git-ignored) | `VITE_GOOGLE_CLIENT_ID=<client id>` |
| Backend | `.env.local` / production env (`GOOGLE_CLIENT_ID`) | `<same client id>`; the gateway checks the token `aud` against it |

Without `VITE_GOOGLE_CLIENT_ID` the sign-in page shows "Google sign-in isn't configured for this build" instead of the button, and `scripts/deploy.sh` refuses to deploy.

## 3. When the production domain changes

Add the new `https://<domain>` to **Authorized JavaScript origins** before deploying to it. This is a Google Cloud setting, not part of the Cloudflare Terraform.

## 4. Troubleshooting

| Symptom | Fix |
| --- | --- |
| Popup: "origin is not allowed" | Add the exact origin (scheme + host + port) to the client |
| Button never appears; "Couldn't load Google sign-in" | A blocker or CSP blocks `accounts.google.com`; allow it |
| "Google sign-in couldn't be verified" | Backend rejected the token: check `GOOGLE_CLIENT_ID` matches, clock skew, `email_verified` |
| "MeetQ couldn't keep you signed in" | Sign-in succeeded but `GET /api/auth/me` returned 401: cookie not set or not sent. Check `Set-Cookie` attributes, `Access-Control-Allow-Credentials`, exact `Access-Control-Allow-Origin`, same registrable domain for SPA and API |
| Only some accounts can sign in | Consent screen still in *Testing*: add test users or publish |
