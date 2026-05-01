import type {
  InterpreterMode,
  Language,
  ParticipantReference,
  ParticipantSnapshot,
} from "../../types/api";
import type { InterpreterStatusValue } from "../../types/ws";

export interface InterpreterStatusEntry {
  key: string;
  speakerId: string;
  speakerName: string;
  brseParticipantId: string | null;
  brseParticipantName: string;
  sourceLanguage: Language | null;
  targetLanguage: Language;
  status: InterpreterStatusValue;
  fallbackUsed: boolean;
  message: string | null;
  audioTrackName: string | null;
  audienceParticipantIds: string[];
  relayMode: InterpreterMode | null;
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
    brse_participant?: ParticipantReference | null;
    listener_ids?: string[];
    audience_participant_ids?: string[];
    relay_mode?: InterpreterMode | null;
  },
  sentAt: string,
  participantsById: Record<string, ParticipantSnapshot>,
): InterpreterStatusEntry[] {
  const key = `${payload.speaker_id}:${payload.target_language}`;
  const brseParticipantName = payload.brse_participant?.display_name ?? "AI Relay";
  const nextEntry: InterpreterStatusEntry = {
    key,
    speakerId: payload.speaker_id,
    speakerName:
      participantsById[payload.speaker_id]?.display_name || payload.speaker_id,
    brseParticipantId: payload.brse_participant?.participant_id ?? null,
    brseParticipantName,
    sourceLanguage: payload.source_language ?? null,
    targetLanguage: payload.target_language,
    status: payload.status,
    fallbackUsed: payload.fallback_used,
    message: payload.message,
    audioTrackName: payload.audio_track_name ?? null,
    audienceParticipantIds:
      payload.audience_participant_ids ?? payload.listener_ids ?? [],
    relayMode: payload.relay_mode ?? null,
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
