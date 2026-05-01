import type {
  Language,
  ParticipantKind,
  ParticipantReference,
  RecentTranscriptSnapshot,
} from "../../types/api";
import type { TranscriptPayload } from "../../types/ws";

/**
 * Maximum number of transcript entries kept in state.
 * Chose 30 as a practical cap: enough to show recent conversation context
 * (covering ~2-3 min of active relay), but prevents unbounded DOM growth
 * that causes layout instability and perf issues.
 */
export const MAX_TRANSCRIPT_ENTRIES = 30;

export type TranscriptKind = "source" | "translated" | "relay";

export interface TranscriptEntry {
  transcriptId: string;
  utteranceId: string | null;
  kind: TranscriptKind;
  actorParticipantId: string;
  actorName: string;
  actorLanguage: Language;
  actorKind: ParticipantKind;
  sourceSpeakerId: string;
  sourceSpeakerName: string;
  sourceSpeakerLanguage: Language;
  relayParticipantId: string | null;
  relayParticipantName: string | null;
  relayTargetLanguage: Language | null;
  sourceText: string;
  relayText: string | null;
  text: string;
  audioTrackName: string | null;
  canonicalAudioTrackName: string | null;
  fallbackUsed: boolean;
  isFinal: boolean;
  timestamp: string;
  updatedAt: string;
}

export function hydrateTranscriptEntries(
  transcripts: RecentTranscriptSnapshot[],
  targetLanguage: Language | null,
): TranscriptEntry[] {
  return transcripts
    .map((item) => normalizeSnapshotTranscript(item, targetLanguage))
    .sort(sortTranscriptEntries);
}

export function upsertTranscriptEntry(
  current: TranscriptEntry[],
  payload: TranscriptPayload,
  sentAt: string,
): TranscriptEntry[] {
  return mergeTranscriptCollections(current, [normalizeLiveTranscript(payload, sentAt)]);
}

export function mergeTranscriptCollections(
  current: TranscriptEntry[],
  incoming: TranscriptEntry[],
): TranscriptEntry[] {
  if (incoming.length === 0) {
    return current;
  }

  const merged = new Map<string, TranscriptEntry>();

  for (const item of current) {
    merged.set(item.transcriptId, item);
  }

  for (const item of incoming) {
    const existing = merged.get(item.transcriptId);
    if (!existing) {
      merged.set(item.transcriptId, item);
      continue;
    }

    merged.set(item.transcriptId, choosePreferredTranscript(existing, item));
  }

  const sorted = Array.from(merged.values()).sort(sortTranscriptEntries);
  return pruneTranscriptCollection(sorted);
}

/**
 * Prune transcript collection to MAX_TRANSCRIPT_ENTRIES.
 * Strategy:
 * - Never drop active partial entries (they are being updated in realtime)
 * - Drop oldest final entries first
 * - If still over limit after dropping finals, drop oldest partials
 */
export function pruneTranscriptCollection(
  entries: TranscriptEntry[],
): TranscriptEntry[] {
  if (entries.length <= MAX_TRANSCRIPT_ENTRIES) {
    return entries;
  }

  // Separate partials and finals
  const partials: TranscriptEntry[] = [];
  const finals: TranscriptEntry[] = [];

  for (const entry of entries) {
    if (entry.isFinal) {
      finals.push(entry);
    } else {
      partials.push(entry);
    }
  }

  // Keep all partials, trim finals from the oldest
  const slotsForFinals = Math.max(0, MAX_TRANSCRIPT_ENTRIES - partials.length);
  const keptFinals = finals.slice(-slotsForFinals);

  // If partials alone exceed the limit, trim oldest partials too
  const combined = [...keptFinals, ...partials].sort(sortTranscriptEntries);
  if (combined.length > MAX_TRANSCRIPT_ENTRIES) {
    return combined.slice(-MAX_TRANSCRIPT_ENTRIES);
  }

  return combined;
}

function normalizeSnapshotTranscript(
  item: RecentTranscriptSnapshot,
  targetLanguage: Language | null,
): TranscriptEntry {
  const kind = item.kind ?? inferSnapshotKind(item);
  const sourceSpeakerRef = pickSourceSpeakerRef({
    speakerId: item.speaker_id,
    speakerName: item.speaker_display_name,
    srcLang: item.src_lang,
    speaker: item.speaker,
    originalSpeaker: item.original_speaker,
  });
  const relayParticipant = pickRelayParticipantRef(item.brse_participant);
  const relayTargetLanguage =
    item.relay_target?.target_language
    ?? item.target_lang
    ?? item.listener?.target_language
    ?? targetLanguage;
  const actor = pickActor({
    kind,
    sourceSpeakerRef,
    relayParticipant,
    relayTargetLanguage,
  });
  const sourceText = item.source_text ?? item.text ?? "";
  const relayText = pickRelayText(kind, {
    text: item.text,
    brseText: item.brse_text,
    translatedText: item.translated_text,
  });
  const text =
    kind === "relay"
      ? relayText ?? sourceText
      : item.text ?? (kind === "translated" ? relayText ?? sourceText : sourceText);

  return {
    transcriptId: item.transcript_id,
    utteranceId: item.utterance_id ?? null,
    kind,
    actorParticipantId: actor.participant_id,
    actorName: actor.display_name,
    actorLanguage: actor.language,
    actorKind: actor.kind,
    sourceSpeakerId: sourceSpeakerRef.participant_id,
    sourceSpeakerName: sourceSpeakerRef.display_name,
    sourceSpeakerLanguage: sourceSpeakerRef.source_language ?? sourceSpeakerRef.language,
    relayParticipantId: relayParticipant?.participant_id ?? null,
    relayParticipantName: relayParticipant?.display_name ?? null,
    relayTargetLanguage: relayTargetLanguage ?? null,
    sourceText,
    relayText,
    text,
    audioTrackName: item.audio_track_name ?? null,
    canonicalAudioTrackName:
      item.audio_output?.track_name ?? item.audio_track_name ?? null,
    fallbackUsed: item.fallback_used ?? false,
    isFinal: item.is_final ?? true,
    timestamp: item.created_at,
    updatedAt: item.created_at,
  };
}

function normalizeLiveTranscript(
  payload: TranscriptPayload,
  sentAt: string,
): TranscriptEntry {
  const kind = payload.kind ?? inferLiveKind(payload);
  const sourceSpeakerRef = pickSourceSpeakerRef({
    speakerId: payload.speaker.participant_id,
    speakerName: payload.speaker.display_name,
    srcLang:
      payload.src_lang
      ?? payload.original_speaker?.source_language
      ?? payload.original_speaker?.language
      ?? payload.speaker.source_language
      ?? payload.speaker.language
      ?? "auto",
    speaker: payload.speaker,
    originalSpeaker: payload.original_speaker,
  });
  const relayParticipant = pickRelayParticipantRef(payload.brse_participant);
  const relayTargetLanguage =
    payload.relay_target?.target_language
    ?? payload.tgt_lang
    ?? payload.listener?.target_language
    ?? payload.audio_output?.target_language
    ?? null;
  const actor = pickActor({
    kind,
    sourceSpeakerRef,
    relayParticipant,
    relayTargetLanguage,
  });
  const sourceText = payload.source_text ?? payload.text ?? "";
  const relayText = pickRelayText(kind, {
    text: payload.text,
    brseText: payload.brse_text,
    translatedText: payload.translated_text,
  });
  const text =
    kind === "relay"
      ? relayText ?? sourceText
      : payload.text ?? (kind === "translated" ? relayText ?? sourceText : sourceText);
  const timestamp = payload.created_at ?? sentAt;

  return {
    transcriptId: payload.transcript_id,
    utteranceId: payload.utterance_id ?? null,
    kind,
    actorParticipantId: actor.participant_id,
    actorName: actor.display_name,
    actorLanguage: actor.language,
    actorKind: actor.kind,
    sourceSpeakerId: sourceSpeakerRef.participant_id,
    sourceSpeakerName: sourceSpeakerRef.display_name,
    sourceSpeakerLanguage: sourceSpeakerRef.source_language ?? sourceSpeakerRef.language,
    relayParticipantId: relayParticipant?.participant_id ?? null,
    relayParticipantName: relayParticipant?.display_name ?? null,
    relayTargetLanguage,
    sourceText,
    relayText,
    text,
    audioTrackName: payload.audio_track_name ?? null,
    canonicalAudioTrackName:
      payload.audio_output?.track_name ?? payload.audio_track_name ?? null,
    fallbackUsed: payload.fallback_used,
    isFinal: payload.is_final,
    timestamp,
    updatedAt: sentAt,
  };
}

function choosePreferredTranscript(
  existing: TranscriptEntry,
  incoming: TranscriptEntry,
): TranscriptEntry {
  const baseTimestamp = existing.timestamp.localeCompare(incoming.timestamp) <= 0
    ? existing.timestamp
    : incoming.timestamp;

  if (existing.isFinal && !incoming.isFinal) {
    return {
      ...existing,
      timestamp: baseTimestamp,
    };
  }

  if (!existing.isFinal && incoming.isFinal) {
    return {
      ...incoming,
      timestamp: baseTimestamp,
    };
  }

  const preferred =
    existing.updatedAt.localeCompare(incoming.updatedAt) >= 0
      ? existing
      : incoming;

  return {
    ...preferred,
    timestamp: baseTimestamp,
  };
}

function inferSnapshotKind(item: RecentTranscriptSnapshot): TranscriptKind {
  if (item.brse_text || item.brse_participant || item.relay_target) {
    return "relay";
  }
  if (item.translated_text && item.target_lang && item.target_lang !== item.src_lang) {
    return "translated";
  }
  return "source";
}

function inferLiveKind(payload: TranscriptPayload): TranscriptKind {
  if (payload.brse_text || payload.brse_participant || payload.relay_target) {
    return "relay";
  }
  if (payload.tgt_lang && payload.src_lang && payload.tgt_lang !== payload.src_lang) {
    return "translated";
  }
  if (payload.listener?.target_language && payload.speaker.source_language) {
    return payload.listener.target_language === payload.speaker.source_language
      ? "source"
      : "translated";
  }
  return "source";
}

function pickSourceSpeakerRef(input: {
  speakerId: string;
  speakerName: string;
  srcLang: Language;
  speaker?: ParticipantReference | null;
  originalSpeaker?: ParticipantReference | null;
}): RequiredParticipantReference {
  const ref = input.originalSpeaker ?? input.speaker;
  return {
    participant_id: ref?.participant_id ?? input.speakerId,
    display_name: ref?.display_name ?? input.speakerName,
    language:
      ref?.language
      ?? ref?.source_language
      ?? input.srcLang,
    source_language:
      ref?.source_language
      ?? ref?.language
      ?? input.srcLang,
    kind: ref?.kind ?? "human",
  };
}

function pickRelayParticipantRef(
  ref?: ParticipantReference | null,
): RequiredParticipantReference | null {
  if (!ref) {
    return null;
  }

  return {
    participant_id: ref.participant_id,
    display_name: ref.display_name,
    language: ref.language ?? "auto",
    source_language: ref.source_language ?? ref.language ?? "auto",
    kind: ref.kind ?? "virtual_brse",
  };
}

function pickActor(input: {
  kind: TranscriptKind;
  sourceSpeakerRef: RequiredParticipantReference;
  relayParticipant: RequiredParticipantReference | null;
  relayTargetLanguage: Language | null;
}): RequiredParticipantReference {
  if (input.kind !== "relay") {
    return input.sourceSpeakerRef;
  }

  const relayActor = input.relayParticipant ?? {
    participant_id: "brse_ai",
    display_name: "AI Relay",
    language: "auto" as Language,
    source_language: "auto" as Language,
    kind: "virtual_brse" as ParticipantKind,
  };

  return {
    ...relayActor,
    language: input.relayTargetLanguage ?? relayActor.language,
  };
}

function pickRelayText(
  kind: TranscriptKind,
  input: {
    text?: string | null;
    brseText?: string | null;
    translatedText?: string | null;
  },
): string | null {
  if (kind === "relay") {
    return input.brseText ?? input.translatedText ?? input.text ?? null;
  }

  if (kind === "translated") {
    return input.translatedText ?? input.text ?? null;
  }

  return null;
}

function sortTranscriptEntries(left: TranscriptEntry, right: TranscriptEntry): number {
  const byTime = left.timestamp.localeCompare(right.timestamp);
  if (byTime !== 0) {
    return byTime;
  }
  return left.updatedAt.localeCompare(right.updatedAt);
}

interface RequiredParticipantReference {
  participant_id: string;
  display_name: string;
  language: Language;
  source_language: Language;
  kind: ParticipantKind;
}
