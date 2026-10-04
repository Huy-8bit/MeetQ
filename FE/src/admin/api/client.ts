import { requestJson } from "../../lib/api";
import type {
  ArchiveDetailResponse,
  ArchiveListResponse,
  ArchiveRow,
  RetentionSettings,
  AdminAuthResponse,
  AdminConfigResponse,
  AiMetricsResponse,
  AnalyticsResponse,
  IssueDetailResponse,
  IssuesResponse,
  LiveRoomDetail,
  LiveRoomsResponse,
  MeetingDetail,
  MeetingParticipantRow,
  MeetingRow,
  MeetingSummaries,
  OverviewResponse,
  Page,
  RelayRow,
  SystemHealth,
  TimelineResponse,
  TranscriptLine,
  TranscriptResponse,
  WindowKey,
} from "./types";

/** Sends an authenticated admin request. Supplied by AdminSessionProvider. */
export type AdminRequest = <T>(path: string, init?: RequestInit) => Promise<T>;

export type QueryParams = Record<string, string | number | boolean | null | undefined>;

export function withQuery(path: string, params: QueryParams = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

/** Admin realm session endpoints. The session is an HttpOnly cookie, separate from the user session. */
export const ADMIN_AUTH_PATHS = {
  login: "/api/admin/auth/login",
  me: "/api/admin/auth/me",
  logout: "/api/admin/auth/logout",
} as const;

export function adminSignIn(username: string, password: string): Promise<AdminAuthResponse> {
  return requestJson<AdminAuthResponse>(ADMIN_AUTH_PATHS.login, {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function fetchAdminMe(): Promise<AdminAuthResponse> {
  return requestJson<AdminAuthResponse>(ADMIN_AUTH_PATHS.me);
}

export function adminSignOut(): Promise<void> {
  return requestJson<void>(ADMIN_AUTH_PATHS.logout, { method: "POST", body: "{}" });
}

const enc = encodeURIComponent;

export function adminEndpoints(request: AdminRequest) {
  return {
    health: () => request<SystemHealth>("/api/admin/health"),
    overview: (todayStart: string) =>
      request<OverviewResponse>(withQuery("/api/admin/overview", { today_start: todayStart })),
    liveRooms: (params: QueryParams) => request<LiveRoomsResponse>(withQuery("/api/admin/rooms", params)),
    liveRoom: (roomId: string) => request<LiveRoomDetail>(`/api/admin/rooms/${enc(roomId)}`),
    roomTimeline: (roomId: string, limit = 50) =>
      request<TimelineResponse>(withQuery(`/api/admin/rooms/${enc(roomId)}/timeline`, { limit })),
    roomTranscript: (roomId: string, kind: string) =>
      request<TranscriptResponse>(withQuery(`/api/admin/rooms/${enc(roomId)}/transcript`, { kind })),
    meetings: (params: QueryParams) => request<Page<MeetingRow>>(withQuery("/api/admin/meetings", params)),
    meeting: (roomId: string) => request<MeetingDetail>(`/api/admin/meetings/${enc(roomId)}`),
    meetingTranscripts: (roomId: string, page: number) =>
      request<Page<TranscriptLine>>(withQuery(`/api/admin/meetings/${enc(roomId)}/transcripts`, { page })),
    meetingRelays: (roomId: string, page: number) =>
      request<Page<RelayRow>>(withQuery(`/api/admin/meetings/${enc(roomId)}/relays`, { page })),
    meetingChat: (roomId: string, page: number) =>
      request<Page<TranscriptLine>>(withQuery(`/api/admin/meetings/${enc(roomId)}/chat`, { page })),
    meetingSummaries: (roomId: string) => request<MeetingSummaries>(`/api/admin/meetings/${enc(roomId)}/summaries`),
    regenerateFinalSummary: (roomId: string, language: string | null) =>
      request<unknown>(`/api/admin/meetings/${enc(roomId)}/summaries/final`, {
        method: "POST",
        body: JSON.stringify({ language }),
      }),
    meetingParticipants: (roomId: string) =>
      request<MeetingParticipantRow[]>(`/api/admin/meetings/${enc(roomId)}/participants`),
    aiMetrics: (window: WindowKey) => request<AiMetricsResponse>(withQuery("/api/admin/ai/metrics", { window })),
    issues: (window: WindowKey, includeInfo: boolean) =>
      request<IssuesResponse>(withQuery("/api/admin/issues", { window, include_info: includeInfo })),
    issue: (code: string, window: WindowKey, page: number) =>
      request<IssueDetailResponse>(withQuery(`/api/admin/issues/${enc(code)}`, { window, page })),
    analytics: (from: string, to: string, tzOffsetMinutes: number) =>
      request<AnalyticsResponse>(
        withQuery("/api/admin/analytics", { from, to, tz_offset_minutes: tzOffsetMinutes }),
      ),
    config: () => request<AdminConfigResponse>("/api/admin/config"),
    archives: (params: QueryParams) => request<ArchiveListResponse>(withQuery("/api/admin/recordings", params)),
    archive: (archiveId: string) => request<ArchiveDetailResponse>(`/api/admin/archives/${enc(archiveId)}`),
    retentionSettings: () => request<RetentionSettings>("/api/admin/settings/retention"),
    updateRetentionSettings: (days: number) =>
      request<RetentionSettings>("/api/admin/settings/retention", {
        method: "PATCH",
        body: JSON.stringify({ default_retention_days: days }),
      }),
    updateArchiveRetention: (
      archiveId: string,
      body: { retention_days?: number; use_default?: boolean; confirm_expire?: boolean },
    ) =>
      request<{ archive: ArchiveRow }>(`/api/admin/archives/${enc(archiveId)}/retention`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    deleteArchive: (archiveId: string) =>
      request<{ archive: ArchiveRow }>(`/api/admin/archives/${enc(archiveId)}`, {
        method: "DELETE",
        body: JSON.stringify({ confirm: "DELETE" }),
      }),
  };
}

export type AdminEndpoints = ReturnType<typeof adminEndpoints>;
