import type { RecordingState } from "./recording";
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
export type BrseOutputMode = "voice_text" | "text_only";
export type MeetingMode = "direct_translation" | "brse_relay" | "brse_silent_summary";
export type InterpreterMode = "per_listener" | "brse_participant";
export type ParticipantKind = "human" | "virtual_brse";
export type ScreenShareSource = "screen_share";
export type MeetingSummaryType = "interim" | "final";
export type MeetingSummaryStatus = "pending" | "completed" | "skipped" | "failed";
export type MeetingAudioModel =
  | "translated_audio_first"
  | "brse_participant_audio"
  | "brse_text_only_relay"
  | "brse_silent_listener";
export type CrossLanguageRemoteAudioPolicy =
  | "interpreter_track"
  | "human_original_plus_brse"
  | "human_original_only";
export type CanonicalRemoteAudioPolicy =
  | "interpreter_track_for_cross_language"
  | "human_original_track";
export type AiRelayAudioPolicy =
  | "listener_private_track"
  | "virtual_participant_track"
  | "disabled";
export type RelayRouteStrategy =
  | "single_language_source_capture"
  | "two_language_relay"
  | "multi_language_text_caption";

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
  brse_mode?: BrseMode;
  brse_output_mode?: BrseOutputMode;
  cross_language_remote_audio: CrossLanguageRemoteAudioPolicy;
  canonical_remote_audio: CanonicalRemoteAudioPolicy;
  same_language_policy: SameLanguagePolicy;
  ai_relay_audio?: AiRelayAudioPolicy;
  ai_audio_output_enabled?: boolean;
  relay_audio_enabled?: boolean;
  relay_text_enabled?: boolean;
  relay_text_output_enabled?: boolean;
  ai_audio_suppressed_reason?: string | null;
  source_transcript_capture?: boolean;
  relay_transcript_policy?: "publish_realtime" | "source_only_internal";
  interpreter_mode?: InterpreterMode;
  bridge_strategy?: "speaker_language_map" | "participant_language_preference";
  relay_language_map?: Partial<Record<SelectableLanguage, SelectableLanguage>>;
  relay_language_targets?: Partial<Record<SelectableLanguage, SelectableLanguage[]>>;
  requested_brse_output_mode?: BrseOutputMode;
  effective_brse_output_mode?: BrseOutputMode;
  output_mode_downgrade_reason?: string | null;
  room_language_count?: number;
  route_strategy?: RelayRouteStrategy;
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
  mode?: "interpreter_track" | "virtual_participant_track" | "disabled";
  participant_id?: string;
  participant_kind?: ParticipantKind;
  livekit_identity?: string | null;
  output_suppressed?: boolean;
  suppressed_reason?: string | null;
  relay_audio_enabled?: boolean;
  brse_output_mode?: BrseOutputMode;
}

export interface AudioOutputDescriptor {
  model: MeetingAudioModel;
  mode: "interpreter_track" | "virtual_participant_track" | "disabled";
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
  output_suppressed?: boolean;
  suppressed_reason?: string | null;
  relay_audio_enabled?: boolean;
  brse_output_mode?: BrseOutputMode;
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
  brse_mode?: BrseMode;
  brse_output_mode?: BrseOutputMode;
  participant_limit: number | null;
  supported_languages: Language[];
  room_languages?: MeetingLanguage[];
  meeting_languages?: MeetingLanguage[];
  language_a?: MeetingLanguage;
  language_b?: MeetingLanguage;
  meeting_mode?: MeetingMode;
  interpreter_mode?: InterpreterMode;
  audio_routing?: AudioRouting;
  /** Joining needs the meeting password. The password itself is never returned. */
  password_required?: boolean;
  /** Optional title; show `formatMeetingTitle()` when it's empty. */
  title?: string | null;
  /** Locked by the host: nobody new can join. */
  locked?: boolean;
}

export type RoomAccess = "link" | "password";

/** Room roles. The server decides them (by signed-in account); the UI only renders them. */
export type RoomRole = "host" | "co_host" | "participant";

export type RoomPermissionName =
  | "can_manage_ai"
  | "can_manage_recording"
  | "can_mute_participant"
  | "can_remove_participant"
  | "can_manage_room_security"
  | "can_assign_cohost"
  | "can_manage_password"
  | "can_lock_room"
  | "can_extend_room";

export type RoomPermissions = Record<RoomPermissionName, boolean>;

export interface RoomPermissionsResponse {
  room_id: string;
  participant_id: string;
  role: RoomRole;
  enforced: boolean;
  permissions: RoomPermissions;
}

export interface CreateRoomRequest {
  room_languages: MeetingLanguage[];
  meeting_languages?: MeetingLanguage[];
  language_a?: MeetingLanguage;
  language_b?: MeetingLanguage;
  brse_enabled?: boolean;
  brse_mode?: BrseMode;
  brse_output_mode?: BrseOutputMode;
  access?: RoomAccess;
  password?: string;
  title?: string;
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
  /** @deprecated use `role`. */
  is_host?: boolean;
  role?: RoomRole;
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
    /** Active room recording (starting/recording/stopping), shown in the lobby. */
    recording?: RecordingState | null;
    recording_available?: boolean;
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
  /** Only for password-protected rooms; sent in the request body, never in the URL. */
  password?: string;
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
    role?: RoomRole;
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

export type MeetingSummaryActionItemPayload = string | MeetingSummaryActionItem;

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
  total_message_count?: number;
  max_messages?: number;
  selection_strategy?: string;
  [key: string]: unknown;
}

export interface MeetingSummarySourceStats {
  transcript_count?: number;
  source_transcript_count?: number;
  relay_count?: number;
  translated_transcript_count?: number;
  chat_count?: number;
  included_message_count?: number;
  source_char_count?: number;
  source_token_estimate?: number;
  signal_record_count?: number;
  signal_char_count?: number;
  selection_strategy?: string;
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
  key_points?: string[] | null;
  highlights?: string[] | null;
  decisions?: string[] | null;
  action_items?: MeetingSummaryActionItemPayload[] | null;
  action_item_details?: MeetingSummaryActionItem[] | null;
  risks_blockers?: string[] | null;
  open_questions?: string[] | null;
  next_steps?: string[] | null;
  participant_highlights?: MeetingSummaryParticipantItem[] | null;
  participant_summary?: MeetingSummaryParticipantItem[] | null;
  duration_seconds?: number | null;
  source_window?: MeetingSummarySourceWindow | null;
  source_stats?: MeetingSummarySourceStats | null;
  error?: string | null;
}

export type FetchMeetingSummaryResponse = MeetingSummaryResponse;
export type GenerateMeetingSummaryResponse = MeetingSummaryResponse;

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
