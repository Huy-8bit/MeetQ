import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, onUnauthorized } from "../lib/api";
import {
  USER_SESSION_ERROR_CODES,
  fetchCurrentUser,
  signInWithGoogleCredential,
  signOutUser,
} from "./authApi";
import { disableGoogleAutoSelect } from "./google";
import type { AuthStatus, AuthUser } from "./types";

/** Why the user is signed out, when it is worth telling them. */
export type AuthNotice = "session_ended" | "server_unreachable" | "auth_unavailable" | null;

interface AuthState {
  /** "idle" until a user route asks for the session (admin pages never do). */
  phase: "idle" | AuthStatus;
  user: AuthUser | null;
  notice: AuthNotice;
}

interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  notice: AuthNotice;
  /** Runs GET /api/auth/me once; guards call it on mount. */
  ensureChecked: () => void;
  /** Re-runs GET /api/auth/me (e.g. "Try again" after a network error). */
  refresh: () => Promise<void>;
  signInWithGoogle: (credential: string) => Promise<AuthUser>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export class SessionNotEstablishedError extends Error {
  constructor() {
    super("Google sign-in succeeded, but MeetQ couldn't start a session in this browser.");
    this.name = "SessionNotEstablishedError";
  }
}

function noticeFor(error: unknown): AuthNotice {
  if (error instanceof ApiError) {
    if (error.status === 401) return null;
    if (error.status === 404 || error.status === 501) return "auth_unavailable";
  }
  return "server_unreachable";
}

/**
 * User realm only (Google sign-in). The admin portal has its own session in
 * admin/auth/AdminSession.tsx; neither realm reads or clears the other.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ phase: "idle", user: null, notice: null });
  const inFlight = useRef<Promise<void> | null>(null);
  const phaseRef = useRef(state.phase);
  phaseRef.current = state.phase;

  const refresh = useCallback((): Promise<void> => {
    if (inFlight.current) return inFlight.current;
    setState((current) => ({ ...current, phase: "loading" }));
    const run = fetchCurrentUser()
      .then((user) => setState({ phase: "authenticated", user, notice: null }))
      .catch((error: unknown) => setState({ phase: "unauthenticated", user: null, notice: noticeFor(error) }))
      .finally(() => {
        inFlight.current = null;
      });
    inFlight.current = run;
    return run;
  }, []);

  const ensureChecked = useCallback(() => {
    if (phaseRef.current === "idle") void refresh();
  }, [refresh]);

  // A 401 with a user-session code from any MeetQ API means the session is over.
  useEffect(
    () =>
      onUnauthorized((error, path) => {
        if (path.startsWith("/api/admin")) return;
        if (!USER_SESSION_ERROR_CODES.has(error.code)) return; // e.g. room token errors
        setState((current) =>
          current.phase === "authenticated" ? { phase: "unauthenticated", user: null, notice: "session_ended" } : current,
        );
      }),
    [],
  );

  const signInWithGoogle = useCallback(async (credential: string) => {
    await signInWithGoogleCredential(credential);
    // The backend session (cookie) is the proof of sign-in, not the Google profile.
    let user: AuthUser;
    try {
      user = await fetchCurrentUser();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) throw new SessionNotEstablishedError();
      throw error;
    }
    setState({ phase: "authenticated", user, notice: null });
    return user;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await signOutUser();
    } catch {
      // Best effort: the local state is cleared either way; the next /me call is authoritative.
    }
    disableGoogleAutoSelect();
    setState({ phase: "unauthenticated", user: null, notice: null });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status: state.phase === "idle" ? "loading" : state.phase,
      user: state.user,
      notice: state.notice,
      ensureChecked,
      refresh,
      signInWithGoogle,
      signOut,
    }),
    [ensureChecked, refresh, signInWithGoogle, signOut, state],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return value;
}

/** The signed-in user on a route wrapped by RequireAuth. */
export function useAuthUser(): AuthUser | null {
  return useAuth().user;
}
