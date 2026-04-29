export type Language = "vi" | "en" | "ja";

export type RoomState = "created" | "active" | "empty";

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

export interface RoomSummary {
  room_id: string;
  state: RoomState;
  created_at: string;
  expires_at: string;
  participant_limit: number;
  supported_languages: Language[];
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
  speaker_id: string;
  speaker_display_name: string;
  src_lang: Language;
  source_text: string;
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
