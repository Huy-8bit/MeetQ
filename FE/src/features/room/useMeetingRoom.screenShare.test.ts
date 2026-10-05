import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RoomSession } from "../../state/session";

const fakeRoom = { localParticipant: {} };

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
      subscribe: () => () => undefined,
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

function makePublished(options: { withAudio: boolean; audioUnavailable?: boolean; actualFps?: number }) {
  const video = { mediaStreamTrack: new EventTarget(), stop: vi.fn() };
  const audio = options.withAudio ? { mediaStreamTrack: new EventTarget(), stop: vi.fn() } : null;
  return {
    video,
    audio,
    published: {
      track: video,
      publication: {},
      audioTrack: audio,
      audioPublication: audio ? {} : null,
      audioUnavailable: options.audioUnavailable ?? false,
      quality: "motion",
      requested: { width: 1920, height: 1080, frameRate: 60 },
      actual: { width: 1920, height: 1080, frameRate: options.actualFps ?? 60 },
      trackSid: "TR_video",
      trackName: "screen",
    },
  };
}

function renderMeeting() {
  const session = makeSession();
  return renderHook(() =>
    useMeetingRoom({
      roomId: "room1",
      initialRoom: null,
      session,
      onSessionInvalidated: () => undefined,
    }),
  );
}

describe("useMeetingRoom screen share", () => {
  beforeEach(() => {
    vi.mocked(livekit.publishScreenShareTrack).mockReset();
    vi.mocked(livekit.unpublishScreenShareTrack).mockReset();
    vi.mocked(api.startScreenShare).mockClear();
    vi.mocked(api.stopScreenShare).mockClear();
  });

  it("passes the dialog choice to the capture and exposes canShareScreen", async () => {
    const { published } = makePublished({ withAudio: true });
    vi.mocked(livekit.publishScreenShareTrack).mockResolvedValue(published as never);
    const { result } = renderMeeting();
    expect(result.current.canShareScreen).toBe(true);

    await act(async () => {
      await result.current.startScreenShare({ quality: "motion", includeAudio: true });
    });

    expect(livekit.publishScreenShareTrack).toHaveBeenCalledWith(fakeRoom, { quality: "motion", includeAudio: true });
    expect(result.current.isScreenSharing).toBe(true);
    expect(result.current.screenShareError).toBeNull();
    expect(result.current.screenShareNotice).toBeNull();
  });

  it("stopping from the browser's native control removes video and audio, with no error", async () => {
    const { published, video, audio } = makePublished({ withAudio: true });
    vi.mocked(livekit.publishScreenShareTrack).mockResolvedValue(published as never);
    const { result } = renderMeeting();
    await act(async () => {
      await result.current.startScreenShare({ quality: "detail", includeAudio: true });
    });

    act(() => {
      video.mediaStreamTrack.dispatchEvent(new Event("ended"));
    });

    await waitFor(() => expect(result.current.isScreenSharing).toBe(false));
    expect(livekit.unpublishScreenShareTrack).toHaveBeenCalledWith(fakeRoom, video, audio);
    expect(api.stopScreenShare).toHaveBeenCalledWith("room1", "room-token");
    expect(result.current.screenShareError).toBeNull();
  });

  it("when only the shared audio ends, keeps the screen and drops the audio", async () => {
    const { published, video, audio } = makePublished({ withAudio: true });
    vi.mocked(livekit.publishScreenShareTrack).mockResolvedValue(published as never);
    const { result } = renderMeeting();
    await act(async () => {
      await result.current.startScreenShare({ quality: "detail", includeAudio: true });
    });

    act(() => {
      audio!.mediaStreamTrack.dispatchEvent(new Event("ended"));
    });

    expect(livekit.unpublishScreenShareTrack).toHaveBeenCalledWith(fakeRoom, null, audio);
    expect(result.current.isScreenSharing).toBe(true);
    expect(api.stopScreenShare).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.stopScreenShare({ reason: "manual_stop" });
    });
    expect(livekit.unpublishScreenShareTrack).toHaveBeenLastCalledWith(fakeRoom, video, null);
  });

  it("shows nothing when the user closes the picker", async () => {
    vi.mocked(livekit.publishScreenShareTrack).mockRejectedValue(new livekit.ScreenShareCancelledError());
    const { result } = renderMeeting();

    await act(async () => {
      await result.current.startScreenShare({ quality: "detail", includeAudio: false });
    });

    expect(result.current.screenShareError).toBeNull();
    expect(result.current.isScreenSharing).toBe(false);
    expect(api.startScreenShare).not.toHaveBeenCalled();
  });

  it("explains unsupported devices and real failures", async () => {
    vi.mocked(livekit.publishScreenShareTrack).mockRejectedValueOnce(new livekit.ScreenShareUnsupportedError());
    const { result } = renderMeeting();

    await act(async () => {
      await result.current.startScreenShare({ quality: "detail", includeAudio: false });
    });
    expect(result.current.screenShareError).toBe("Screen sharing isn't supported on this device.");

    vi.mocked(livekit.publishScreenShareTrack).mockRejectedValueOnce(
      new DOMException("Could not start video source", "NotReadableError"),
    );
    await act(async () => {
      await result.current.startScreenShare({ quality: "detail", includeAudio: false });
    });
    expect(result.current.screenShareError).toBe("Could not start screen sharing.");
  });

  it("warns when shared audio is unavailable or the frame rate is lower than asked", async () => {
    const { published } = makePublished({ withAudio: false, audioUnavailable: true, actualFps: 30 });
    vi.mocked(livekit.publishScreenShareTrack).mockResolvedValue(published as never);
    const { result } = renderMeeting();

    await act(async () => {
      await result.current.startScreenShare({ quality: "motion", includeAudio: true });
    });

    expect(result.current.isScreenSharing).toBe(true);
    expect(result.current.screenShareNotice).toBe(
      "Screen sharing started, but shared audio isn't available for this source or browser. "
        + "Your browser is capturing at up to 30 FPS (60 FPS requested).",
    );

    await act(async () => {
      await result.current.stopScreenShare({ reason: "manual_stop" });
    });
    expect(result.current.screenShareNotice).toBeNull();
  });
});
