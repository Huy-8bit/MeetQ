import { requestJson } from "../lib/api";
import { toAuthUser, type AuthUser, type AuthUserResponse } from "./types";

/** User-session endpoints. The session itself is an HttpOnly cookie set by the backend. */
export const USER_AUTH_PATHS = {
  google: "/api/auth/google",
  me: "/api/auth/me",
  logout: "/api/auth/logout",
} as const;

/** 401 error codes that mean "the user session is missing or over" (see docs/auth-backend-contract.md). */
export const USER_SESSION_ERROR_CODES = new Set(["auth_required", "session_expired", "invalid_session"]);

export async function signInWithGoogleCredential(credential: string): Promise<AuthUser> {
  const response = await requestJson<AuthUserResponse>(USER_AUTH_PATHS.google, {
    method: "POST",
    body: JSON.stringify({ credential }),
  });
  return toAuthUser(response.user);
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  const response = await requestJson<AuthUserResponse>(USER_AUTH_PATHS.me);
  return toAuthUser(response.user);
}

export async function signOutUser(): Promise<void> {
  await requestJson<void>(USER_AUTH_PATHS.logout, { method: "POST", body: "{}" });
}
