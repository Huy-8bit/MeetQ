export type Language = "vi" | "en" | "ja";

export type RoomState = "created" | "active" | "empty";
export type SameLanguagePolicy = "human_passthrough" | "muted";

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
  model: "translated_audio_first";
  cross_language_remote_audio: "interpreter_track";
  canonical_remote_audio: "interpreter_track_for_cross_language";
  same_language_policy: SameLanguagePolicy;
}

export interface RoomSummary {
  room_id: string;
  state: RoomState;
  created_at: string;
  expires_at: string;
  participant_limit: number;
  supported_languages: Language[];
  audio_routing?: AudioRouting;
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
}

export interface RecentTranscriptSnapshot {
  transcript_id: string;
  utterance_id?: string | null;
  kind?: "source" | "translated";
  speaker_id: string;
  speaker_display_name: string;
  speaker_language?: Language;
  src_lang: Language;
  text?: string;
  source_text: string;
  is_final?: boolean;
  fallback_used?: boolean;
  translated_text?: string | null;
  target_lang?: Language | null;
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
}

export interface RoomSnapshotResponse {
  room: RoomSummary & {
    participant_count: number;
  };
  participants: ParticipantSnapshot[];
  recent_transcripts: RecentTranscriptSnapshot[];
}

export interface JoinRoomRequest {
  display_name: string;
  language: Language;
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
    language: Language;
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
  };
}
