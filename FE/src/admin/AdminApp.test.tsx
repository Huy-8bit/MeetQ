import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ADMIN_ME, HEALTHY_SYSTEM, mockFetch, renderAdmin, seedAdminSession } from "./test-utils";

const OVERVIEW = {
  generated_at: "2026-10-03T10:00:00Z",
  history_available: true,
  kpis: {
    active_rooms: { value: 3, previous: null, available: true, note: null },
    open_rooms: { value: 4, previous: null, available: true, note: null },
    participants_online: { value: 7, previous: null, available: true, note: null },
    ai_enabled_rooms: { value: 3, previous: null, available: true, note: null },
    meetings_today: { value: 12, previous: 9, available: true, note: null },
    relay_errors_1h: { value: 2, previous: 5, available: true, note: null },
    summary_failures_today: { value: 0, previous: 0, available: true, note: null },
  },
  live_rooms: [],
  system_health: HEALTHY_SYSTEM,
  ai_health: {
    window_minutes: 15,
    stt: { status: "healthy", reason: "10 request(s), 0 error(s)" },
    translation: { status: "degraded", reason: "2 error(s) of 10" },
    voice: { status: "unknown", reason: "No traffic" },
    summary: { status: "healthy", reason: "3 generated" },
  },
  recent_issues: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("admin routing and auth", () => {
  it("redirects to the sign-in page without a session", async () => {
    mockFetch({});
    renderAdmin("/admin/live-rooms");
    expect(await screen.findByRole("heading", { name: "Sign in to the admin portal" })).toBeInTheDocument();
  });

  it("signs in with username and password, then shows the overview", async () => {
    let signedIn = false;
    const { calls } = mockFetch({
      "/api/admin/auth/login": () => {
        signedIn = true;
        return { body: ADMIN_ME };
      },
      "/api/admin/auth/me": () =>
        signedIn ? { body: ADMIN_ME } : { status: 401, body: { error: { code: "admin_auth_required", message: "x" } } },
      "/api/admin/health": () => ({ body: HEALTHY_SYSTEM }),
      "/api/admin/overview": () => ({ body: OVERVIEW }),
    });
    renderAdmin("/admin");

    await userEvent.type(await screen.findByLabelText("Username"), "ops");
    await userEvent.type(screen.getByLabelText("Password"), "secret");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
    expect(await screen.findByText("Meetings today")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText(/\+3 vs this time yesterday/)).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
    expect(screen.getByText("No open rooms")).toBeInTheDocument();
    expect(screen.getByText("Ops Admin")).toBeInTheDocument();

    const loginCall = calls.find((call) => call.path === "/api/admin/auth/login");
    expect(JSON.parse(String(loginCall?.init?.body))).toEqual({ username: "ops", password: "secret" });
    // Cookie session: no bearer token, credentials always included.
    const overviewCall = calls.find((call) => call.path === "/api/admin/overview");
    expect(overviewCall?.init?.credentials).toBe("include");
    expect((overviewCall?.init?.headers as Record<string, string>).Authorization).toBeUndefined();
    expect(window.sessionStorage.length).toBe(0);
    expect(window.localStorage.getItem("meetq_admin_session")).toBeNull();
  });

  it("shows a generic message when the credentials are wrong", async () => {
    mockFetch({
      "/api/admin/auth/login": () => ({ status: 401, body: { error: { code: "invalid_credentials", message: "Incorrect admin password." } } }),
    });
    renderAdmin("/admin");
    await userEvent.type(await screen.findByLabelText("Username"), "ops");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Incorrect username or password.")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("has no Google sign-in", async () => {
    mockFetch({});
    renderAdmin("/admin/login");
    expect(await screen.findByLabelText("Username")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /google/i })).not.toBeInTheDocument();
    expect(screen.queryByTitle(/google/i)).not.toBeInTheDocument();
  });

  it("signs out through the admin logout endpoint only", async () => {
    seedAdminSession();
    const { calls } = mockFetch({
      "/api/admin/health": () => ({ body: HEALTHY_SYSTEM }),
      "/api/admin/overview": () => ({ body: OVERVIEW }),
      "/api/admin/auth/logout": () => ({ status: 204, body: null }),
    });
    renderAdmin("/admin");
    await userEvent.click(await screen.findByRole("button", { name: /Sign out/ }));
    expect(await screen.findByLabelText("Username")).toBeInTheDocument();
    expect(calls.some((call) => call.path === "/api/admin/auth/logout")).toBe(true);
    expect(calls.some((call) => call.path === "/api/auth/logout")).toBe(false);
  });

  it("returns to sign-in when the session is rejected", async () => {
    seedAdminSession();
    mockFetch({
      "/api/admin/health": () => ({ status: 401, body: { error: { code: "admin_session_expired", message: "Admin session expired." } } }),
      "/api/admin/overview": () => ({ status: 401, body: { error: { code: "admin_session_expired", message: "Admin session expired." } } }),
    });
    renderAdmin("/admin");
    expect(await screen.findByText("Your admin session expired.")).toBeInTheDocument();
  });

  it("does not invent metrics when history is unavailable", async () => {
    seedAdminSession();
    mockFetch({
      "/api/admin/health": () => ({ body: HEALTHY_SYSTEM }),
      "/api/admin/overview": () => ({
        body: {
          ...OVERVIEW,
          history_available: false,
          kpis: {
            ...OVERVIEW.kpis,
            meetings_today: { value: null, previous: null, available: false, note: "History storage unavailable" },
          },
        },
      }),
    });
    renderAdmin("/admin");
    expect(await screen.findByText(/History storage is unavailable/)).toBeInTheDocument();
    expect(screen.getAllByText("Not available").length).toBeGreaterThan(0);
  });
});
