import { describe, expect, it } from "vitest";
import { ScreenShareCancelledError, ScreenShareUnsupportedError } from "../../lib/livekit";
import { buildScreenShareNotice, screenShareStartErrorMessage } from "./useMeetingRoom";

describe("screenShareStartErrorMessage", () => {
  it("shows nothing when the user closes the picker", () => {
    expect(screenShareStartErrorMessage(new ScreenShareCancelledError())).toBeNull();
  });

  it("explains unsupported devices", () => {
    expect(screenShareStartErrorMessage(new ScreenShareUnsupportedError())).toBe(
      "Screen sharing isn't supported on this device.",
    );
  });

  it("uses a generic message for real failures (no raw browser/backend text)", () => {
    expect(screenShareStartErrorMessage(new DOMException("Could not start video source", "NotReadableError"))).toBe(
      "Could not start screen sharing.",
    );
    expect(screenShareStartErrorMessage(new Error("500 Internal Server Error"))).toBe(
      "Could not start screen sharing.",
    );
  });
});

describe("buildScreenShareNotice", () => {
  const requested = { width: 1920, height: 1080, frameRate: 60 };

  it("is silent when the capture matches the request", () => {
    expect(buildScreenShareNotice({ audioUnavailable: false, requested, actual: { frameRate: 60 } })).toBeNull();
    expect(buildScreenShareNotice({ audioUnavailable: false, requested, actual: {} })).toBeNull();
  });

  it("warns when shared audio was asked for but not provided", () => {
    expect(buildScreenShareNotice({ audioUnavailable: true, requested, actual: { frameRate: 60 } })).toBe(
      "Screen sharing started, but shared audio isn't available for this source or browser.",
    );
  });

  it("reports the real frame rate instead of claiming 60 FPS", () => {
    expect(buildScreenShareNotice({ audioUnavailable: false, requested, actual: { frameRate: 30 } })).toBe(
      "Your browser is capturing at up to 30 FPS (60 FPS requested).",
    );
  });
});
