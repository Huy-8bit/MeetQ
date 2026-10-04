/** A MeetQ user as returned by the backend. Only the backend decides who is signed in. */
export interface AuthUser {
  id: string;
  email: string;
  name: string;
  avatarUrl: string | null;
}

/** Wire format of `user` in /api/auth/* responses. */
export interface AuthUserPayload {
  id: string;
  email: string;
  name?: string | null;
  avatar_url?: string | null;
}

export interface AuthUserResponse {
  user: AuthUserPayload;
}

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

export function toAuthUser(payload: AuthUserPayload): AuthUser {
  return {
    id: payload.id,
    email: payload.email,
    name: payload.name?.trim() || payload.email,
    avatarUrl: payload.avatar_url || null,
  };
}
