import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HEALTHY_SYSTEM, liveRoom, mockFetch, renderAdmin, seedAdminSession } from "../test-utils";

function roomsResponse(items: unknown[], extra: Record<string, unknown> = {}) {
  return {
    items,
    page: 1,
    page_size: 25,
    total: items.length,
    counts_by_status: { live: items.length, empty: 0, error: 0, expired: 0 },
    runtime_online: true,
    ...extra,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Live Rooms page", () => {
  it("shows a loading state, then the rooms table", async () => {
    seedAdminSession();
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    mockFetch({
      "/api/admin/health": () => ({ body: HEALTHY_SYSTEM }),
      "/api/admin/rooms": async () => {
        await gate;
        return { body: roomsResponse([liveRoom()]) };
      },
    });

    renderAdmin("/admin/live-rooms");
    expect(await screen.findByRole("status", { name: "Loading" })).toBeInTheDocument();

    release();
    const link = await screen.findByRole("link", { name: "rm_abc123" });
    expect(link).toHaveAttribute("href", "/admin/live-rooms/rm_abc123");
    expect(screen.getByText("Voice + Text")).toBeInTheDocument();
    expect(screen.getByText("Translating")).toBeInTheDocument();
    expect(screen.getByText("VI ⇄ JA")).toBeInTheDocument();
  });

  it("shows the empty state when no room exists", async () => {
    seedAdminSession();
    mockFetch({
      "/api/admin/health": () => ({ body: HEALTHY_SYSTEM }),
      "/api/admin/rooms": () => ({ body: roomsResponse([]) }),
    });
    renderAdmin("/admin/live-rooms");
    expect(await screen.findByText("No rooms right now")).toBeInTheDocument();
  });

  it("shows an error state with retry when the API fails", async () => {
    seedAdminSession();
    let failing = true;
    mockFetch({
      "/api/admin/health": () => ({ body: HEALTHY_SYSTEM }),
      "/api/admin/rooms": () =>
        failing
          ? { status: 503, body: { error: { code: "service_unavailable", message: "Gateway is not initialized." } } }
          : { body: roomsResponse([liveRoom()]) },
    });
    renderAdmin("/admin/live-rooms");

    expect(await screen.findByText("Couldn't load this data")).toBeInTheDocument();
    expect(screen.getByText("Gateway is not initialized.")).toBeInTheDocument();

    failing = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "rm_abc123" })).toBeInTheDocument();
  });

  it("sends the selected filter to the API", async () => {
    seedAdminSession();
    const { calls } = mockFetch({
      "/api/admin/health": () => ({ body: HEALTHY_SYSTEM }),
      "/api/admin/rooms": ({ params }) => ({
        body: roomsResponse(params.get("language") === "en" ? [] : [liveRoom()]),
      }),
    });
    renderAdmin("/admin/live-rooms");
    await screen.findByRole("link", { name: "rm_abc123" });

    await userEvent.click(screen.getByRole("button", { name: "Language" }));
    await userEvent.click(await screen.findByRole("option", { name: "English" }));

    await waitFor(() => {
      expect(calls.some((call) => call.path === "/api/admin/rooms" && call.params.get("language") === "en")).toBe(true);
    });
    expect(await screen.findByText("No rooms match these filters")).toBeInTheDocument();
  });

  it("uses the admin cookie session, not a bearer token", async () => {
    seedAdminSession();
    const { calls } = mockFetch({
      "/api/admin/health": () => ({ body: HEALTHY_SYSTEM }),
      "/api/admin/rooms": () => ({ body: roomsResponse([]) }),
    });
    renderAdmin("/admin/live-rooms");
    await screen.findByText("No rooms right now");
    const call = calls.find((item) => item.path === "/api/admin/rooms");
    expect(call?.init?.credentials).toBe("include");
    expect((call?.init?.headers as Record<string, string>).Authorization).toBeUndefined();
  });
});
