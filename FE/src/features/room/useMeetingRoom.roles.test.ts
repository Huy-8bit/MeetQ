import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RoomSession } from "../../state/session";

const fakeRoom = { localParticipant: {} };
const gatewayHandlers: { onEvent: ((event: unknown) => void) | null } = { onEvent: null };

vi.mock("../../lib/livekit", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/livekit")>();
  return {
    ...actual,
    createMeetingRoom: vi.fn(() => fakeRoom),
    connectLiveKit: vi.fn(async () => undefined),
    publishLocalMedia: vi.fn(async () => []),
    bindRoomRefresh: vi.fn(() => () => undefined),
    buildMediaSnapshot: vi.fn(() => ({ videos: [], humanAudio: [], brseAudio: [], screenShares: [] })),
    getLocalMicrophoneTrack: vi.fn(() => null),
    getLocalCameraTrack: vi.fn(() => null),
    enumerateAudioDevices: vi.fn(async () => ({ audioInputs: [], audioOutputs: [] })),
    disconnectRoom: vi.fn(),
    isScreenShareSupported: vi.fn(() => true),
    publishScreenShareTrack: vi.fn(),
    unpublishScreenShareTrack: vi.fn(),
  };
});

vi.mock("../../lib/ws", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/ws")>();
  return {
    ...actual,
    retainGatewaySocket: vi.fn(() => ({
      subscribe: (handlers: { onEvent: (event: unknown) => void }) => {
        gatewayHandlers.onEvent = handlers.onEvent;
        return () => undefined;
      },
      connect: async () => undefined,
      disconnect: () => undefined,
      disconnectForUnload: () => undefined,
      sendScreenShareStop: () => undefined,
    })),
    releaseGatewaySocket: vi.fn(),
  };
});

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return {
    ...actual,
    leaveRoomBestEffort: vi.fn(),
    api: {
      ...actual.api,
      getRoomSummary: vi.fn(() => new Promise(() => undefined)),
      startScreenShare: vi.fn(async () => ({
        active: true,
        track_sid: "TR_video",
        track_name: "screen",
        timestamp: "2026-10-05T00:00:00Z",
      })),
      stopScreenShare: vi.fn(async () => ({ active: false, timestamp: "2026-10-05T00:00:01Z" })),
      leaveRoom: vi.fn(async () => undefined),
    },
  };
});

vi.mock("../../lib/audioOutput", () => ({
  setRoomAudioOutputDevice: vi.fn(async () => undefined),
}));

const livekit = await import("../../lib/livekit");
const { api } = await import("../../lib/api");
const { useMeetingRoom } = await import("./useMeetingRoom");

function makeSession(): RoomSession {
  const participant = {
    participant_id: "p1",
    session_id: "s1",
    display_name: "Alice",
    language: "en",
  };
  return {
    sessionKey: "room1::p1::s1::ws",
    roomId: "room1",
    roomToken: "room-token",
    roomTokenExpiresAt: "2099-01-01T00:00:00Z",
    websocketUrl: "ws://localhost/ws",
    livekit: {
      url: "ws://localhost:7880",
      room_name: "room1",
      participant_identity: "p1",
      participant_name: "Alice",
      token: "lk-token",
    },
    participant,
    room: {
      room_id: "room1",
      state: "active",
      created_at: "2026-10-05T00:00:00Z",
      expires_at: "2099-01-01T00:00:00Z",
      participant_limit: 10,
      supported_languages: ["en", "ja"],
      room_languages: ["en", "ja"],
    },
    snapshot: {
      participants: [{ ...participant, status: "connected" }],
      recent_transcripts: [],
      recent_messages: [],
    },
  } as unknown as RoomSession;
}


function envelope(type: string, payload: Record<string, unknown>) {
  return { type, event_id: `evt_${type}`, room_id: "room1", sent_at: "2026-10-05T00:00:00Z", payload };
}

function snapshot(selfRole: string) {
  return envelope("room.snapshot", {
    self: { participant_id: "p1", session_id: "s1", display_name: "Alice", language: "en", role: selfRole, permissions_enforced: true },
    room: { state: "active", expires_at: "2099-01-01T00:00:00Z", room_languages: ["en", "ja"], supported_languages: ["en", "ja"], participant_limit: null },
    participants: [
      { participant_id: "p1", display_name: "Alice", language: "en", status: "connected", role: selfRole },
      { participant_id: "p2", display_name: "Bob", language: "ja", status: "connected", role: "host" },
    ],
    recent_transcripts: [],
  });
}

function renderMeeting(onSessionInvalidated = vi.fn()) {
  const session = makeSession();
  const view = renderHook(() =>
    useMeetingRoom({ roomId: "room1", initialRoom: null, session, onSessionInvalidated }),
  );
  return { ...view, onSessionInvalidated };
}

function emit(event: unknown) {
  act(() => {
    gatewayHandlers.onEvent?.(event);
  });
}

describe("useMeetingRoom roles (server-driven)", () => {
  it("takes the role from the server snapshot and updates it live", async () => {
    const { result } = renderMeeting();
    await waitFor(() => expect(gatewayHandlers.onEvent).not.toBeNull());
    emit(snapshot("participant"));
    expect(result.current.selfRole).toBe("participant");
    expect(result.current.permissions.can_manage_ai).toBe(false);
    expect(result.current.hostParticipantId).toBe("p2");

    emit(
      envelope("participant.role_changed", {
        room_id: "room1",
        participant_id: "p1",
        participant_ids: ["p1"],
        old_role: "participant",
        new_role: "co_host",
        changed_by: "p2",
        changed_by_name: "Bob",
        changed_at: "2026-10-05T00:00:01Z",
      }),
    );
    expect(result.current.selfRole).toBe("co_host");
    expect(result.current.permissions.can_manage_recording).toBe(true);
    expect(result.current.permissions.can_manage_password).toBe(false);
    expect(result.current.roleNotice).toMatch(/Bob made you a co-host/);
    expect(result.current.participants.find((p) => p.participant_id === "p1")?.role).toBe("co_host");
  });

  it("follows the room lock and password state", async () => {
    const { result } = renderMeeting();
    await waitFor(() => expect(gatewayHandlers.onEvent).not.toBeNull());
    emit(snapshot("host"));
    emit(envelope("room.lock_changed", { room_id: "room1", locked: true, changed_by: "p1", changed_at: "x" }));
    expect(result.current.roomLocked).toBe(true);
    emit(envelope("room.access_updated", { room_id: "room1", password_required: true, changed_by: "p1", changed_at: "x" }));
    expect(result.current.passwordRequired).toBe(true);
  });

  it("leaves the meeting when the host removes you", async () => {
    const { result, onSessionInvalidated } = renderMeeting();
    await waitFor(() => expect(gatewayHandlers.onEvent).not.toBeNull());
    emit(snapshot("participant"));
    emit(envelope("participant.removed", { participant_id: "p2", removed_by: "Bob", removed_at: "x", reason: "removed_by_host" }));
    expect(result.current.removedFromMeeting).toBeNull();
    expect(result.current.participants.some((p) => p.participant_id === "p2")).toBe(false);
    emit(envelope("participant.removed", { participant_id: "p1", removed_by: "Bob", removed_at: "x", reason: "removed_by_host" }));
    expect(result.current.removedFromMeeting).toEqual({ by: "Bob" });
    expect(onSessionInvalidated).toHaveBeenCalled();
  });
});
