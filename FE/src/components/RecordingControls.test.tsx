import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { activeRecording, mergeRecording, noticeForEvent } from "../features/room/useRoomRecording";
import type { RecordingState } from "../types/recording";
import type { RecordingEvent } from "../types/ws";
import { RecordButton, RecordingIndicator } from "./RecordingControls";

function rec(overrides: Partial<RecordingState> = {}): RecordingState {
  return {
    recording_id: "rec_1",
    room_id: "rm_1",
    archive_id: "arc_1",
    status: "recording",
    requested_at: "2026-10-04T10:00:00Z",
    started_at: new Date(Date.now() - 754_000).toISOString(),
    stopped_at: null,
    duration_seconds: null,
    size_bytes: null,
    started_by: { participant_id: "pt_huy", display_name: "Huy" },
    error_code: null,
    version: 2,
    ...overrides,
  };
}

function event(type: RecordingEvent["type"], recording: RecordingState): RecordingEvent {
  return { type, room_id: recording.room_id, payload: { recording } } as RecordingEvent;
}

describe("room recording state", () => {
  it("every client converges on the highest server version", () => {
    let state = mergeRecording({}, rec({ status: "stopping", version: 4 }));
    state = mergeRecording(state, rec({ status: "recording", version: 3 })); // late, older event
    expect(state.rec_1.status).toBe("stopping");
    state = mergeRecording(state, rec({ status: "processing", version: 5 }));
    expect(activeRecording(state)).toBeNull(); // indicator off once processing
  });

  it("follows the newest active segment", () => {
    let state = mergeRecording({}, rec({ recording_id: "rec_old", status: "ready", version: 9 }));
    state = mergeRecording(state, rec({ recording_id: "rec_new", requested_at: "2026-10-04T11:00:00Z", status: "starting", version: 1 }));
    expect(activeRecording(state)?.recording_id).toBe("rec_new");
  });

  it("announces start (with who), stop and failure to the room", () => {
    expect(noticeForEvent(event("recording.started", rec()), rec({ status: "starting" }))?.message).toBe("Recording started by Huy.");
    expect(noticeForEvent(event("recording.stopped", rec({ status: "processing" })), rec())?.message).toBe("Recording stopped.");
    expect(noticeForEvent(event("recording.failed", rec({ status: "failed" })), rec())?.message).toMatch(/Recording failed/);
    expect(noticeForEvent(event("recording.processing", rec({ status: "processing" })), rec())).toBeNull();
  });
});

describe("RecordingIndicator", () => {
  it("is permanent with elapsed time while recording", () => {
    render(<RecordingIndicator recording={rec()} />);
    expect(screen.getByRole("status")).toHaveTextContent(/REC\s*12:3\d/);
  });

  it("shows starting and stopping states", () => {
    const { rerender } = render(<RecordingIndicator recording={rec({ status: "starting", started_at: null })} />);
    expect(screen.getByText("Starting recording…")).toBeInTheDocument();
    rerender(<RecordingIndicator recording={rec({ status: "stopping" })} />);
    expect(screen.getByText("Stopping recording…")).toBeInTheDocument();
    rerender(<RecordingIndicator recording={null} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("RecordButton", () => {
  it("asks for confirmation before starting", async () => {
    const onStart = vi.fn();
    render(<RecordButton recording={null} isStarting={false} isStopping={false} onStart={onStart} onStop={() => undefined} />);
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    expect(screen.getByRole("alertdialog", { name: "Start recording?" })).toHaveTextContent(
      "Everyone in this meeting will be notified that recording has started.",
    );
    expect(onStart).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onStart).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    await userEvent.click(screen.getByRole("button", { name: "Start recording" }));
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("stops without a dialog and shows busy states", async () => {
    const onStop = vi.fn();
    const { rerender } = render(
      <RecordButton recording={rec()} isStarting={false} isStopping={false} onStart={() => undefined} onStop={onStop} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Stop recording" }));
    expect(onStop).toHaveBeenCalledTimes(1);
    rerender(<RecordButton recording={rec({ status: "stopping" })} isStarting={false} isStopping onStart={() => undefined} onStop={onStop} />);
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();
  });
});
