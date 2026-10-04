import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AiRelaySettingsPanel } from "./AiRelaySettingsPanel";
import { RelayModeControl } from "./RelayModeControl";

describe("RelayModeControl", () => {
  it("is hidden when the room has no mode choice (1 or 3+ languages)", () => {
    const { container } = render(<RelayModeControl mode="text_only" modes={[]} onChange={() => undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the current server mode and sends the selected mode", async () => {
    const onChange = vi.fn();
    render(<RelayModeControl mode="voice_text" modes={["voice_text", "text_only"]} onChange={onChange} />);

    const trigger = screen.getByRole("button", { name: "AI relay mode" });
    expect(trigger).toHaveTextContent("Voice + Text");

    await userEvent.click(trigger);
    expect(screen.getByText("Live translation appears as text without AI voice.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: /Text Only/ }));
    expect(onChange).toHaveBeenCalledWith("text_only");
  });

  it("shows Updating… and is disabled while the server applies the change", () => {
    render(<RelayModeControl mode="voice_text" modes={["voice_text", "text_only"]} pending onChange={() => undefined} />);
    const trigger = screen.getByRole("button", { name: "AI relay mode" });
    expect(trigger).toHaveTextContent("Updating…");
    expect(trigger).toBeDisabled();
  });

  it("restores the server mode after a failed update (no optimistic value)", () => {
    const { rerender } = render(
      <RelayModeControl mode="voice_text" modes={["voice_text", "text_only"]} pending onChange={() => undefined} />,
    );
    // Request failed: pending ends, the server mode is still voice_text.
    rerender(<RelayModeControl mode="voice_text" modes={["voice_text", "text_only"]} onChange={() => undefined} />);
    expect(screen.getByRole("button", { name: "AI relay mode" })).toHaveTextContent("Voice + Text");
  });

  it("is disabled when the room has expired", () => {
    render(<RelayModeControl mode="text_only" modes={["voice_text", "text_only"]} disabled onChange={() => undefined} />);
    expect(screen.getByRole("button", { name: "AI relay mode" })).toBeDisabled();
  });
});

describe("AiRelaySettingsPanel", () => {
  const base = {
    brseRoomMode: "voice_text" as const,
    isTogglingBrse: false,
    canToggleBrse: true,
    onToggleBrse: () => undefined,
    relayMode: "voice_text" as const,
    isUpdatingRelayMode: false,
    canChangeRelayMode: true,
    onChangeRelayMode: () => undefined,
    relayModeError: null,
  };

  it("lets the mode change while AI relay is off without turning it on", async () => {
    const onToggleBrse = vi.fn();
    const onChangeRelayMode = vi.fn();
    render(
      <AiRelaySettingsPanel
        {...base}
        brseEnabled={false}
        brseRoomMode="off"
        languageCount={2}
        relayModes={["voice_text", "text_only"]}
        onToggleBrse={onToggleBrse}
        onChangeRelayMode={onChangeRelayMode}
      />,
    );
    expect(screen.getByText("AI relay is off. This mode is used when it's turned back on.")).toBeInTheDocument();
    // In Settings the select is named by its visible "Mode" label.
    await userEvent.click(screen.getByRole("button", { name: "Mode" }));
    await userEvent.click(screen.getByRole("option", { name: /Text Only/ }));
    expect(onChangeRelayMode).toHaveBeenCalledWith("text_only");
    expect(onToggleBrse).not.toHaveBeenCalled();
    expect(screen.getByRole("switch", { name: "AI relay" })).toHaveAttribute("aria-checked", "false");
  });

  it("explains fixed modes for single and multi-language rooms", () => {
    const { rerender } = render(<AiRelaySettingsPanel {...base} brseEnabled languageCount={1} relayModes={[]} />);
    expect(screen.queryByRole("button", { name: "Mode" })).not.toBeInTheDocument();
    expect(screen.getByText(/Single-language rooms show captions/)).toBeInTheDocument();
    rerender(<AiRelaySettingsPanel {...base} brseEnabled languageCount={3} relayModes={[]} />);
    expect(screen.getByText(/AI voice needs exactly two languages/)).toBeInTheDocument();
  });

  it("shows the server error message", () => {
    render(
      <AiRelaySettingsPanel
        {...base}
        brseEnabled
        languageCount={2}
        relayModes={["voice_text", "text_only"]}
        relayModeError="Could not update AI relay mode. Try again."
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Could not update AI relay mode. Try again.");
  });
});
