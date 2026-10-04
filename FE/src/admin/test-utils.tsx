import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { AdminSessionProvider } from "./auth/AdminSession";
import { AdminRoutes } from "./AdminApp";

export interface FetchCall {
  path: string;
  params: URLSearchParams;
  init?: RequestInit;
}

type Handler = (call: FetchCall) => { status?: number; body: unknown } | Promise<{ status?: number; body: unknown }>;

export const ADMIN_ME = { admin: { id: "adm_1", username: "ops", display_name: "Ops Admin" }, expires_at: null };
const ADMIN_SIGNED_OUT = { status: 401, body: { error: { code: "admin_auth_required", message: "Admin sign-in required." } } };

let adminSignedIn = false;

/** Routes fetch() by URL pathname; unmatched requests fail the test loudly. */
export function mockFetch(handlers: Record<string, Handler>) {
  const signedIn = adminSignedIn;
  adminSignedIn = false;
  handlers = {
    "/api/admin/auth/me": () => (signedIn ? { body: ADMIN_ME } : ADMIN_SIGNED_OUT),
    ...handlers,
  };
  const calls: FetchCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input.toString());
    const call = { path: url.pathname, params: url.searchParams, init };
    calls.push(call);
    const handler = handlers[url.pathname];
    if (!handler) {
      return new Response(JSON.stringify({ error: { code: "not_mocked", message: url.pathname } }), { status: 500 });
    }
    const { status = 200, body } = await handler(call);
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

/** The next mockFetch() answers GET /api/admin/auth/me with a signed-in admin (cookie session). */
export function seedAdminSession() {
  adminSignedIn = true;
}

export function renderAdmin(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AdminSessionProvider>
        <Routes>
          <Route path="/admin/*" element={<AdminRoutes />} />
        </Routes>
      </AdminSessionProvider>
    </MemoryRouter>,
  );
}

export const HEALTHY_SYSTEM = {
  checked_at: "2026-10-03T10:00:00Z",
  overall: "healthy",
  components: [{ key: "redis", label: "Redis", status: "healthy", detail: null }],
};

export function liveRoom(overrides: Record<string, unknown> = {}) {
  return {
    room_id: "rm_abc123",
    state: "active",
    status: "live",
    room_languages: ["vi", "ja"],
    participants_online: 2,
    participants_total: 2,
    ai_mode: "voice_text",
    brse_enabled: true,
    brse_state: "translating",
    runtime_attached: true,
    created_at: "2026-10-03T09:30:00Z",
    activated_at: "2026-10-03T09:31:00Z",
    expires_at: "2026-10-03T10:00:00Z",
    seconds_left: 840,
    recent_error_count: 0,
    last_error_at: null,
    ...overrides,
  };
}
