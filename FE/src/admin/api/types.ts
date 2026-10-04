// Mirrors BE/server/service/admin/schemas.py — keep both in sync.

export type HealthStatus = "healthy" | "degraded" | "down" | "unknown";
export type RoomStatus = "live" | "empty" | "error" | "expired";
export type AiMode = "voice_text" | "text_only" | "captions" | "summary_capture" | "off";
export type MeetingStatus = "live" | "ended";
export type Severity = "info" | "warning" | "error";
export type StageStatus = "ok" | "failed" | "warning" | "skipped" | "pending";
export type WindowKey = "15m" | "1h" | "24h" | "7d" | "30d";

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

/** Admin identity from /api/admin/auth/login and /api/admin/auth/me (cookie session). */
export interface AdminIdentityPayload {
  id: string;
  username: string;
  display_name?: string | null;
}

export interface AdminAuthResponse {
  admin: AdminIdentityPayload;
  expires_at?: string | null;
}

export interface HealthComponent {
  key: string;
  label: string;
  status: HealthStatus;
  detail: string | null;
}

export interface SystemHealth {
  checked_at: string;
  overall: HealthStatus;
  components: HealthComponent[];
}

export interface StageHealth {
  status: HealthStatus;
  reason: string | null;
}

export interface AiHealth {
  window_minutes: number;
  stt: StageHealth;
  translation: StageHealth;
  voice: StageHealth;
  summary: StageHealth;
}

export interface LiveRoomRow {
  room_id: string;
  state: string;
  status: RoomStatus;
  room_languages: string[];
  participants_online: number;
  participants_total: number;
  ai_mode: AiMode;
  brse_enabled: boolean;
  brse_state: string | null;
  runtime_attached: boolean | null;
  created_at: string | null;
  activated_at: string | null;
  expires_at: string | null;
  seconds_left: number | null;
  recent_error_count: number;
  last_error_at: string | null;
  /** Access type only — the room password is never sent to the admin portal. */
  password_protected?: boolean;
}

export interface LiveRoomsResponse extends Page<LiveRoomRow> {
  counts_by_status: Partial<Record<RoomStatus, number>>;
  runtime_online: boolean | null;
}

export interface ParticipantMedia {
  connection: string | null;
  microphone: string | null;
  camera: string | null;
  screen_share: string | null;
}

export interface LiveParticipant {
  participant_id: string;
  display_name: string;
  language: string;
  kind: string;
  is_virtual: boolean;
  status: string;
  ws_connected: boolean;
  media_connected: boolean;
  joined_at: string | null;
  last_seen_at: string | null;
  is_screen_sharing: boolean;
  media: ParticipantMedia | null;
}

export interface SpeakerAiStatus {
  speaker_id: string;
  speaker_name: string | null;
  status: string | null;
  source_language: string | null;
  target_language: string | null;
  pending_relay_count: number | null;
  overlap_level: string | null;
  audience_count: number | null;
  message: string | null;
  updated_at: string | null;
}

export interface LatencySummary {
  samples: number;
  avg: number | null;
  p50: number | null;
  p95: number | null;
  p99: number | null;
}

export interface RoomBrseState {
  enabled: boolean;
  ai_mode: AiMode;
  runtime_attached: boolean | null;
  state: string | null;
  current_speaker_id: string | null;
  current_speaker_name: string | null;
  queue_depth: number | null;
  speakers: SpeakerAiStatus[];
  latency: {
    last?: Record<string, number>;
    stt_ms?: LatencySummary;
    first_text_ms?: LatencySummary;
    first_audio_ms?: LatencySummary;
    total_ms?: LatencySummary;
  };
  last_success_at: string | null;
  last_error: { occurred_at: string | null; code: string | null; issue_code: string | null; message: string | null } | null;
  output_mode_downgrade_reason: string | null;
  audio_suppressed_reason: string | null;
}

export interface LiveRoomDetail {
  room: LiveRoomRow;
  participants: LiveParticipant[];
  media_source: "livekit" | "unavailable";
  brse: RoomBrseState;
}

export interface TraceStage {
  key: string;
  label: string;
  status: StageStatus;
  ms: number | null;
  note: string | null;
}

export interface TimelineItem {
  event_id: string;
  event_type: "relay_trace" | "ai_error" | string;
  occurred_at: string | null;
  room_id: string | null;
  utterance_id: string | null;
  speaker_id: string | null;
  speaker_name: string | null;
  src_lang: string | null;
  target_lang: string | null;
  outcome: string | null;
  reason: string | null;
  issue_code: string | null;
  severity: Severity | null;
  code: string | null;
  message: string | null;
  relay_style: string | null;
  stages: TraceStage[];
  metrics: Record<string, number>;
  source_text: string | null;
  relay_text: string | null;
}

export interface TimelineResponse {
  items: TimelineItem[];
  source: "live" | "history";
}

export type TranscriptKind = "source" | "relay" | "translated" | "chat" | "system";

export interface TranscriptLine {
  id: string;
  kind: TranscriptKind;
  created_at: string | null;
  speaker_id: string | null;
  speaker_name: string | null;
  language: string | null;
  target_language: string | null;
  text: string;
  source_text: string | null;
  translations: Array<{ language: string; text: string }>;
}

export interface TranscriptResponse {
  items: TranscriptLine[];
  limit_note: string | null;
}

export interface Kpi {
  value: number | null;
  previous: number | null;
  available: boolean;
  note: string | null;
}

export interface IssueOccurrence {
  event_id: string;
  occurred_at: string | null;
  room_id: string | null;
  issue_code: string;
  title: string;
  severity: Severity;
  speaker_name: string | null;
  language_pair: string | null;
  detail: string | null;
}

export interface OverviewResponse {
  generated_at: string;
  history_available: boolean;
  kpis: Record<string, Kpi>;
  live_rooms: LiveRoomRow[];
  system_health: SystemHealth;
  ai_health: AiHealth;
  recent_issues: IssueOccurrence[];
}

export interface MeetingRow {
  room_id: string;
  status: MeetingStatus;
  end_reason: string | null;
  created_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  room_languages: string[];
  participant_count: number;
  ai_mode: AiMode;
  final_summary_status: string | null;
  live_summary_status: string | null;
  password_protected?: boolean;
}

export interface SummaryMeta {
  status?: string | null;
  summary_language?: string | null;
  generated_at?: string | null;
  created_at?: string | null;
  trigger_reason?: string | null;
}

export interface MeetingDetail {
  meeting: MeetingRow;
  activated_at: string | null;
  expires_at: string | null;
  brse_mode: string | null;
  brse_output_mode: string | null;
  counts: Record<"source" | "relay" | "translated" | "chat" | "messages" | "participants", number>;
  summaries: { final: SummaryMeta | null; interim: SummaryMeta | null };
  is_live_in_runtime_store: boolean;
}

export interface RelayRow {
  id: string;
  created_at: string | null;
  utterance_id: string | null;
  speaker_name: string | null;
  source_language: string | null;
  target_language: string | null;
  original: string | null;
  translation: string;
  relay_style: string | null;
  delivery_state: string | null;
  delivery_reason: string | null;
  latency_ms: number | null;
  voice_delivered: boolean | null;
}

export interface MeetingParticipantRow {
  participant_id: string;
  display_name: string | null;
  language: string | null;
  kind: string | null;
  is_virtual: boolean;
  first_joined_at: string | null;
  last_joined_at: string | null;
  last_left_at: string | null;
  join_count: number;
}

export interface SummaryDocument {
  summary_type: "interim" | "final";
  status: string;
  summary_language: string | null;
  created_at: string | null;
  generated_at: string | null;
  updated_at: string | null;
  trigger_reason: string | null;
  error: string | null;
  summary_text: string | null;
  key_points: string[];
  decisions: string[];
  action_items: string[];
  action_item_details: Array<{ text: string; owner: string | null; due: string | null }>;
  risks_blockers: string[];
  open_questions: string[];
  next_steps: string[];
  participant_highlights: Array<{ participant_id: string | null; display_name: string | null; summary: string }>;
  source_stats: Record<string, number | boolean | string | null>;
}

export interface MeetingSummaries {
  final: SummaryDocument | null;
  interim: SummaryDocument | null;
}

export interface StageStats {
  requests: number;
  success: number;
  errors: number;
  success_rate: number | null;
  error_rate: number | null;
  latency: LatencySummary;
  error_breakdown: Array<{ reason: string; count: number }>;
}

export interface SummaryStats {
  requests: number;
  completed: number;
  failed: number;
  skipped: number;
  pending: number;
  failure_rate: number | null;
  latency: LatencySummary;
  by_type: Record<string, Record<string, number>>;
}

export interface LanguagePairStats {
  pair: string;
  source_language: string;
  target_language: string;
  relays: number;
  delivered: number;
  errors: number;
  success_rate: number | null;
  error_rate: number | null;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  latency_samples: number;
}

export interface AiMetricsResponse {
  window: WindowKey;
  range_start: string;
  range_end: string;
  sample_limit: number;
  sampled: number;
  truncated: boolean;
  history_available: boolean;
  stages: Record<"stt" | "translation" | "voice" | "delivery", StageStats>;
  summary: SummaryStats;
  language_pairs: LanguagePairStats[];
  health: AiHealth;
  percentile_min_samples: Record<string, number>;
}

export interface IssueAggregate {
  code: string;
  title: string;
  stage: string;
  severity: Severity;
  description: string;
  occurrences: number;
  affected_rooms: number;
  first_at: string | null;
  latest_at: string | null;
  top_language_pair: string | null;
}

export interface IssuesResponse {
  window: WindowKey;
  history_available: boolean;
  truncated: boolean;
  items: IssueAggregate[];
}

export interface IssueDetailResponse {
  window: WindowKey;
  issue: IssueAggregate;
  occurrences: Page<IssueOccurrence>;
}

export interface AnalyticsResponse {
  range_start: string;
  range_end: string;
  history_available: boolean;
  truncated: boolean;
  totals: Record<string, number | null>;
  meetings_over_time: Array<{ date: string; meetings: number }>;
  language_distribution: Array<{ key: string; label: string; count: number }>;
  ai_mode_usage: Array<{ mode: AiMode; count: number }>;
  feature_usage: Record<string, Kpi>;
}

export interface ConfigItem {
  key: string;
  label: string;
  value: string | number | boolean | null;
  unit: string | null;
  source: string;
  note: string | null;
}

export interface AdminConfigResponse {
  editable: boolean;
  room: ConfigItem[];
  ai: ConfigItem[];
  languages: Array<{ code: string; label: string; enabled: boolean; source: string }>;
  notifications: Array<{ event: string; label: string; supported: boolean; enabled: boolean; channel: string | null }>;
  operations: ConfigItem[];
}

// ── Meeting archives, recordings, retention ──────────────────────────────

export type ArchiveStatus =
  | "open"
  | "finalizing"
  | "processing_recording"
  | "ready"
  | "partial"
  | "failed"
  | "deleting"
  | "deleted";

export interface ArchiveRecordingSummary {
  status: "none" | "processing" | "ready" | "failed" | "partial";
  count: number;
  ready: number;
  failed: number;
  pending: number;
  total_bytes: number;
  total_duration_seconds: number;
}

export interface ArchiveRow {
  archive_id: string;
  room_id: string;
  status: ArchiveStatus;
  storage: "s3" | "none" | null;
  room_languages: string[];
  meeting_started_at: string | null;
  ended_at: string | null;
  participant_count: number | null;
  recording: ArchiveRecordingSummary;
  retention_days: number;
  retention_source: "default" | "custom";
  default_retention_days_snapshot: number | null;
  retention_override_days: number | null;
  expires_at: string | null;
  created_at: string | null;
  finalized_at: string | null;
  deleted_at: string | null;
  deletion_reason: string | null;
  error_code: string | null;
}

export interface ArchiveListResponse extends Page<ArchiveRow> {
  default_retention_days: number;
  storage_configured: boolean;
  recording_available: boolean;
}

export interface AdminRecordingSegment {
  recording_id: string;
  status: string;
  requested_at: string | null;
  started_at: string | null;
  stopped_at: string | null;
  duration_seconds: number | null;
  size_bytes: number | null;
  started_by: { participant_id: string | null; display_name: string | null };
  stopped_by?: string | null;
  stop_reason: string | null;
  error_code: string | null;
  s3_key: string | null;
  provider_recording_id: string | null;
}

export interface ArchiveDetailResponse {
  archive: ArchiveRow;
  recordings: AdminRecordingSegment[];
  files: Array<{ name: string; key: string | null; size: number | null }>;
  s3_bucket: string | null;
  s3_prefix: string | null;
  system_default_retention_days: number;
  storage_bytes: number;
}

export interface RetentionSettings {
  default_retention_days: number;
  updated_at: string | null;
  updated_by: string | null;
  source: "admin" | "config";
}
