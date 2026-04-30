import type {
  AudioRouting,
  Language,
  ParticipantSnapshot,
  SameLanguagePolicy,
} from "./api";

export interface AudioOutputDescriptor {
  model: "translated_audio_first";
  mode: "interpreter_track";
  canonical: boolean;
  track_available?: boolean;
  track_name: string | null;
  speaker_id: string;
  listener_id?: string;
  listener_ids?: string[];
  source_language: Language;
  target_language: Language;
  same_language_policy?: SameLanguagePolicy;
  tracks?: Array<{
    listener_id: string;
    track_name: string;
    track_sid?: string;
    source_language: Language;
    target_language: Language;
    track_available: boolean;
    authoritative: boolean;
    mode: "interpreter_track";
  }>;
}

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
      audio_routing?: AudioRouting;
    };
    participants: ParticipantSnapshot[];
    recent_transcripts: Array<{
      transcript_id: string;
      utterance_id?: string | null;
      kind?: "source" | "translated";
      speaker_id: string;
      speaker_display_name: string;
      speaker_language?: Language;
      src_lang: Language;
      text?: string;
      source_text: string;
      translated_text?: string | null;
      target_lang?: Language | null;
      is_final?: boolean;
      fallback_used?: boolean;
      audio_track_name?: string | null;
      speaker?: {
        participant_id: string;
        display_name: string;
        language?: Language;
        source_language?: Language;
      };
      listener?: {
        participant_id: string;
        target_language: Language;
      };
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
  utterance_id?: string | null;
  kind?: "source" | "translated";
  text?: string;
  src_lang?: Language;
  tgt_lang?: Language | null;
  created_at?: string;
  speaker: {
    participant_id: string;
    display_name: string;
    language?: Language;
    source_language?: Language;
  };
  listener?: {
    participant_id: string;
    target_language: Language;
  };
  source_text?: string;
  translated_text?: string;
  audio_track_name: string | null;
  audio_output?: AudioOutputDescriptor;
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
    source_language?: Language;
    target_language: Language;
    status: InterpreterStatusValue;
    fallback_used: boolean;
    message: string | null;
    audio_track_name?: string | null;
    listener_ids?: string[];
    audio_output?: AudioOutputDescriptor;
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

// ─── Test WebSocket event types ───────────────────────────────────────────────

export interface TestWsEnvelope<TType extends string, TPayload> {
  type: TType;
  session_id: string;
  event_id: string;
  sent_at: string;
  payload: TPayload;
}

// Mic test — server → client
export type MicTestStartedEvent = TestWsEnvelope<
  "mic_test.started",
  { session_id: string; status: "active"; timestamp: string }
>;

export type MicTestLevelEvent = TestWsEnvelope<
  "mic_test.level",
  {
    session_id: string;
    status: "active";
    rms: number;
    peak: number;
    db: number;
    chunk_ms: number;
    timestamp: string;
  }
>;

export type MicTestSilenceEvent = TestWsEnvelope<
  "mic_test.silence",
  { session_id: string; status: "active"; silence_ms: number; timestamp: string }
>;

export type MicTestStoppedEvent = TestWsEnvelope<
  "mic_test.stopped",
  { session_id: string; status: "stopped"; timestamp: string }
>;

export type MicTestErrorEvent = TestWsEnvelope<
  "mic_test.error",
  { session_id: string; code: string; message: string; timestamp: string }
>;

export type MicTestServerEvent =
  | MicTestStartedEvent
  | MicTestLevelEvent
  | MicTestSilenceEvent
  | MicTestStoppedEvent
  | MicTestErrorEvent;

// Translation test — server → client
export type TranslationTestStartedEvent = TestWsEnvelope<
  "translation_test.started",
  {
    session_id: string;
    src_lang: string;
    tgt_lang: string;
    status: "listening";
    timestamp: string;
  }
>;

export type TranslationTestPartialEvent = TestWsEnvelope<
  "translation_test.partial",
  {
    session_id: string;
    src_lang: string;
    tgt_lang: string;
    source_text: string;
    translated_text: string;
    is_final: false;
    timestamp: string;
  }
>;

export type TranslationTestFinalEvent = TestWsEnvelope<
  "translation_test.final",
  {
    session_id: string;
    src_lang: string;
    tgt_lang: string;
    source_text: string;
    translated_text: string;
    is_final: true;
    timestamp: string;
    audio_url?: string | null;
    audio_track_name?: string | null;
  }
>;

export type TranslationTestErrorEvent = TestWsEnvelope<
  "translation_test.error",
  { session_id: string; code: string; message: string; timestamp: string }
>;

export type TranslationTestServerEvent =
  | TranslationTestStartedEvent
  | TranslationTestPartialEvent
  | TranslationTestFinalEvent
  | TranslationTestErrorEvent;

// ─────────────────────────────────────────────────────────────────────────────
