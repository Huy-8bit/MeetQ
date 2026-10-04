import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HEALTHY_SYSTEM, mockFetch, renderAdmin, seedAdminSession } from "../test-utils";

const ARCHIVE = {
  archive_id: "arc_abc123",
  room_id: "rm_abc123",
  status: "ready",
  storage: "s3",
  room_languages: ["vi", "ja"],
  meeting_started_at: "2026-09-29T08:00:00Z",
  ended_at: "2026-09-29T08:30:00Z",
  participant_count: 2,
  recording: { status: "ready", count: 1, ready: 1, failed: 0, pending: 0, total_bytes: 184_000_000, total_duration_seconds: 1722 },
  retention_days: 7,
  retention_source: "default",
  default_retention_days_snapshot: 7,
  retention_override_days: null,
  expires_at: "2026-10-06T08:30:00Z",
  created_at: "2026-09-29T08:01:00Z",
  finalized_at: "2026-09-29T08:35:00Z",
  deleted_at: null,
  deletion_reason: null,
  error_code: null,
};
const DETAIL = {
  archive: ARCHIVE,
  recordings: [
    {
      recording_id: "rec_1",
      status: "ready",
      requested_at: "2026-09-29T08:01:00Z",
      started_at: "2026-09-29T08:01:02Z",
      stopped_at: "2026-09-29T08:29:44Z",
      duration_seconds: 1722,
      size_bytes: 184_000_000,
      started_by: { participant_id: "pt_1", display_name: "Huy" },
      stop_reason: "user_stopped",
      error_code: null,
      s3_key: "meetings/rm_abc123/arc_abc123/recordings/rec_1.mp4",
      provider_recording_id: "EG_1",
    },
  ],
  files: [{ name: "manifest", key: "meetings/rm_abc123/arc_abc123/manifest.json", size: 900 }],
  s3_bucket: "meetq-prod-meeting-archive",
  s3_prefix: "meetings/rm_abc123/arc_abc123/",
  system_default_retention_days: 7,
  storage_bytes: 184_000_900,
};

afterEach(() => vi.unstubAllGlobals());

describe("admin archive detail", () => {
  it("warns before a retention change that expires the meeting immediately", async () => {
    seedAdminSession();
    const bodies: unknown[] = [];
    const { calls } = mockFetch({
      "/api/admin/health": () => ({ body: HEALTHY_SYSTEM }),
      "/api/admin/archives/arc_abc123": () => ({ body: DETAIL }),
      "/api/admin/archives/arc_abc123/retention": (call) => {
        const body = JSON.parse(String(call.init?.body));
        bodies.push(body);
        if (!body.confirm_expire) {
          return { status: 409, body: { error: { code: "retention_expires_immediately", message: "x", details: { expires_at: "2026-10-02T08:30:00Z" } } } };
        }
        return { body: { archive: { ...ARCHIVE, retention_days: 3, retention_source: "custom" } } };
      },
    });
    renderAdmin("/admin/recordings/arc_abc123");
    expect(await screen.findByText("184 MB")).toBeInTheDocument();
    const input = screen.getByLabelText("Retention (days)");
    await userEvent.clear(input);
    await userEvent.type(input, "3");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Expire this meeting now?" });
    expect(dialog).toHaveTextContent("already older than the new retention period");
    await userEvent.click(within(dialog).getByRole("button", { name: "Apply and expire" }));
    expect(bodies).toEqual([{ retention_days: 3 }, { retention_days: 3, confirm_expire: true }]);
    expect(calls.filter((c) => c.path.endsWith("/retention")).every((c) => c.init?.method === "PATCH")).toBe(true);
  });

  it("deletes only after typing DELETE", async () => {
    seedAdminSession();
    const { calls } = mockFetch({
      "/api/admin/health": () => ({ body: HEALTHY_SYSTEM }),
      "/api/admin/archives/arc_abc123": (call) =>
        call.init?.method === "DELETE"
          ? { body: { archive: { ...ARCHIVE, status: "deleted" } } }
          : { body: DETAIL },
    });
    renderAdmin("/admin/recordings/arc_abc123");
    await userEvent.click(await screen.findByRole("button", { name: "Delete now" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete meeting archive?" });
    expect(dialog).toHaveTextContent("This action cannot be undone.");
    const confirm = within(dialog).getByRole("button", { name: "Delete permanently" });
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Type DELETE to confirm"), "delete");
    expect(confirm).toBeDisabled();
    await userEvent.clear(within(dialog).getByLabelText("Type DELETE to confirm"));
    await userEvent.type(within(dialog).getByLabelText("Type DELETE to confirm"), "DELETE");
    await userEvent.click(confirm);
    const deleteCall = calls.find((c) => c.init?.method === "DELETE");
    expect(JSON.parse(String(deleteCall?.init?.body))).toEqual({ confirm: "DELETE" });
  });
});
