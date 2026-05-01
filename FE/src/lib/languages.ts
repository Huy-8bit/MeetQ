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
  return `${getLanguageLabel(sourceLanguage ?? "auto")} -> ${getLanguageLabel(targetLanguage ?? "auto")}`;
}

export function formatMeetingLanguagePair(
  languages: readonly MeetingLanguage[] | null | undefined,
): string {
  if (!languages || languages.length === 0) {
    return "Unavailable";
  }

  if (languages.length === 1) {
    return getLanguageLabel(languages[0]);
  }

  return `${getLanguageLabel(languages[0])} and ${getLanguageLabel(languages[1])}`;
}

export function formatMeetingLanguageBridge(
  languages: readonly MeetingLanguage[] | null | undefined,
): string {
  if (!languages || languages.length === 0) {
    return "Unavailable";
  }

  return languages.map((language) => getLanguageLabel(language)).join(" <-> ");
}

export function resolveMeetingLanguages(
  meetingLanguages: RoomSnapshotResponse["room"]["meeting_languages"] | undefined,
  supportedLanguages: RoomSnapshotResponse["room"]["supported_languages"] | undefined,
): MeetingLanguage[] {
  const directPair = (meetingLanguages ?? []).filter(
    (language): language is MeetingLanguage => isMeetingLanguage(language),
  );

  if (directPair.length === 2 && directPair[0] !== directPair[1]) {
    return directPair;
  }

  const fallbackPair = [
    ...new Set(
      (supportedLanguages ?? []).filter((language): language is MeetingLanguage =>
        isMeetingLanguage(language),
      ),
    ),
  ];

  if (fallbackPair.length === 2 && fallbackPair[0] !== fallbackPair[1]) {
    return fallbackPair;
  }

  return [];
}
