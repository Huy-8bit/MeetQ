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
import { ApiError, requestJson } from "../../lib/api";
import { adminEndpoints, adminSignIn, adminSignOut, fetchAdminMe, type AdminEndpoints } from "../api/client";
import type { AdminAuthResponse } from "../api/types";

export type AdminStatus = "loading" | "authenticated" | "unauthenticated";

export interface AdminIdentity {
  id: string;
  username: string;
  displayName: string;
}

interface AdminSessionValue {
  status: AdminStatus;
  isAuthenticated: boolean;
  admin: AdminIdentity | null;
  expiresAt: string | null;
  /** Set when the session ended on its own (expired / revoked) or the server is unreachable. */
  endedReason: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  api: AdminEndpoints;
}

const AdminSessionContext = createContext<AdminSessionValue | null>(null);

interface SessionState {
  status: AdminStatus;
  admin: AdminIdentity | null;
  expiresAt: string | null;
  endedReason: string | null;
}

function toIdentity(response: AdminAuthResponse): AdminIdentity {
  const { admin } = response;
  return { id: admin.id, username: admin.username, displayName: admin.display_name?.trim() || admin.username };
}

function signedIn(response: AdminAuthResponse): SessionState {
  return { status: "authenticated", admin: toIdentity(response), expiresAt: response.expires_at ?? null, endedReason: null };
}

function signedOut(endedReason: string | null = null): SessionState {
  return { status: "unauthenticated", admin: null, expiresAt: null, endedReason };
}

/**
 * Admin realm: username + password, backend cookie session, checked with
 * GET /api/admin/auth/me. Independent from the Google user session: a signed-in
 * MeetQ user gets no admin access, and signing out of one realm leaves the other.
 */
export function AdminSessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: "loading", admin: null, expiresAt: null, endedReason: null });
  const checked = useRef(false);

  useEffect(() => {
    if (checked.current) return;
    checked.current = true;
    fetchAdminMe()
      .then((response) => setState(signedIn(response)))
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) setState(signedOut());
        else setState(signedOut("Couldn't reach the admin API to check your session."));
      });
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    await adminSignIn(username, password);
    // The cookie session is the proof; confirm it before showing the portal.
    let me: AdminAuthResponse;
    try {
      me = await fetchAdminMe();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        throw new ApiError("Signed in, but this browser didn't keep the admin session (cookies blocked?).", {
          code: "admin_session_not_established",
          status: 401,
        });
      }
      throw error;
    }
    setState(signedIn(me));
  }, []);

  const logout = useCallback(async () => {
    try {
      await adminSignOut();
    } catch {
      // Best effort: local state is cleared; /api/admin/auth/me stays authoritative.
    }
    setState(signedOut());
  }, []);

  const authenticated = state.status === "authenticated";

  const api = useMemo(
    () =>
      adminEndpoints(async <T,>(path: string, init?: RequestInit): Promise<T> => {
        if (!authenticated) {
          throw new ApiError("Admin sign-in required.", { code: "admin_auth_required", status: 401 });
        }
        try {
          return await requestJson<T>(path, init);
        } catch (error) {
          if (error instanceof ApiError && error.status === 401) {
            setState(
              signedOut(error.code === "admin_session_expired" ? "Your admin session expired." : "Please sign in again."),
            );
          }
          throw error;
        }
      }),
    [authenticated],
  );

  const value = useMemo<AdminSessionValue>(
    () => ({
      status: state.status,
      isAuthenticated: authenticated,
      admin: state.admin,
      expiresAt: state.expiresAt,
      endedReason: state.endedReason,
      login,
      logout,
      api,
    }),
    [api, authenticated, login, logout, state],
  );

  return <AdminSessionContext.Provider value={value}>{children}</AdminSessionContext.Provider>;
}

export function useAdminSession(): AdminSessionValue {
  const value = useContext(AdminSessionContext);
  if (!value) {
    throw new Error("useAdminSession must be used inside AdminSessionProvider");
  }
  return value;
}

export function useAdminApi(): AdminEndpoints {
  return useAdminSession().api;
}
