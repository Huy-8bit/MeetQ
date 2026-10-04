import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { mockFetch, type FetchCall } from "../admin/test-utils";
import { SessionProvider } from "../state/session";
import { AuthProvider } from "./AuthProvider";

const USER = {
  user: { id: "usr_1", email: "huy@example.com", name: "Nguyen Gia Huy", avatar_url: "https://example.com/a.png" },
};
const SIGNED_OUT = { status: 401, body: { error: { code: "auth_required", message: "Sign in required." } } };
const CONFIG = { room_meeting_duration_seconds: 1800, supported_languages: ["vi", "en", "ja"] };

let gisCallback: ((response: { credential?: string }) => void) | null = null;
const disableAutoSelect = vi.fn();

function installFakeGoogle() {
  window.google = {
    accounts: {
      id: {
        initialize: (config) => {
          gisCallback = config.callback;
        },
        renderButton: (parent) => {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = "Continue with Google";
          button.onclick = () => gisCallback?.({ credential: "google-id-token" });
          parent.appendChild(button);
        },
        disableAutoSelect,
        cancel: () => undefined,
      },
    },
  };
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <SessionProvider>
          <App />
          <LocationProbe />
        </SessionProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

function currentLocation() {
  return screen.getByTestId("location").textContent;
}

/** Backend double: Google sign-in creates the cookie session that /me reads. */
function backend({ googleStatus = 200, startSignedIn = false } = {}) {
  let signedIn = startSignedIn;
  const mock = mockFetch({
    "/api/auth/me": () => (signedIn ? { body: USER } : SIGNED_OUT),
    "/api/auth/google": () => {
      if (googleStatus !== 200) {
        return { status: googleStatus, body: { error: { code: "invalid_google_credential", message: "bad" } } };
      }
      signedIn = true;
      return { body: USER };
    },
    "/api/auth/logout": () => {
      signedIn = false;
      return { status: 204, body: null };
    },
    "/api/config": () => ({ body: CONFIG }),
  });
  return mock;
}

function paths(calls: FetchCall[]) {
  return calls.map((call) => call.path);
}

beforeEach(() => {
  vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com");
  // RoomPage reads media queries once the invited room opens.
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
  installFakeGoogle();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  delete window.google;
  gisCallback = null;
  window.localStorage.clear();
});

describe("protected user routes", () => {
  it("shows nothing protected while GET /api/auth/me runs", async () => {
    let release: () => void = () => undefined;
    mockFetch({
      "/api/auth/me": () => new Promise((resolve) => (release = () => resolve({ body: USER }))),
      "/api/config": () => ({ body: CONFIG }),
    });
    renderApp("/");
    expect(await screen.findByRole("status", { name: "Checking your sign-in" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
    release();
    expect(await screen.findByRole("button", { name: "Account: Nguyen Gia Huy" })).toBeInTheDocument();
  });

  it("keeps a room invite in next when the visitor is signed out", async () => {
    backend();
    renderApp("/rooms/rm_abc123");
    expect(await screen.findByRole("heading", { name: "Sign in to join the meeting" })).toBeInTheDocument();
    expect(currentLocation()).toBe("/login?next=%2Frooms%2Frm_abc123");
  });

  it("returns to the invited room after Google sign-in", async () => {
    const { calls } = backend();
    renderApp("/login?next=%2Frooms%2Frm_abc123");
    await userEvent.click(await screen.findByRole("button", { name: "Continue with Google" }));
    await waitFor(() => expect(currentLocation()).toBe("/rooms/rm_abc123"));

    const googleCall = calls.find((call) => call.path === "/api/auth/google");
    expect(JSON.parse(String(googleCall?.init?.body))).toEqual({ credential: "google-id-token" });
    expect(googleCall?.init?.credentials).toBe("include");
    // The session is confirmed with /me after the credential exchange.
    const order = paths(calls);
    expect(order.lastIndexOf("/api/auth/me")).toBeGreaterThan(order.indexOf("/api/auth/google"));
  });

  it("does not trust the Google credential when the backend rejects it", async () => {
    backend({ googleStatus: 401 });
    renderApp("/login");
    await userEvent.click(await screen.findByRole("button", { name: "Continue with Google" }));
    expect(await screen.findByText("Google sign-in couldn't be verified. Try again.")).toBeInTheDocument();
    expect(currentLocation()).toBe("/login");
  });

  it("reports a session that the browser did not keep", async () => {
    mockFetch({
      "/api/auth/me": () => SIGNED_OUT,
      "/api/auth/google": () => ({ body: USER }), // accepted, but no cookie session follows
    });
    renderApp("/login");
    await userEvent.click(await screen.findByRole("button", { name: "Continue with Google" }));
    expect(await screen.findByText(/couldn't keep you signed in/)).toBeInTheDocument();
    expect(currentLocation()).toBe("/login");
  });

  it("ignores external next targets", async () => {
    backend();
    renderApp("/login?next=https%3A%2F%2Fevil.com");
    await userEvent.click(await screen.findByRole("button", { name: "Continue with Google" }));
    await waitFor(() => expect(currentLocation()).toBe("/"));
  });

  it("signs out through POST /api/auth/logout and returns to /login", async () => {
    const { calls } = backend({ startSignedIn: true });
    renderApp("/");
    await userEvent.click(await screen.findByRole("button", { name: "Account: Nguyen Gia Huy" }));
    expect(screen.getByText("huy@example.com")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(currentLocation()).toBe("/login"));
    expect(paths(calls)).toContain("/api/auth/logout");
    expect(paths(calls)).not.toContain("/api/admin/auth/logout");
    expect(disableAutoSelect).toHaveBeenCalled();
  });

  it("sends the user to /login when an API reports the session ended", async () => {
    let meCalls = 0;
    mockFetch({
      "/api/auth/me": () => (++meCalls === 1 ? { body: USER } : SIGNED_OUT),
      "/api/config": () => ({ status: 401, body: { error: { code: "session_expired", message: "expired" } } }),
    });
    renderApp("/");
    expect(await screen.findByText("Your session ended. Sign in again to continue.")).toBeInTheDocument();
    expect(currentLocation()).toBe("/login");
  });

  it("shows a configuration error instead of a broken button without a client ID", async () => {
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "");
    backend();
    renderApp("/login");
    expect(await screen.findByText(/VITE_GOOGLE_CLIENT_ID is missing/)).toBeInTheDocument();
  });
});

describe("user and admin realms are separate", () => {
  it("a Google-signed-in user still needs an admin session for /admin", async () => {
    const { calls } = backend({ startSignedIn: true });
    renderApp("/admin");
    expect(await screen.findByLabelText("Username")).toBeInTheDocument();
    expect(paths(calls)).toContain("/api/admin/auth/me");
    expect(paths(calls)).not.toContain("/api/auth/me"); // admin pages don't consult the user session
  });

  it("admin 401s never sign the user out", async () => {
    backend({ startSignedIn: true });
    renderApp("/");
    expect(await screen.findByRole("button", { name: "Account: Nguyen Gia Huy" })).toBeInTheDocument();
    // Simulate an admin API rejecting the (absent) admin session.
    const { requestJson } = await import("../lib/api");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ error: { code: "auth_required", message: "x" } }), { status: 401 })),
    );
    await expect(requestJson("/api/admin/overview")).rejects.toThrow();
    expect(screen.getByRole("button", { name: "Account: Nguyen Gia Huy" })).toBeInTheDocument();
  });
});

describe("lobby name", () => {
  it("pre-fills the Google name and remembers a different name per account", async () => {
    const { loadUserPrefs, saveUserPrefs } = await import("../lib/userPrefs");
    saveUserPrefs("Nguyen Gia Huy", "vi", "usr_1", "Nguyen Gia Huy");
    expect(loadUserPrefs("usr_1").displayName).toBe(""); // falls back to the Google name
    saveUserPrefs("Huy (BrSE)", "vi", "usr_1", "Nguyen Gia Huy");
    expect(loadUserPrefs("usr_1").displayName).toBe("Huy (BrSE)");
    expect(loadUserPrefs("usr_2").displayName).toBe("");
  });
});
