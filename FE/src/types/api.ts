export type Language =
  | "vi"
  | "en"
  | "ja"
  | "zh"
  | "ko"
  | "fr"
  | "es"
  | "auto";
export type SelectableLanguage = Exclude<Language, "auto">;
export type MeetingLanguage = SelectableLanguage;

export type RoomState = "created" | "active" | "empty";
export type SameLanguagePolicy = "human_passthrough" | "muted";
export type BrseMode = "relay" | "silent_summary";
export type MeetingMode = "direct_translation" | "brse_relay" | "brse_silent_summary";
export type InterpreterMode = "per_listener" | "brse_participant";
export type ParticipantKind = "human" | "virtual_brse";
export type ScreenShareSource = "screen_share";
export type MeetingSummaryType = "interim" | "final";
export type MeetingSummaryStatus = "pending" | "completed" | "skipped" | "failed";
export type MeetingAudioModel =
  | "translated_audio_first"
  | "brse_participant_audio";
export type CrossLanguageRemoteAudioPolicy =
  | "interpreter_track"
  | "human_original_plus_brse";
export type CanonicalRemoteAudioPolicy =
  | "interpreter_track_for_cross_language"
  | "human_original_track";
export type AiRelayAudioPolicy =
  | "listener_private_track"
  | "virtual_participant_track";

export type ParticipantStatus =
  | "joining"
  | "connected"
  | "reconnecting"
  | "disconnected";

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    request_id?: string;
    details?: Record<string, unknown>;
  };
}

export interface AudioRouting {
  model: MeetingAudioModel;
  cross_language_remote_audio: CrossLanguageRemoteAudioPolicy;
  canonical_remote_audio: CanonicalRemoteAudioPolicy;
  same_language_policy: SameLanguagePolicy;
  ai_relay_audio?: AiRelayAudioPolicy;
  interpreter_mode?: InterpreterMode;
  bridge_strategy?: "speaker_language_map";
  relay_language_map?: Partial<Record<SelectableLanguage, SelectableLanguage>>;
  virtual_participant_id?: string;
}

export interface AudioOutputTrackDescriptor {
  listener_id?: string;
  track_name: string | null;
  track_sid?: string;
  source_language?: Language | null;
  target_language?: Language | null;
  track_available?: boolean;
  authoritative?: boolean;
  mode?: "interpreter_track" | "virtual_participant_track";
  participant_id?: string;
  participant_kind?: ParticipantKind;
  livekit_identity?: string | null;
}

export interface AudioOutputDescriptor {
  model: MeetingAudioModel;
  mode: "interpreter_track" | "virtual_participant_track";
  canonical: boolean;
  track_available?: boolean;
  track_name: string | null;
  speaker_id?: string | null;
  listener_id?: string;
  listener_ids?: string[];
  audience_participant_ids?: string[];
  source_language?: Language | null;
  target_language?: Language | null;
  same_language_policy?: SameLanguagePolicy;
  participant_id?: string;
  participant_kind?: ParticipantKind;
  livekit_identity?: string | null;
  track?: AudioOutputTrackDescriptor;
  tracks?: AudioOutputTrackDescriptor[];
}

export interface ParticipantReference {
  participant_id: string;
  display_name: string;
  language: Language;
  source_language?: Language;
  kind?: ParticipantKind;
  is_virtual?: boolean;
  livekit_identity?: string | null;
}

export interface RelayTargetReference {
  target_language: Language;
  participant_ids: string[];
}

export interface RoomSummary {
  room_id: string;
  state: RoomState;
  created_at: string;
  expires_at: string;
  brse_enabled?: boolean;
  participant_limit: number | null;
  supported_languages: Language[];
  meeting_languages?: MeetingLanguage[];
  meeting_mode?: MeetingMode;
  interpreter_mode?: InterpreterMode;
  audio_routing?: AudioRouting;
}

export interface CreateRoomRequest {
  meeting_languages: [MeetingLanguage, MeetingLanguage];
  brse_enabled?: boolean;
  brse_mode?: BrseMode;
}

export interface CreateRoomResponse {
  room: RoomSummary;
  join: {
    api_path: string;
    share_url: string;
  };
}

export interface ParticipantSnapshot {
  participant_id: string;
  display_name: string;
  language: Language;
  status: ParticipantStatus;
  joined_at?: string;
  kind?: ParticipantKind;
  is_virtual?: boolean;
  livekit_identity?: string | null;
  metadata?: Record<string, unknown>;
  is_screen_sharing?: boolean;
  screen_share?: ScreenShareTrackInfo | null;
  is_host?: boolean;
  muted_by_host?: boolean;
}

export interface ScreenShareTrackInfo {
  active: boolean;
  source: ScreenShareSource;
  track_sid?: string | null;
  track_name?: string | null;
  started_at: string;
}

export interface RecentTranscriptSnapshot {
  transcript_id: string;
  utterance_id?: string | null;
  kind?: "source" | "translated" | "relay";
  speaker_id: string;
  speaker_display_name: string;
  speaker_language?: Language;
  src_lang: Language;
  text?: string;
  source_text: string;
  is_final?: boolean;
  fallback_used?: boolean;
  translated_text?: string | null;
  brse_text?: string | null;
  target_lang?: Language | null;
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
}

export interface RoomSnapshotResponse {
  room: RoomSummary & {
    participant_count: number;
    host_participant_id?: string | null;
  };
  participants: ParticipantSnapshot[];
  recent_transcripts: RecentTranscriptSnapshot[];
  recent_messages?: ChatMessage[];
}

export interface JoinRoomRequest {
  display_name: string;
  language: MeetingLanguage;
  client: {
    sdk: "web";
    version: string;
  };
}

// ─── Test session types ───────────────────────────────────────────────────────

export type MicTestStatus = "created" | "active" | "stopped" | "error";
export type TranslationTestStatus =
  | "created"
  | "listening"
  | "translating"
  | "completed"
  | "error";

export interface MicTestSessionResponse {
  session_id: string;
  status: MicTestStatus;
  created_at: string;
  expires_at: string;
  websocket: {
    url: string;
  };
}

export interface CreateTranslationTestRequest {
  src_lang: Language;
  tgt_lang: Language;
}

export interface TranslationTestSessionResponse {
  session_id: string;
  src_lang: Language;
  tgt_lang: Language;
  status: TranslationTestStatus;
  created_at: string;
  expires_at: string;
  websocket: {
    url: string;
  };
}

// ─────────────────────────────────────────────────────────────────────────────

export interface JoinRoomResponse {
  room: RoomSummary;
  participant: {
    participant_id: string;
    session_id: string;
    display_name: string;
    language: MeetingLanguage;
  };
  room_token: {
    token: string;
    expires_at: string;
  };
  websocket: {
    url: string;
  };
  livekit: {
    url: string;
    room_name: string;
    participant_identity: string;
    participant_name: string;
    token: string;
  };
  snapshot: {
    participants: ParticipantSnapshot[];
    recent_transcripts: RecentTranscriptSnapshot[];
    recent_messages?: ChatMessage[];
  };
}

export interface ScreenShareStartRequest {
  track_sid?: string;
  track_name?: string;
  source?: ScreenShareSource;
}

export interface ScreenShareStateResponse {
  participant_id: string;
  display_name: string;
  active: boolean;
  timestamp: string;
  track_sid?: string | null;
  track_name?: string | null;
}

// ─── Meeting summary types ──────────────────────────────────────────────────

export interface MeetingSummaryActionItem {
  text: string;
  owner?: string | null;
  due?: string | null;
}

export interface MeetingSummaryParticipantItem {
  participant_id?: string | null;
  display_name?: string | null;
  summary: string;
}

export interface MeetingSummarySourceWindow {
  source?: "redis_snapshot" | "mongodb_archive" | string;
  from?: string | null;
  to?: string | null;
  message_count?: number;
  max_messages?: number;
  [key: string]: unknown;
}

export interface MeetingSummarySourceStats {
  transcript_count?: number;
  source_transcript_count?: number;
  relay_count?: number;
  translated_transcript_count?: number;
  chat_count?: number;
  included_message_count?: number;
  truncated?: boolean;
  [key: string]: unknown;
}

export interface MeetingSummaryResponse {
  room_id: string;
  summary_id?: string | null;
  summary_type?: MeetingSummaryType | null;
  status?: MeetingSummaryStatus | null;
  created_at?: string | null;
  generated_at?: string | null;
  summary_language?: string | null;
  summary_text?: string | null;
  highlights?: string[] | null;
  decisions?: string[] | null;
  action_items?: MeetingSummaryActionItem[] | null;
  participant_summary?: MeetingSummaryParticipantItem[] | null;
  duration_seconds?: number | null;
  source_window?: MeetingSummarySourceWindow | null;
  source_stats?: MeetingSummarySourceStats | null;
  error?: string | null;
}

// ─── Chat types ───────────────────────────────────────────────────────────────

export type ChatTranslationMode = "original_only" | "translate";

export interface ChatTranslation {
  language: MeetingLanguage;
  text: string;
}

export interface ChatMessage {
  message_id: string;
  client_event_id?: string | null;
  sender_id?: string;
  sender_display_name?: string;
  sender_language?: Language | null;
  participant_id?: string;
  display_name?: string;
  language?: Language | null;
  text: string;
  sent_at?: string;
  created_at?: string;
  // Translation fields — additive, absent in old messages means original_only
  translation_mode?: ChatTranslationMode | null;
  translations?: ChatTranslation[] | null;
}

export type ChatDeliveryStatus = "sending" | "sent" | "failed";

export interface RoomChatMessage {
  message_id: string;
  client_event_id?: string | null;
  participant_id: string;
  display_name: string;
  text: string;
  created_at: string;
  sender_language?: Language | null;
  delivery_status?: ChatDeliveryStatus;
  // Translation fields — carried through from ChatMessage
  translation_mode?: ChatTranslationMode;
  translations?: ChatTranslation[];
}

// ─── Moderation types ─────────────────────────────────────────────────────────

export interface MuteParticipantRequest {
  target_participant_id: string;
}

export interface MuteParticipantResponse {
  participant_id: string;
  muted_by_host: boolean;
  timestamp: string;
}
