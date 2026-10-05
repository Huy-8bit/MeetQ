import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SCREEN_SHARE_QUALITY_STORAGE_KEY } from "../lib/uiPreferences";
import { RoomControlBar } from "./RoomControlBar";
import { ScreenShareDialog } from "./ScreenShareDialog";

afterEach(() => {
  window.localStorage.clear();
});

describe("ScreenShareDialog", () => {
  it("defaults to High quality with shared audio off", () => {
    render(<ScreenShareDialog open onConfirm={() => undefined} onCancel={() => undefined} />);

    expect(screen.getByRole("dialog", { name: "Share screen" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /High quality — 1080p · 30 FPS/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Smooth motion — 1080p · Up to 60 FPS/ })).not.toBeChecked();
    expect(screen.getByText("Best for text, slides, and coding.")).toBeInTheDocument();
    expect(screen.getByText("Best for video and animations.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Include shared audio" })).not.toBeChecked();
  });

  it("confirms with the chosen quality and audio, and remembers only the quality", async () => {
    const onConfirm = vi.fn();
    render(<ScreenShareDialog open onConfirm={onConfirm} onCancel={() => undefined} />);

    await userEvent.click(screen.getByRole("radio", { name: /Smooth motion/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Include shared audio" }));
    await userEvent.click(screen.getByRole("button", { name: "Share" }));

    expect(onConfirm).toHaveBeenCalledWith({ quality: "motion", includeAudio: true });
    expect(window.localStorage.getItem(SCREEN_SHARE_QUALITY_STORAGE_KEY)).toBe("motion");
    expect(window.localStorage.length).toBe(1);
  });

  it("reopens with the remembered quality but shared audio off again", async () => {
    const onConfirm = vi.fn();
    const { rerender } = render(<ScreenShareDialog open onConfirm={onConfirm} onCancel={() => undefined} />);

    await userEvent.click(screen.getByRole("radio", { name: /Smooth motion/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Include shared audio" }));
    await userEvent.click(screen.getByRole("button", { name: "Share" }));

    rerender(<ScreenShareDialog open={false} onConfirm={onConfirm} onCancel={() => undefined} />);
    rerender(<ScreenShareDialog open onConfirm={onConfirm} onCancel={() => undefined} />);

    expect(screen.getByRole("radio", { name: /Smooth motion/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Include shared audio" })).not.toBeChecked();
  });

  it("ignores an unknown stored quality", () => {
    window.localStorage.setItem(SCREEN_SHARE_QUALITY_STORAGE_KEY, "ultra");
    render(<ScreenShareDialog open onConfirm={() => undefined} onCancel={() => undefined} />);
    expect(screen.getByRole("radio", { name: /High quality/ })).toBeChecked();
  });

  it("cancels with Escape and Cancel without starting a share", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ScreenShareDialog open onConfirm={onConfirm} onCancel={onCancel} />);

    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe("RoomControlBar share button", () => {
  const baseProps = {
    sidePanelOpen: false,
    isMicMuted: false,
    isTogglingMic: false,
    isMutedByHost: false,
    isCameraOff: true,
    isTogglingCamera: false,
    isScreenSharing: false,
    isStartingScreenShare: false,
    isStoppingScreenShare: false,
    isLeaving: false,
    onToggleMic: () => undefined,
    onToggleCamera: () => undefined,
    onToggleSidePanel: () => undefined,
    onOpenSettings: () => undefined,
    onLeave: () => undefined,
  };

  it("explains and blocks sharing on devices without screen capture", async () => {
    const onToggleScreenShare = vi.fn();
    render(<RoomControlBar {...baseProps} canShareScreen={false} onToggleScreenShare={onToggleScreenShare} />);

    const button = screen.getByRole("button", { name: /Share screen/ });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAttribute("title", "Screen sharing isn't supported on this device.");
    await userEvent.click(button);
    expect(onToggleScreenShare).not.toHaveBeenCalled();
  });

  it("opens the share flow where screen capture is supported", async () => {
    const onToggleScreenShare = vi.fn();
    render(<RoomControlBar {...baseProps} canShareScreen onToggleScreenShare={onToggleScreenShare} />);

    const button = screen.getByRole("button", { name: "Share screen" });
    expect(button).not.toHaveAttribute("aria-disabled");
    await userEvent.click(button);
    expect(onToggleScreenShare).toHaveBeenCalledTimes(1);
  });
});
