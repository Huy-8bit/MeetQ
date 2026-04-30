import type { Language, ParticipantSnapshot } from "../../types/api";
import type { InterpreterStatusValue } from "../../types/ws";

export interface InterpreterStatusEntry {
  key: string;
  speakerId: string;
  speakerName: string;
  sourceLanguage: Language | null;
  targetLanguage: Language;
  status: InterpreterStatusValue;
  fallbackUsed: boolean;
  message: string | null;
  audioTrackName: string | null;
  listenerIds: string[];
  updatedAt: string;
}

export function upsertInterpreterStatus(
  current: InterpreterStatusEntry[],
  payload: {
    speaker_id: string;
    source_language?: Language;
    target_language: Language;
    status: InterpreterStatusValue;
    fallback_used: boolean;
    message: string | null;
    audio_track_name?: string | null;
    listener_ids?: string[];
  },
  sentAt: string,
  participantsById: Record<string, ParticipantSnapshot>,
): InterpreterStatusEntry[] {
  const key = `${payload.speaker_id}:${payload.target_language}`;
  const nextEntry: InterpreterStatusEntry = {
    key,
    speakerId: payload.speaker_id,
    speakerName:
      participantsById[payload.speaker_id]?.display_name || payload.speaker_id,
    sourceLanguage: payload.source_language ?? null,
    targetLanguage: payload.target_language,
    status: payload.status,
    fallbackUsed: payload.fallback_used,
    message: payload.message,
    audioTrackName: payload.audio_track_name ?? null,
    listenerIds: payload.listener_ids ?? [],
    updatedAt: sentAt,
  };

  const index = current.findIndex((item) => item.key === key);
  if (index === -1) {
    return [nextEntry, ...current];
  }

  const next = [...current];
  next[index] = nextEntry;
  return next;
}
