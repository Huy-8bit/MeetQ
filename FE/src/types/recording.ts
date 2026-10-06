import type { RoomRole } from "./api";
/** Room-level recording state, identical for every participant (server is the source of truth). */
export type RecordingStatus = "starting" | "recording" | "stopping" | "processing" | "ready" | "failed";

export interface RecordingState {
  recording_id: string;
  room_id: string;
  archive_id: string | null;
  status: RecordingStatus;
  requested_at: string | null;
  started_at: string | null;
  stopped_at: string | null;
  duration_seconds: number | null;
  size_bytes: number | null;
  started_by: { participant_id: string | null; display_name: string | null };
  stopped_by?: string | null;
  stop_reason?: string | null;
  error_code: string | null;
  /** Increases with every server-side change; clients keep the highest. */
  version: number;
  /** History views: the recording can be played/downloaded. */
  playable?: boolean;
}

export const ACTIVE_RECORDING_STATUSES: RecordingStatus[] = ["starting", "recording", "stopping"];

export function isRecordingActive(state: RecordingState | null | undefined): state is RecordingState {
  return !!state && ACTIVE_RECORDING_STATUSES.includes(state.status);
}

export type RecordingSummaryStatus = "none" | "processing" | "ready" | "failed" | "partial";

export interface RecordingSummary {
  status: RecordingSummaryStatus;
  count: number;
  ready: number;
  failed: number;
  pending: number;
  total_bytes: number;
  total_duration_seconds: number;
}

export interface MeetingRow {
  room_id: string;
  archive_id: string | null;
  status: string | null;
  meeting_state?: "live" | "ended";
  title?: string | null;
  room_languages: string[];
  created_at?: string | null;
  meeting_started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  participant_count: number | null;
  recording: RecordingSummary;
  summary_status?: string | null;
  expires_at: string | null;
  retention_days: number | null;
  my_role?: RoomRole;
  created_by_me?: boolean;
}

export interface MeetingOverview extends MeetingRow {
  brse_enabled?: boolean | null;
  relay_mode?: string | null;
  password_protected?: boolean;
  host?: string | null;
  co_hosts?: string[];
}

export interface MeetingParticipantRow {
  participant_id: string | null;
  display_name: string | null;
  language: string | null;
  kind: string;
  /** From the persisted membership; null for meetings from before roles existed. */
  role?: RoomRole | null;
  removed?: boolean;
  joined_at: string | null;
  left_at: string | null;
  is_you: boolean;
}

export type MeetingListFilter = "all" | "created" | "recorded" | "summary";
export type MeetingListRange = "all" | "today" | "7d" | "30d";

export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
  prev_cursor: string | null;
}

export interface TranscriptItem {
  message_id: string | null;
  cursor: string;
  kind: string;
  created_at: string | null;
  speaker_name: string | null;
  language: string | null;
  text: string;
  /** Only translations that were produced during the meeting. */
  translations: Array<{ language: string | null; text: string }>;
}

export interface RelayItem {
  message_id: string | null;
  cursor: string;
  created_at: string | null;
  speaker_name: string | null;
  source_language: string | null;
  target_language: string | null;
  source_text: string | null;
  translated_text: string;
}

export interface ChatHistoryItem {
  message_id: string | null;
  cursor: string;
  created_at: string | null;
  sender_name: string | null;
  language: string | null;
  text: string;
  translations: Array<{ language: string; text: string }>;
}

export type SearchSourceType = "transcript" | "relay" | "chat" | "summary";

export interface SearchResultItem {
  meeting_id: string;
  meeting_title: string | null;
  source_type: SearchSourceType;
  /** Summary section ("Decisions", …) for summary results. */
  section: string | null;
  timestamp: string | null;
  speaker: string | null;
  language: string | null;
  /** Compact snippet; `highlights` are [start, end] offsets into it (plain text, no HTML). */
  text: string;
  highlights: Array<[number, number]>;
  source_item_id: string | null;
  /** Opens the transcript/relay/chat list at this item. */
  cursor: string | null;
}

export interface SearchResults extends Paged<SearchResultItem> {
  query: string;
}

export interface MeetingDetailResponse {
  meeting: MeetingOverview;
  recordings: RecordingState[];
  participants: MeetingParticipantRow[];
  counts: { transcript: number; relay: number; chat: number };
  summary: Record<string, unknown> | null;
}

export interface MeetingMessage {
  message_id: string | null;
  kind: string;
  created_at: string | null;
  speaker_name: string | null;
  language: string | null;
  target_language: string | null;
  text: string | null;
  source_text: string | null;
  translated_text: string | null;
  translations: Array<{ language: string; text: string }>;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
