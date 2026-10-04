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
  status: string;
  room_languages: string[];
  meeting_started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  participant_count: number | null;
  recording: RecordingSummary;
  expires_at: string | null;
  retention_days: number | null;
}

export interface MeetingParticipantRow {
  participant_id: string | null;
  display_name: string | null;
  language: string | null;
  kind: string;
  joined_at: string | null;
  left_at: string | null;
  is_you: boolean;
}

export interface MeetingDetailResponse {
  meeting: MeetingRow;
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
