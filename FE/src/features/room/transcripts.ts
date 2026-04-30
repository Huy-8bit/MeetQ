import type {
  Language,
  RecentTranscriptSnapshot,
} from "../../types/api";
import type { TranscriptPayload } from "../../types/ws";

export type TranscriptKind = "source" | "translated";

export interface TranscriptEntry {
  transcriptId: string;
  utteranceId: string | null;
  speakerParticipantId: string;
  speakerName: string;
  speakerLanguage: Language;
  kind: TranscriptKind;
  srcLang: Language;
  tgtLang: Language | null;
  text: string;
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

  return Array.from(merged.values()).sort(sortTranscriptEntries);
}

function normalizeSnapshotTranscript(
  item: RecentTranscriptSnapshot,
  targetLanguage: Language | null,
): TranscriptEntry {
  const kind = item.kind ?? inferSnapshotKind(item);
  const srcLang = item.src_lang;
  const speakerLanguage =
    item.speaker_language ?? item.speaker?.language ?? item.speaker?.source_language ?? srcLang;
  const text =
    item.text ??
    (kind === "translated"
      ? item.translated_text ?? item.source_text
      : item.source_text);

  return {
    transcriptId: item.transcript_id,
    utteranceId: item.utterance_id ?? null,
    speakerParticipantId: item.speaker?.participant_id ?? item.speaker_id,
    speakerName: item.speaker?.display_name ?? item.speaker_display_name,
    speakerLanguage,
    kind,
    srcLang,
    tgtLang: item.target_lang ?? item.listener?.target_language ?? targetLanguage,
    text,
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
  const srcLang =
    payload.src_lang ??
    payload.speaker.source_language ??
    payload.speaker.language ??
    payload.listener?.target_language ??
    "en";
  const speakerLanguage =
    payload.speaker.language ?? payload.speaker.source_language ?? srcLang;
  const text = payload.text ?? pickTranscriptText(kind, payload);
  const timestamp = payload.created_at ?? sentAt;

  return {
    transcriptId: payload.transcript_id,
    utteranceId: payload.utterance_id ?? null,
    speakerParticipantId: payload.speaker.participant_id,
    speakerName: payload.speaker.display_name,
    speakerLanguage,
    kind,
    srcLang,
    tgtLang: payload.tgt_lang ?? payload.listener?.target_language ?? null,
    text,
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
  if (item.translated_text && item.target_lang && item.target_lang !== item.src_lang) {
    return "translated";
  }
  return "source";
}

function inferLiveKind(payload: TranscriptPayload): TranscriptKind {
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

function pickTranscriptText(kind: TranscriptKind, payload: TranscriptPayload): string {
  if (kind === "translated") {
    return payload.translated_text ?? payload.source_text ?? "";
  }
  return payload.source_text ?? payload.translated_text ?? "";
}

function sortTranscriptEntries(left: TranscriptEntry, right: TranscriptEntry): number {
  const byTime = left.timestamp.localeCompare(right.timestamp);
  if (byTime !== 0) {
    return byTime;
  }
  return left.updatedAt.localeCompare(right.updatedAt);
}
