import type { Language, MeetingLanguage, RoomSnapshotResponse } from "../types/api";

export const SUPPORTED_MEETING_LANGUAGES: readonly MeetingLanguage[] = [
  "vi",
  "en",
  "ja",
  "zh",
  "ko",
  "fr",
  "es",
];

export const DEFAULT_MEETING_LANGUAGE_PAIR: readonly [
  MeetingLanguage,
  MeetingLanguage,
] = ["vi", "ja"];

const LANGUAGE_LABELS: Record<Language, string> = {
  vi: "Vietnamese",
  en: "English",
  ja: "Japanese",
  zh: "Chinese",
  ko: "Korean",
  fr: "French",
  es: "Spanish",
  auto: "Auto",
};

export function isMeetingLanguage(value: string): value is MeetingLanguage {
  return SUPPORTED_MEETING_LANGUAGES.includes(value as MeetingLanguage);
}

export function getLanguageLabel(language: Language | null | undefined): string {
  if (!language) {
    return "Unknown";
  }

  return LANGUAGE_LABELS[language] ?? language;
}

export function formatLanguageFlow(
  sourceLanguage: Language | null | undefined,
  targetLanguage: Language | null | undefined,
): string {
  return `${getLanguageLabel(sourceLanguage ?? "auto")} → ${getLanguageLabel(targetLanguage ?? "auto")}`;
}

export function formatMeetingLanguagePair(
  languages: readonly MeetingLanguage[] | null | undefined,
): string {
  if (!languages || languages.length === 0) {
    return "Unavailable";
  }

  return formatRoomLanguageList(languages);
}

export function formatMeetingLanguageBridge(
  languages: readonly MeetingLanguage[] | null | undefined,
): string {
  if (!languages || languages.length === 0) {
    return "Unavailable";
  }

  return formatRoomLanguageList(languages);
}

export function formatRoomLanguageList(
  languages: readonly MeetingLanguage[] | null | undefined,
): string {
  const normalized = normalizeLanguageList(languages);
  if (normalized.length === 0) {
    return "Unavailable";
  }

  if (normalized.length === 1) {
    return getLanguageLabel(normalized[0]);
  }

  return normalized.map((language) => getLanguageLabel(language)).join(", ");
}

export function normalizeLanguageList(
  languages: readonly unknown[] | null | undefined,
): MeetingLanguage[] {
  const normalized: MeetingLanguage[] = [];
  for (const language of languages ?? []) {
    if (typeof language !== "string" || !isMeetingLanguage(language)) {
      continue;
    }
    if (!normalized.includes(language)) {
      normalized.push(language);
    }
  }

  return normalized;
}

interface RoomLanguageSource {
  room_languages?: readonly unknown[] | null;
  meeting_languages?: readonly unknown[] | null;
  language_a?: unknown;
  language_b?: unknown;
  supported_languages?: readonly unknown[] | null;
}

export function normalizeRoomLanguages(
  room: RoomLanguageSource | null | undefined,
): MeetingLanguage[] {
  const roomLanguages = normalizeLanguageList(room?.room_languages);
  if (roomLanguages.length > 0) {
    return roomLanguages;
  }

  const meetingLanguages = normalizeLanguageList(room?.meeting_languages);
  if (meetingLanguages.length > 0) {
    return meetingLanguages;
  }

  const legacyPair = normalizeLanguageList([room?.language_a, room?.language_b]);
  if (legacyPair.length > 0) {
    return legacyPair;
  }

  const supportedLanguages = normalizeLanguageList(room?.supported_languages);
  return supportedLanguages.length <= 2 ? supportedLanguages : [];
}

export function resolveMeetingLanguages(
  meetingLanguages: RoomSnapshotResponse["room"]["meeting_languages"] | undefined,
  supportedLanguages: RoomSnapshotResponse["room"]["supported_languages"] | undefined,
): MeetingLanguage[] {
  const directLanguages = normalizeLanguageList(meetingLanguages);
  if (directLanguages.length > 0) {
    return directLanguages;
  }

  const fallbackLanguages = normalizeLanguageList(supportedLanguages);
  return fallbackLanguages.length <= 2 ? fallbackLanguages : [];
}
