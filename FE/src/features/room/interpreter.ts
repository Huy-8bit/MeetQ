import type { Language, ParticipantSnapshot } from "../../types/api";
import type { InterpreterStatusValue } from "../../types/ws";

export interface InterpreterStatusEntry {
  key: string;
  speakerId: string;
  speakerName: string;
  targetLanguage: Language;
  status: InterpreterStatusValue;
  fallbackUsed: boolean;
  message: string | null;
  updatedAt: string;
}

export function upsertInterpreterStatus(
  current: InterpreterStatusEntry[],
  payload: {
    speaker_id: string;
    target_language: Language;
    status: InterpreterStatusValue;
    fallback_used: boolean;
    message: string | null;
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
    targetLanguage: payload.target_language,
    status: payload.status,
    fallbackUsed: payload.fallback_used,
    message: payload.message,
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
