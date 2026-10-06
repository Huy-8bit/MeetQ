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

const DETAIL = (overrides: Record<string, unknown> = {}) => ({
  meeting: { ...MEETING, title: "Vikki Lending Weekly", host: "Huy", co_hosts: ["Kenji"], summary_status: "completed" },
  recordings: [RECORDING],
  participants: [],
  counts: { transcript: 2, relay: 0, chat: 0 },
  summary: null,
  ...overrides,
});

describe("My meetings", () => {
  it("lists meetings as cards with a title fallback, recording status and expiry", async () => {
    mockFetch({
      "/api/meetings": () => ({
        body: { items: [{ ...MEETING, my_role: "host", summary_status: "completed" }], total: 1, page: 1, page_size: 20 },
      }),
    });
    renderAt("/meetings");
    expect(await screen.findByRole("link", { name: /Vietnamese.*Japanese meeting/ })).toBeInTheDocument();
    expect(screen.getByText("Recording available")).toBeInTheDocument();
    expect(screen.getByText("Summary ready")).toBeInTheDocument();
    expect(screen.getByText("Host")).toBeInTheDocument();
    expect(screen.getByText(/6 days left/)).toBeInTheDocument();
    expect(screen.getByText(/28 min · 2 participants/)).toBeInTheDocument();
  });

  it("filters and searches on the server, debounced, and shows content matches", async () => {
    const { calls } = mockFetch({
      "/api/meetings": () => ({ body: { items: [MEETING], total: 1, page: 1, page_size: 20 } }),
      "/api/meetings/search": () => ({
        body: {
          items: [
            {
              meeting_id: "rm_abc123",
              meeting_title: "Vikki Lending Weekly",
              source_type: "chat",
              section: null,
              timestamp: "2026-10-04T08:16:00Z",
              speaker: "Kenji",
              language: "vi",
              text: "Production deployment <b>after</b> test",
              highlights: [[0, 10]],
              source_item_id: "msg_1",
              cursor: "abc",
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
          query: "production",
        },
      }),
    });
    renderAt("/meetings");
    await screen.findByRole("link", { name: /Vietnamese/ });
    await userEvent.click(screen.getByRole("radio", { name: "Recorded" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Search meetings" }), "production");
    expect(await screen.findByText("1 result")).toBeInTheDocument();
    const listCalls = calls.filter((call) => call.path === "/api/meetings");
    expect(listCalls.some((call) => call.params.get("filter") === "recorded")).toBe(true);
    // One request after the pause, not one per keystroke.
    const withQuery = listCalls.filter((call) => call.params.get("q"));
    expect(withQuery.map((call) => call.params.get("q"))).toEqual(["production"]);
    // Highlights are plain text: markup in a snippet is shown, never interpreted.
    expect(screen.getByText("Production").tagName).toBe("MARK");
    expect(screen.getByText(/<b>after<\/b> test/)).toBeInTheDocument();
  });

  it("opens on the overview with hosts, then plays a recording with a freshly signed URL", async () => {
    const { calls } = mockFetch({
      "/api/meetings/rm_abc123": () => ({ body: DETAIL() }),
      "/api/recordings/rec_1/playback-url": () => ({ body: { url: "https://s3.example/signed.mp4?X-Amz-Expires=600", expires_in: 600 } }),
    });
    const { container } = renderAt("/meetings/rm_abc123");
    expect(await screen.findByRole("heading", { name: "Vikki Lending Weekly" })).toBeInTheDocument();
    expect(screen.getByText(/Available until Oct/, { selector: "div, p" })).toHaveTextContent("expires in 6 days");
    expect(screen.getByText("Kenji")).toBeInTheDocument(); // co-host in the overview
    await userEvent.click(screen.getByRole("radio", { name: "Recording" }));
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
    renderAt("/meetings/rm_abc123?tab=recording");
    expect(await screen.findByText("Recording is being prepared.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Play" })).not.toBeInTheDocument();
  });

  it("loads the full transcript page by page with the stored translations", async () => {
    const { calls } = mockFetch({
      "/api/meetings/rm_abc123": () => ({ body: DETAIL() }),
      "/api/meetings/rm_abc123/transcript": (call) =>
        call.params.get("cursor")
          ? {
              body: {
                items: [{ message_id: "s2", cursor: "c2", kind: "source", created_at: "2026-10-04T08:02:00Z", speaker_name: "Kenji", language: "ja", text: "了解です。", translations: [] }],
                next_cursor: null,
                prev_cursor: null,
              },
            }
          : {
              body: {
                items: [
                  {
                    message_id: "s1",
                    cursor: "c1",
                    kind: "source",
                    created_at: "2026-10-04T08:01:02Z",
                    speaker_name: "Huy",
                    language: "vi",
                    text: "Chúng ta sẽ deploy production tối nay.",
                    translations: [{ language: "ja", text: "今夜、本番環境にデプロイします。" }],
                  },
                ],
                next_cursor: "c1",
                prev_cursor: null,
              },
            },
    });
    renderAt("/meetings/rm_abc123?tab=transcript");
    expect(await screen.findByText("Chúng ta sẽ deploy production tối nay.")).toBeInTheDocument();
    expect(screen.getByText("今夜、本番環境にデプロイします。")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("了解です。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(calls.filter((call) => call.path.endsWith("/transcript")).map((call) => call.params.get("cursor"))).toEqual([null, "c1"]);
  });

  it("searches this meeting and jumps to the matching utterance", async () => {
    const { calls } = mockFetch({
      "/api/meetings/rm_abc123": () => ({ body: DETAIL() }),
      "/api/meetings/rm_abc123/search": () => ({
        body: {
          items: [
            {
              meeting_id: "rm_abc123",
              meeting_title: null,
              source_type: "transcript",
              section: null,
              timestamp: "2026-10-04T08:01:02Z",
              speaker: "Huy",
              language: "vi",
              text: "Chúng ta sẽ deploy production tối nay.",
              highlights: [[19, 29]],
              source_item_id: "s1",
              cursor: "c1",
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
          query: "production",
        },
      }),
      "/api/meetings/rm_abc123/transcript": () => ({
        body: {
          items: [{ message_id: "s1", cursor: "c1", kind: "source", created_at: "2026-10-04T08:01:02Z", speaker_name: "Huy", language: "vi", text: "Chúng ta sẽ deploy production tối nay.", translations: [] }],
          next_cursor: null,
          prev_cursor: "c0",
        },
      }),
    });
    const { container } = renderAt("/meetings/rm_abc123");
    await screen.findByRole("heading", { name: "Vikki Lending Weekly" });
    await userEvent.type(screen.getByRole("searchbox", { name: "Search this meeting" }), "production");
    await userEvent.click(await screen.findByRole("button", { name: /Transcript.*Huy/ }));
    expect(await screen.findByRole("button", { name: "Load earlier" })).toBeInTheDocument();
    expect(calls.find((call) => call.path.endsWith("/transcript"))?.params.get("start")).toBe("c1");
    expect(container.querySelector('[data-item-id="s1"]')?.className).toContain("is-focused");
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
