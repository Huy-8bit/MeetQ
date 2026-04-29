import type { Language, RecentTranscriptSnapshot } from "../../types/api";
import type { TranscriptPayload } from "../../types/ws";

export interface TranscriptEntry {
  transcriptId: string;
  speakerId: string;
  speakerName: string;
  listenerId: string | null;
  sourceLanguage: Language;
  targetLanguage: Language | null;
  sourceText: string;
  translatedText: string;
  audioTrackName: string | null;
  fallbackUsed: boolean;
  isFinal: boolean;
  latencyMs?: number;
  createdAt: string;
  updatedAt: string;
}

export function hydrateTranscriptEntries(
  transcripts: RecentTranscriptSnapshot[],
  targetLanguage: Language | null,
): TranscriptEntry[] {
  return transcripts
    .map((item) => ({
      transcriptId: item.transcript_id,
      speakerId: item.speaker_id,
      speakerName: item.speaker_display_name,
      listenerId: null,
      sourceLanguage: item.src_lang,
      targetLanguage,
      sourceText: item.source_text,
      translatedText: "",
      audioTrackName: null,
      fallbackUsed: false,
      isFinal: true,
      createdAt: item.created_at,
      updatedAt: item.created_at,
    }))
    .sort((left, right) => left.createdAt.localeCompare(right.createdAt));
}

export function upsertTranscriptEntry(
  current: TranscriptEntry[],
  payload: TranscriptPayload,
  sentAt: string,
): TranscriptEntry[] {
  const entry: TranscriptEntry = {
    transcriptId: payload.transcript_id,
    speakerId: payload.speaker.participant_id,
    speakerName: payload.speaker.display_name,
    listenerId: payload.listener.participant_id,
    sourceLanguage: payload.speaker.source_language,
    targetLanguage: payload.listener.target_language,
    sourceText: payload.source_text,
    translatedText: payload.translated_text,
    audioTrackName: payload.audio_track_name,
    fallbackUsed: payload.fallback_used,
    isFinal: payload.is_final,
    latencyMs: payload.latency_ms,
    createdAt: sentAt,
    updatedAt: sentAt,
  };

  const index = current.findIndex(
    (item) => item.transcriptId === payload.transcript_id,
  );
  if (index === -1) {
    return [...current, entry].sort((left, right) =>
      left.createdAt.localeCompare(right.createdAt),
    );
  }

  const existing = current[index];
  const next = [...current];
  next[index] = {
    ...existing,
    ...entry,
    createdAt: existing.createdAt,
    updatedAt: sentAt,
  };
  return next;
}
