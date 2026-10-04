import type { BrseMode, BrseOutputMode, RoomSummary } from "../types/api";
import { normalizeLanguageList, normalizeRoomLanguages } from "./languages";

export type BrseRoomMode = "off" | "voice_text" | "text_only" | "silent_summary";
export type BrseCreateMode = "voice_text" | "text_only" | "off";

type BrseRoomLike =
  | (Partial<
      Pick<
        RoomSummary,
        | "brse_enabled"
        | "brse_mode"
        | "brse_output_mode"
        | "meeting_mode"
        | "audio_routing"
        | "room_languages"
        | "meeting_languages"
        | "language_a"
        | "language_b"
        | "supported_languages"
      >
    > & {
      brse_mode?: BrseMode | string;
      brse_output_mode?: BrseOutputMode | string;
    })
  | null
  | undefined;

export const BRSE_CREATE_MODE_OPTIONS: Array<{
  value: BrseCreateMode;
  label: string;
  detail: string;
}> = [
  {
    value: "voice_text",
    label: "Voice + Text",
    detail: "Text relay + AI voice",
  },
  {
    value: "text_only",
    label: "Text Only",
    detail: "Text relay, no AI voice",
  },
  {
    value: "off",
    label: "Off",
    detail: "No BRSE relay",
  },
];

export function normalizeBrseOutputMode(
  value: BrseOutputMode | string | null | undefined,
): BrseOutputMode {
  return value === "text_only" ? "text_only" : "voice_text";
}

export function normalizeBrseMode(
  value: BrseMode | string | null | undefined,
): BrseMode {
  return value === "silent_summary" ? "silent_summary" : "relay";
}

export function resolveBrseEnabled(room: BrseRoomLike): boolean {
  if (!room) {
    return false;
  }

  if (typeof room.brse_enabled === "boolean") {
    return room.brse_enabled;
  }

  return (
    room.meeting_mode === "brse_relay" ||
    room.meeting_mode === "brse_silent_summary" ||
    room.audio_routing?.model === "brse_participant_audio" ||
    room.audio_routing?.model === "brse_text_only_relay" ||
    room.audio_routing?.model === "brse_silent_listener"
  );
}

export function resolveBrseOutputMode(room: BrseRoomLike): BrseOutputMode {
  return normalizeBrseOutputMode(
    room?.audio_routing?.effective_brse_output_mode ??
      room?.brse_output_mode ??
      room?.audio_routing?.brse_output_mode,
  );
}

export function resolveBrseRoomMode(room: BrseRoomLike): BrseRoomMode {
  if (!resolveBrseEnabled(room)) {
    return "off";
  }

  if (isSilentSummaryRoom(room)) {
    return "silent_summary";
  }

  const roomLanguageCount = normalizeRoomLanguages(room).length;
  if (roomLanguageCount > 0 && !isVoiceRelayAvailable(roomLanguageCount)) {
    return "text_only";
  }

  if (room?.audio_routing?.model === "brse_text_only_relay") {
    return "text_only";
  }

  if (room?.audio_routing?.ai_audio_output_enabled === false) {
    return "text_only";
  }

  if (room?.audio_routing?.relay_audio_enabled === false) {
    return "text_only";
  }

  return resolveBrseOutputMode(room);
}

export function isBrseAudioExpected(room: BrseRoomLike): boolean {
  if (!resolveBrseEnabled(room)) {
    return false;
  }

  if (isSilentSummaryRoom(room)) {
    return false;
  }

  const roomLanguageCount = normalizeRoomLanguages(room).length;
  if (roomLanguageCount > 0 && !isVoiceRelayAvailable(roomLanguageCount)) {
    return false;
  }

  if (room?.audio_routing?.model === "brse_text_only_relay") {
    return false;
  }

  if (room?.audio_routing?.ai_audio_output_enabled === false) {
    return false;
  }

  if (room?.audio_routing?.relay_audio_enabled === false) {
    return false;
  }

  return resolveBrseOutputMode(room) === "voice_text";
}

function isSilentSummaryRoom(room: BrseRoomLike): boolean {
  return (
    normalizeBrseMode(room?.brse_mode ?? room?.audio_routing?.brse_mode) ===
      "silent_summary" ||
    room?.meeting_mode === "brse_silent_summary" ||
    room?.audio_routing?.model === "brse_silent_listener"
  );
}

export function getBrseModeLabel(mode: BrseRoomMode): string {
  switch (mode) {
    case "voice_text":
      return "BRSE Voice";
    case "text_only":
      return "BRSE Text Only";
    case "silent_summary":
      return "BRSE Summary";
    case "off":
    default:
      return "BRSE Off";
  }
}

export function getBrseModeDescription(mode: BrseRoomMode): string {
  switch (mode) {
    case "voice_text":
      return "Text + AI voice";
    case "text_only":
      return "Text relay only";
    case "silent_summary":
      return "Summary capture";
    case "off":
    default:
      return "Normal meeting";
  }
}

export function isVoiceRelayAvailable(languageCount: number): boolean {
  return languageCount === 2;
}

export function getEffectiveOutputMode(
  selectedLanguages: readonly unknown[] | null | undefined,
  requestedMode: BrseCreateMode,
): BrseCreateMode {
  const languageCount = normalizeLanguageList(selectedLanguages).length;
  return isVoiceRelayAvailable(languageCount)
    ? requestedMode
    : "text_only";
}

export function getCreateModeDisabledReason(
  languageCount: number,
  mode: BrseCreateMode,
): string | null {
  if (isVoiceRelayAvailable(languageCount)) {
    return null;
  }

  if (mode === "text_only") {
    return null;
  }

  if (languageCount === 1) {
    return "Single-language rooms capture transcript/captions.";
  }

  if (languageCount > 2) {
    return "Multi-language rooms use text relay only.";
  }

  return "Select at least one room language.";
}

export function buildCreateBrsePayload(
  mode: BrseCreateMode,
  selectedLanguages?: readonly unknown[] | null,
): {
  brse_enabled: boolean;
  brse_mode: BrseMode;
  brse_output_mode: BrseOutputMode;
} {
  const effectiveMode = selectedLanguages
    ? getEffectiveOutputMode(selectedLanguages, mode)
    : mode;

  return {
    brse_enabled: effectiveMode !== "off",
    brse_mode: "relay",
    brse_output_mode: effectiveMode === "text_only" ? "text_only" : "voice_text",
  };
}

// ─── In-room relay mode (room-level, independent of AI on/off) ────────────────

export const RELAY_MODE_OPTIONS: Array<{
  value: BrseOutputMode;
  label: string;
  description: string;
}> = [
  {
    value: "voice_text",
    label: "Voice + Text",
    description: "Live translation appears as text and AI voice.",
  },
  {
    value: "text_only",
    label: "Text Only",
    description: "Live translation appears as text without AI voice.",
  },
];

/**
 * Relay modes participants can switch between during the meeting. Only rooms with
 * exactly two languages (and normal relay, not summary capture) have a choice; other
 * rooms return [] so no selector is shown. Does not depend on AI being on.
 */
export function getSelectableRelayModes(room: BrseRoomLike): BrseOutputMode[] {
  if (!room || isSilentSummaryRoom(room)) {
    return [];
  }
  return isVoiceRelayAvailable(normalizeRoomLanguages(room).length)
    ? ["voice_text", "text_only"]
    : [];
}

/**
 * Whether BRSE voice tracks should be played in this room. True whenever voice relay
 * is possible (AI on, two languages), regardless of the current mode: the server only
 * sends audio for relays that started in Voice + Text, so a sentence already being
 * spoken when someone switches to Text Only can finish instead of being cut.
 */
export function isBrseAudioPossible(room: BrseRoomLike): boolean {
  return (
    resolveBrseEnabled(room) &&
    !isSilentSummaryRoom(room) &&
    isVoiceRelayAvailable(normalizeRoomLanguages(room).length)
  );
}

export function relayModeErrorMessage(code: string | null | undefined): string {
  switch (code) {
    case "room_expired":
      return "This meeting has ended, so the AI relay mode can't be changed.";
    case "relay_mode_not_supported":
      return "AI voice is only available in rooms with exactly two languages.";
    case "relay_mode_forbidden":
    case "session_mismatch":
      return "Your session is no longer active in this room. Rejoin to change the AI relay mode.";
    default:
      return "Could not update AI relay mode. Try again.";
  }
}

export interface RelayModeState {
  brse_enabled?: boolean;
  brse_mode?: BrseMode;
  brse_output_mode?: BrseOutputMode;
  audio_routing?: RoomSummary["audio_routing"];
}

/** Applies server relay-mode state (REST response or room.relay_mode_updated) to room meta. */
export function applyRelayModeToRoom<T extends Partial<RoomSummary>>(room: T, next: RelayModeState): T {
  return {
    ...room,
    brse_enabled: next.brse_enabled ?? room.brse_enabled,
    brse_mode: next.brse_mode ?? room.brse_mode,
    brse_output_mode: next.brse_output_mode ?? room.brse_output_mode,
    audio_routing: next.audio_routing ?? room.audio_routing,
  };
}
