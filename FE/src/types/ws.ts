import type { Language, ParticipantSnapshot } from "./api";

export interface WsEnvelope<TType extends string, TPayload> {
  type: TType;
  event_id: string;
  room_id: string;
  sent_at: string;
  payload: TPayload;
}

export type RoomSnapshotEvent = WsEnvelope<
  "room.snapshot",
  {
    self: {
      participant_id: string;
      session_id: string;
      display_name: string;
      language: Language;
    };
    room: {
      state: "created" | "active" | "empty";
      participant_limit: number;
      supported_languages: Language[];
    };
    participants: ParticipantSnapshot[];
    recent_transcripts: Array<{
      transcript_id: string;
      speaker_id: string;
      speaker_display_name: string;
      src_lang: Language;
      source_text: string;
      created_at: string;
    }>;
  }
>;

export type ParticipantJoinedEvent = WsEnvelope<
  "participant.joined",
  {
    participant_id: string;
    display_name: string;
    language: Language;
    status: ParticipantSnapshot["status"];
    joined_at: string;
  }
>;

export type ParticipantUpdatedEvent = WsEnvelope<
  "participant.updated",
  {
    participant_id: string;
    display_name: string;
    language: Language;
    status: ParticipantSnapshot["status"];
  }
>;

export type ParticipantLeftEvent = WsEnvelope<
  "participant.left",
  {
    participant_id: string;
    left_at: string;
  }
>;

export interface TranscriptPayload {
  transcript_id: string;
  speaker: {
    participant_id: string;
    display_name: string;
    source_language: Language;
  };
  listener: {
    participant_id: string;
    target_language: Language;
  };
  source_text: string;
  translated_text: string;
  audio_track_name: string | null;
  fallback_used: boolean;
  is_final: boolean;
  latency_ms?: number;
}

export type TranscriptPartialEvent = WsEnvelope<
  "transcript.partial",
  TranscriptPayload
>;

export type TranscriptFinalEvent = WsEnvelope<"transcript.final", TranscriptPayload>;

export type InterpreterStatusValue =
  | "idle"
  | "capturing"
  | "translating"
  | "playing"
  | "fallback_text_only"
  | "error";

export type InterpreterStatusEvent = WsEnvelope<
  "interpreter.status",
  {
    speaker_id: string;
    target_language: Language;
    status: InterpreterStatusValue;
    fallback_used: boolean;
    message: string | null;
  }
>;

export type PongEvent = WsEnvelope<
  "pong",
  {
    client_time: string;
    server_time: string;
  }
>;

export type ErrorEvent = WsEnvelope<
  "error",
  {
    code: string;
    message: string;
  }
>;

export type ServerEvent =
  | RoomSnapshotEvent
  | ParticipantJoinedEvent
  | ParticipantUpdatedEvent
  | ParticipantLeftEvent
  | TranscriptPartialEvent
  | TranscriptFinalEvent
  | InterpreterStatusEvent
  | PongEvent
  | ErrorEvent;

export type PingMessage = WsEnvelope<
  "ping",
  {
    client_time: string;
  }
>;

export type SetLanguageMessage = WsEnvelope<
  "set_language",
  {
    language: Language;
  }
>;

export type ClientMessage = PingMessage | SetLanguageMessage;
