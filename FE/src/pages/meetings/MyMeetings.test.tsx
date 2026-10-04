import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch } from "../../admin/test-utils";
import { AuthProvider } from "../../auth/AuthProvider";
import { JoinRoomCard } from "../../components/JoinRoomCard";
import type { RoomSnapshotResponse } from "../../types/api";
import { MyMeetingDetailPage } from "./MyMeetingDetailPage";
import { MyMeetingsPage } from "./MyMeetingsPage";

const EXPIRES = new Date(Date.now() + 6 * 86_400_000 + 3_600_000).toISOString();
const MEETING = {
  room_id: "rm_abc123",
  archive_id: "arc_abc123",
  status: "ready",
  room_languages: ["vi", "ja"],
  meeting_started_at: "2026-10-04T08:00:00Z",
  ended_at: "2026-10-04T08:28:00Z",
  duration_seconds: 1680,
  participant_count: 2,
  recording: { status: "ready", count: 1, ready: 1, failed: 0, pending: 0, total_bytes: 184_000_000, total_duration_seconds: 1722 },
  expires_at: EXPIRES,
  retention_days: 7,
};
const RECORDING = {
  recording_id: "rec_1",
  room_id: "rm_abc123",
  archive_id: "arc_abc123",
  status: "ready",
  requested_at: "2026-10-04T08:01:00Z",
  started_at: "2026-10-04T08:01:02Z",
  stopped_at: "2026-10-04T08:29:44Z",
  duration_seconds: 1722,
  size_bytes: 184_000_000,
  started_by: { participant_id: "pt_1", display_name: "Huy" },
  error_code: null,
  version: 5,
  playable: true,
};

afterEach(() => vi.unstubAllGlobals());

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="/meetings" element={<MyMeetingsPage />} />
          <Route path="/meetings/:roomId" element={<MyMeetingDetailPage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("My meetings", () => {
  it("lists meetings with recording status and expiry", async () => {
    mockFetch({ "/api/meetings": () => ({ body: { items: [MEETING], total: 1, page: 1, page_size: 20 } }) });
    renderAt("/meetings");
    expect(await screen.findByRole("link", { name: /Vietnamese.*Japanese/ })).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("6 days")).toBeInTheDocument();
    expect(screen.getByText("28 min")).toBeInTheDocument();
  });

  it("plays a ready recording with a freshly signed URL and shows the expiry", async () => {
    const { calls } = mockFetch({
      "/api/meetings/rm_abc123": () => ({
        body: { meeting: MEETING, recordings: [RECORDING], participants: [], counts: { transcript: 0, relay: 0, chat: 0 }, summary: null },
      }),
      "/api/recordings/rec_1/playback-url": () => ({ body: { url: "https://s3.example/signed.mp4?X-Amz-Expires=600", expires_in: 600 } }),
    });
    const { container } = renderAt("/meetings/rm_abc123");
    expect(await screen.findByText(/Available until/)).toHaveTextContent("expires in 6 days");
    expect(container.querySelector("video")).toBeNull(); // no player until asked
    await userEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(container.querySelector("video")?.getAttribute("src")).toBe("https://s3.example/signed.mp4?X-Amz-Expires=600");
    expect(calls.find((call) => call.path.endsWith("/playback-url"))?.init?.method).toBe("POST");
  });

  it("shows a processing state instead of a broken player", async () => {
    mockFetch({
      "/api/meetings/rm_abc123": () => ({
        body: {
          meeting: MEETING,
          recordings: [{ ...RECORDING, status: "processing", playable: false }],
          participants: [],
          counts: { transcript: 0, relay: 0, chat: 0 },
          summary: null,
        },
      }),
    });
    renderAt("/meetings/rm_abc123");
    expect(await screen.findByText("Recording is being prepared.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Play" })).not.toBeInTheDocument();
  });

  it("explains an expired meeting", async () => {
    mockFetch({
      "/api/meetings/rm_gone": () => ({ status: 410, body: { error: { code: "meeting_archive_deleted", message: "deleted" } } }),
    });
    renderAt("/meetings/rm_gone");
    expect(await screen.findByText("This meeting has expired")).toBeInTheDocument();
  });
});

describe("Lobby", () => {
  it("warns that the meeting is being recorded before joining", async () => {
    mockFetch({ "/api/auth/me": () => ({ status: 401, body: { error: { code: "auth_required", message: "x" } } }) });
    const room = {
      room_id: "rm_abc123",
      state: "active",
      created_at: "2026-10-04T08:00:00Z",
      expires_at: new Date(Date.now() + 1_800_000).toISOString(),
      room_languages: ["vi", "ja"],
      meeting_languages: ["vi", "ja"],
      participant_count: 1,
      recording: { ...RECORDING, status: "recording", playable: undefined },
    } as unknown as RoomSnapshotResponse["room"];
    render(
      <MemoryRouter>
        <AuthProvider>
          <JoinRoomCard
            room={room}
            participants={[]}
            meetingLanguages={["vi", "ja"]}
            isExpired={false}
            onJoin={async () => undefined}
            isSubmitting={false}
            error={null}
          />
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(screen.getByText("This meeting is being recorded.")).toBeInTheDocument();
  });
});
