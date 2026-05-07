import type {
  AudioOutputDescriptor,
  AudioRouting,
  ChatMessage,
  ChatTranslationMode,
  InterpreterMode,
  Language,
  MeetingLanguage,
  ParticipantSnapshot,
  ParticipantReference,
  RelayTargetReference,
  ScreenShareSource,
  ScreenShareTrackInfo,
} from "./api";

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
      brse_enabled?: boolean;
      participant_limit: number | null;
      expires_at?: string;
      supported_languages: Language[];
      meeting_languages?: MeetingLanguage[];
      meeting_mode?: "direct_translation" | "brse_relay" | "brse_silent_summary";
      interpreter_mode?: "per_listener" | "brse_participant";
      audio_routing?: AudioRouting;
    };
    participants: ParticipantSnapshot[];
    recent_transcripts: Array<{
      transcript_id: string;
      utterance_id?: string | null;
      kind?: "source" | "translated" | "relay";
      speaker_id: string;
      speaker_display_name: string;
      speaker_language?: Language;
      src_lang: Language;
      text?: string;
      source_text: string;
      translated_text?: string | null;
      brse_text?: string | null;
      target_lang?: Language | null;
      is_final?: boolean;
      fallback_used?: boolean;
      audio_track_name?: string | null;
      audio_output?: AudioOutputDescriptor | null;
      relay_mode?: InterpreterMode | null;
      speaker?: ParticipantReference;
      original_speaker?: ParticipantReference;
      listener?: {
        participant_id: string;
        target_language: Language;
      } | null;
      brse_participant?: ParticipantReference | null;
      relay_target?: RelayTargetReference | null;
      created_at: string;
    }>;
    host_participant_id?: string | null;
    recent_messages?: ChatMessage[];
  }
>;

export type ParticipantJoinedEvent = WsEnvelope<
  "participant.joined",
  {
    participant_id: string;
    session_id?: string;
    display_name: string;
    language: Language;
    status: ParticipantSnapshot["status"];
    joined_at: string;
    left_at?: string | null;
    kind?: ParticipantSnapshot["kind"];
    is_virtual?: boolean;
    livekit_identity?: string | null;
    metadata?: Record<string, unknown>;
    is_screen_sharing?: boolean;
    screen_share?: ScreenShareTrackInfo | null;
    is_host?: boolean;
    muted_by_host?: boolean;
  }
>;

export type ParticipantUpdatedEvent = WsEnvelope<
  "participant.updated",
  {
    participant_id: string;
    session_id?: string;
    display_name: string;
    language: Language;
    status: ParticipantSnapshot["status"];
    joined_at?: string;
    left_at?: string | null;
    kind?: ParticipantSnapshot["kind"];
    is_virtual?: boolean;
    livekit_identity?: string | null;
    metadata?: Record<string, unknown>;
    is_screen_sharing?: boolean;
    screen_share?: ScreenShareTrackInfo | null;
    is_host?: boolean;
    muted_by_host?: boolean;
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
  kind?: "source" | "translated" | "relay";
  text?: string;
  src_lang?: Language;
  tgt_lang?: Language | null;
  created_at?: string;
  speaker: ParticipantReference;
  listener?: {
    participant_id: string;
    target_language: Language;
  } | null;
  original_speaker?: ParticipantReference | null;
  brse_participant?: ParticipantReference | null;
  relay_target?: RelayTargetReference | null;
  source_text?: string;
  translated_text?: string;
  brse_text?: string;
  audio_track_name: string | null;
  audio_output?: AudioOutputDescriptor | null;
  relay_mode?: InterpreterMode | null;
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
    audience_participant_ids?: string[];
    relay_mode?: InterpreterMode | null;
    brse_participant?: ParticipantReference | null;
    audio_output?: AudioOutputDescriptor | null;
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

export type ScreenShareStartedEvent = WsEnvelope<
  "screen_share.started",
  {
    participant_id: string;
    display_name: string;
    track_sid?: string | null;
    track_name?: string | null;
    active: true;
    timestamp: string;
    source: ScreenShareSource;
  }
>;

export type ScreenShareStoppedEvent = WsEnvelope<
  "screen_share.stopped",
  {
    participant_id: string;
    display_name: string;
    track_sid?: string | null;
    track_name?: string | null;
    active: false;
    timestamp: string;
    reason?: string;
    source: ScreenShareSource;
  }
>;

export type RoomBrseUpdatedEvent = WsEnvelope<
  "room.brse_updated",
  {
    room_id: string;
    brse_enabled: boolean;
    timestamp: string;
    changed_by?: string | null;
    reason?: string | null;
  }
>;

export type RoomExpiredEvent = WsEnvelope<
  "room.expired",
  {
    room_id: string;
    expired_at: string;
    reason?: string | null;
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
  | ScreenShareStartedEvent
  | ScreenShareStoppedEvent
  | RoomBrseUpdatedEvent
  | RoomExpiredEvent
  | ChatMessageEvent
  | RoomHostChangedEvent
  | ModerationForceMutedEvent
  | ModerationParticipantMutedEvent
  | PongEvent
  | ErrorEvent;

// ─── Chat events ──────────────────────────────────────────────────────────────

export type ChatMessageEvent = WsEnvelope<
  "chat.message",
  ChatMessage
>;

// ─── Host events ──────────────────────────────────────────────────────────────

export type RoomHostChangedEvent = WsEnvelope<
  "room.host_changed",
  {
    previous_host_id: string | null;
    new_host_id: string;
    new_host_display_name: string;
    reason: string;
  }
>;

// ─── Moderation events ────────────────────────────────────────────────────────

export type ModerationForceMutedEvent = WsEnvelope<
  "moderation.force_muted",
  {
    participant_id: string;
    muted_by: string;
    reason?: string;
  }
>;

export type ModerationParticipantMutedEvent = WsEnvelope<
  "moderation.participant_muted",
  {
    participant_id: string;
    muted_by_host: boolean;
    muted_by: string;
  }
>;

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

export type ScreenShareStartMessage = WsEnvelope<
  "screen_share.start",
  {
    track_sid?: string;
    track_name?: string;
    source?: ScreenShareSource;
  }
>;

export type ScreenShareStopMessage = WsEnvelope<
  "screen_share.stop",
  Record<string, never>
>;

export type RoomBrseEnableMessage = WsEnvelope<
  "room.brse.enable",
  Record<string, never>
>;

export type RoomBrseDisableMessage = WsEnvelope<
  "room.brse.disable",
  Record<string, never>
>;

export type ClientMessage =
  | PingMessage
  | SetLanguageMessage
  | ScreenShareStartMessage
  | ScreenShareStopMessage
  | RoomBrseEnableMessage
  | RoomBrseDisableMessage
  | ChatSendMessage
  | ModerationMuteMessage;

// ─── Chat client messages ─────────────────────────────────────────────────────

export type ChatSendMessage = WsEnvelope<
  "chat.send",
  {
    text: string;
    translation_mode?: ChatTranslationMode;
  }
>;

// ─── Moderation client messages ───────────────────────────────────────────────

export type ModerationMuteMessage = WsEnvelope<
  "moderation.mute_participant",
  {
    target_participant_id: string;
  }
>;

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
