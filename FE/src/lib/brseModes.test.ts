import { describe, expect, it } from "vitest";
import {
  applyRelayModeToRoom,
  getSelectableRelayModes,
  isBrseAudioExpected,
  isBrseAudioPossible,
  relayModeErrorMessage,
  resolveBrseOutputMode,
  resolveBrseRoomMode,
} from "./brseModes";
import type { RoomSummary } from "../types/api";

type Room = Partial<RoomSummary>;

const twoLanguageVoice: Room = {
  brse_enabled: true,
  brse_mode: "relay",
  brse_output_mode: "voice_text",
  room_languages: ["vi", "ja"],
  audio_routing: { ai_audio_output_enabled: true } as RoomSummary["audio_routing"],
};

describe("relay mode selection rules", () => {
  it("offers both modes only in two-language relay rooms", () => {
    expect(getSelectableRelayModes(twoLanguageVoice)).toEqual(["voice_text", "text_only"]);
    expect(getSelectableRelayModes({ ...twoLanguageVoice, room_languages: ["en"] })).toEqual([]);
    expect(getSelectableRelayModes({ ...twoLanguageVoice, room_languages: ["vi", "ja", "en"] })).toEqual([]);
    expect(getSelectableRelayModes({ ...twoLanguageVoice, brse_mode: "silent_summary" })).toEqual([]);
  });

  it("keeps the mode choice while AI relay is off", () => {
    const off = { ...twoLanguageVoice, brse_enabled: false };
    expect(getSelectableRelayModes(off)).toEqual(["voice_text", "text_only"]);
    expect(resolveBrseRoomMode(off)).toBe("off");
    expect(resolveBrseOutputMode(off)).toBe("voice_text");
  });
});

describe("applying a room.relay_mode_updated event", () => {
  it("updates mode-derived UI for every participant without a reload", () => {
    const next = applyRelayModeToRoom(twoLanguageVoice, {
      brse_enabled: true,
      brse_output_mode: "text_only",
      audio_routing: { ai_audio_output_enabled: false } as RoomSummary["audio_routing"],
    });
    expect(resolveBrseOutputMode(next)).toBe("text_only");
    // Tile "Text relay" and Relay tab "AI voice is off" both follow these values.
    expect(resolveBrseRoomMode(next)).toBe("text_only");
    expect(isBrseAudioExpected(next)).toBe(false);
  });

  it("converges on the last event when two people change the mode", () => {
    let room: Room = twoLanguageVoice;
    for (const mode of ["text_only", "voice_text"] as const) {
      room = applyRelayModeToRoom(room, {
        brse_output_mode: mode,
        audio_routing: { ai_audio_output_enabled: mode === "voice_text" } as RoomSummary["audio_routing"],
      });
    }
    expect(resolveBrseRoomMode(room)).toBe("voice_text");
  });

  it("does not turn AI relay on when only the mode changes", () => {
    const room = applyRelayModeToRoom({ ...twoLanguageVoice, brse_enabled: false }, { brse_output_mode: "text_only" });
    expect(room.brse_enabled).toBe(false);
  });
});

describe("BRSE audio playback", () => {
  it("keeps BRSE tracks playable in two-language rooms in either mode so an in-flight sentence can finish", () => {
    expect(isBrseAudioPossible(twoLanguageVoice)).toBe(true);
    expect(isBrseAudioPossible({ ...twoLanguageVoice, brse_output_mode: "text_only" })).toBe(true);
    expect(isBrseAudioPossible({ ...twoLanguageVoice, room_languages: ["vi", "ja", "en"] })).toBe(false);
    expect(isBrseAudioPossible({ ...twoLanguageVoice, brse_enabled: false })).toBe(false);
  });
});

describe("relay mode errors", () => {
  it("maps server codes to friendly messages", () => {
    expect(relayModeErrorMessage("room_expired")).toMatch(/meeting has ended/);
    expect(relayModeErrorMessage("relay_mode_not_supported")).toMatch(/exactly two languages/);
    expect(relayModeErrorMessage("anything_else")).toBe("Could not update AI relay mode. Try again.");
  });
});
