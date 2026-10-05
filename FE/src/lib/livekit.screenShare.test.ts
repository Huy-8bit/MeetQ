import { Track, type LocalTrack, type Room } from "livekit-client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  publishScreenShareTrack,
  ScreenShareCancelledError,
  ScreenShareUnsupportedError,
  unpublishScreenShareTrack,
} from "./livekit";

class FakeMediaStreamTrack extends EventTarget {
  readonly id = Math.random().toString(36).slice(2);
  enabled = true;
  muted = false;
  readyState: "live" | "ended" = "live";
  contentHint = "";
  stop = vi.fn(() => {
    this.readyState = "ended";
  });

  constructor(
    readonly kind: "audio" | "video",
    private readonly settings: MediaTrackSettings = {},
  ) {
    super();
  }

  getSettings(): MediaTrackSettings {
    return { deviceId: this.id, ...this.settings };
  }

  getConstraints(): MediaTrackConstraints {
    return {};
  }

  applyConstraints(): Promise<void> {
    return Promise.resolve();
  }

  clone(): FakeMediaStreamTrack {
    return new FakeMediaStreamTrack(this.kind, this.settings);
  }
}

function fakeStream(tracks: FakeMediaStreamTrack[]) {
  return {
    getTracks: () => tracks,
    getVideoTracks: () => tracks.filter((track) => track.kind === "video"),
    getAudioTracks: () => tracks.filter((track) => track.kind === "audio"),
  } as unknown as MediaStream;
}

function fakeRoom() {
  let sid = 0;
  const publishTrack = vi.fn(async (track: LocalTrack, options?: { source?: Track.Source }) => ({
    trackSid: `TR_${++sid}`,
    trackName: `${options?.source ?? track.source}`,
    source: options?.source ?? track.source,
    track,
  }));
  const unpublishTrack = vi.fn();
  const room = { localParticipant: { publishTrack, unpublishTrack } } as unknown as Room;
  return { room, publishTrack, unpublishTrack };
}

const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");

// jsdom has no MediaStream; livekit-client builds one around each local track.
class FakeMediaStream {
  private tracks: MediaStreamTrack[];

  constructor(tracks: MediaStreamTrack[] = []) {
    this.tracks = [...tracks];
  }

  getTracks() {
    return this.tracks;
  }

  getAudioTracks() {
    return this.tracks.filter((track) => track.kind === "audio");
  }

  getVideoTracks() {
    return this.tracks.filter((track) => track.kind === "video");
  }

  addTrack(track: MediaStreamTrack) {
    this.tracks.push(track);
  }

  removeTrack(track: MediaStreamTrack) {
    this.tracks = this.tracks.filter((item) => item !== track);
  }
}

beforeEach(() => {
  vi.stubGlobal("MediaStream", FakeMediaStream);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function setGetDisplayMedia(impl: ((options: DisplayMediaStreamOptions) => Promise<MediaStream>) | null) {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: impl ? { getDisplayMedia: vi.fn(impl) } : {},
  });
}

describe("publishScreenShareTrack", () => {
  beforeEach(() => {
    vi.spyOn(console, "debug").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    if (originalMediaDevices) {
      Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
    } else {
      delete (navigator as { mediaDevices?: unknown }).mediaDevices;
    }
  });

  it("throws ScreenShareUnsupportedError without getDisplayMedia", async () => {
    setGetDisplayMedia(null);
    const { room, publishTrack } = fakeRoom();
    await expect(publishScreenShareTrack(room)).rejects.toBeInstanceOf(ScreenShareUnsupportedError);
    expect(publishTrack).not.toHaveBeenCalled();
  });

  it("treats a closed picker as a cancel, not an error", async () => {
    setGetDisplayMedia(() => Promise.reject(new DOMException("Permission denied", "NotAllowedError")));
    const { room, publishTrack } = fakeRoom();
    await expect(publishScreenShareTrack(room)).rejects.toBeInstanceOf(ScreenShareCancelledError);
    expect(publishTrack).not.toHaveBeenCalled();
  });

  it("surfaces a real capture failure (OS-level block) as an error", async () => {
    setGetDisplayMedia(() => Promise.reject(new DOMException("Permission denied by system", "NotAllowedError")));
    const { room } = fakeRoom();
    const result = publishScreenShareTrack(room);
    await expect(result).rejects.not.toBeInstanceOf(ScreenShareCancelledError);
    await expect(result).rejects.toMatchObject({ name: "NotAllowedError" });
  });

  it("asks for 1080p at the profile frame rate with no upscaling", async () => {
    const video = new FakeMediaStreamTrack("video", { width: 1920, height: 1080, frameRate: 60 });
    setGetDisplayMedia(() => Promise.resolve(fakeStream([video])));
    const { room } = fakeRoom();

    const published = await publishScreenShareTrack(room, { quality: "motion" });

    const options = vi.mocked(navigator.mediaDevices.getDisplayMedia).mock.calls[0][0]!;
    expect(options.video).toMatchObject({
      width: { ideal: 1920, max: 1920 },
      height: { ideal: 1080, max: 1080 },
      frameRate: { ideal: 60, max: 60 },
    });
    expect(options.audio).toBe(false);
    expect(video.contentHint).toBe("motion");
    expect(published.requested.frameRate).toBe(60);
    expect(published.actual).toEqual({ width: 1920, height: 1080, frameRate: 60 });
  });

  it("publishes one screen video and one screen audio track when audio is shared", async () => {
    const video = new FakeMediaStreamTrack("video");
    const audio = new FakeMediaStreamTrack("audio");
    setGetDisplayMedia(() => Promise.resolve(fakeStream([video, audio])));
    const { room, publishTrack } = fakeRoom();

    const published = await publishScreenShareTrack(room, { quality: "detail", includeAudio: true });

    expect(publishTrack).toHaveBeenCalledTimes(2);
    expect(publishTrack.mock.calls[0][1]).toMatchObject({ source: Track.Source.ScreenShare });
    expect(publishTrack.mock.calls[1][1]).toMatchObject({ source: Track.Source.ScreenShareAudio });
    expect(published.audioTrack?.source).toBe(Track.Source.ScreenShareAudio);
    expect(published.audioUnavailable).toBe(false);
  });

  it("keeps sharing the screen and flags audioUnavailable when no audio track comes back", async () => {
    const video = new FakeMediaStreamTrack("video");
    setGetDisplayMedia(() => Promise.resolve(fakeStream([video])));
    const { room, publishTrack } = fakeRoom();

    const published = await publishScreenShareTrack(room, { includeAudio: true });

    expect(publishTrack).toHaveBeenCalledTimes(1);
    expect(published.track.source).toBe(Track.Source.ScreenShare);
    expect(published.audioTrack).toBeNull();
    expect(published.audioUnavailable).toBe(true);
  });

  it("drops shared audio the user did not ask for", async () => {
    const video = new FakeMediaStreamTrack("video");
    const audio = new FakeMediaStreamTrack("audio");
    setGetDisplayMedia(() => Promise.resolve(fakeStream([video, audio])));
    const { room, publishTrack } = fakeRoom();

    const published = await publishScreenShareTrack(room, { includeAudio: false });

    expect(publishTrack).toHaveBeenCalledTimes(1);
    expect(audio.stop).toHaveBeenCalled();
    expect(published.audioUnavailable).toBe(false);
  });
});

describe("unpublishScreenShareTrack", () => {
  afterEach(() => {
    if (originalMediaDevices) {
      Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
    }
  });

  it("unpublishes and stops both the screen video and screen audio", async () => {
    vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const video = new FakeMediaStreamTrack("video");
    const audio = new FakeMediaStreamTrack("audio");
    setGetDisplayMedia(() => Promise.resolve(fakeStream([video, audio])));
    const { room, unpublishTrack } = fakeRoom();
    const published = await publishScreenShareTrack(room, { includeAudio: true });

    unpublishScreenShareTrack(room, published.track, published.audioTrack);

    expect(unpublishTrack).toHaveBeenCalledWith(published.audioTrack, true);
    expect(unpublishTrack).toHaveBeenCalledWith(published.track, true);
    expect(video.stop).toHaveBeenCalled();
    expect(audio.stop).toHaveBeenCalled();
    vi.restoreAllMocks();
  });
});
