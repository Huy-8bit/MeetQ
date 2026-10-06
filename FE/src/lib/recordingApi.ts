import { requestJson } from "./api";
import type {
  ChatHistoryItem,
  CursorPage,
  MeetingDetailResponse,
  MeetingListFilter,
  MeetingListRange,
  MeetingMessage,
  MeetingRow,
  Paged,
  RecordingState,
  RelayItem,
  SearchResults,
  TranscriptItem,
} from "../types/recording";

export interface MeetingListQuery {
  page?: number;
  pageSize?: number;
  q?: string;
  filter?: MeetingListFilter;
  range?: MeetingListRange;
}

export interface ContentQuery {
  cursor?: string | null;
  before?: string | null;
  /** Inclusive: open the list at a search result. */
  start?: string | null;
  limit?: number;
}

function queryString(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

const enc = encodeURIComponent;

function roomAuth(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

/** In-room recording control (room token + signed-in user) and meeting history. */
export const recordingApi = {
  start(roomId: string, roomToken: string) {
    return requestJson<{ recording: RecordingState }>(`/api/rooms/${enc(roomId)}/recordings`, {
      method: "POST",
      headers: roomAuth(roomToken),
      body: "{}",
    });
  },

  stop(roomId: string, recordingId: string, roomToken: string) {
    return requestJson<{ recording: RecordingState }>(
      `/api/rooms/${enc(roomId)}/recordings/${enc(recordingId)}/stop`,
      { method: "POST", headers: roomAuth(roomToken), body: "{}" },
    );
  },

  current(roomId: string, roomToken: string) {
    return requestJson<{ recording: RecordingState | null; available: boolean }>(
      `/api/rooms/${enc(roomId)}/recordings/current`,
      { headers: roomAuth(roomToken) },
    );
  },

  listMeetings(query: MeetingListQuery = {}) {
    return requestJson<Paged<MeetingRow>>(
      `/api/meetings${queryString({
        page: query.page ?? 1,
        page_size: query.pageSize,
        q: query.q?.trim(),
        filter: query.filter && query.filter !== "all" ? query.filter : null,
        range: query.range && query.range !== "all" ? query.range : null,
      })}`,
    );
  },

  transcript(roomId: string, query: ContentQuery = {}) {
    return requestJson<CursorPage<TranscriptItem>>(`/api/meetings/${enc(roomId)}/transcript${queryString({ ...query })}`);
  },

  relay(roomId: string, query: ContentQuery = {}) {
    return requestJson<CursorPage<RelayItem>>(`/api/meetings/${enc(roomId)}/relay${queryString({ ...query })}`);
  },

  chat(roomId: string, query: ContentQuery = {}) {
    return requestJson<CursorPage<ChatHistoryItem>>(`/api/meetings/${enc(roomId)}/chat${queryString({ ...query })}`);
  },

  searchMeeting(roomId: string, q: string, page = 1) {
    return requestJson<SearchResults>(`/api/meetings/${enc(roomId)}/search${queryString({ q, page })}`);
  },

  searchAll(q: string, page = 1) {
    return requestJson<SearchResults>(`/api/meetings/search${queryString({ q, page })}`);
  },

  meeting(roomId: string) {
    return requestJson<MeetingDetailResponse>(`/api/meetings/${enc(roomId)}`);
  },

  messages(roomId: string, kind: "transcript" | "relay" | "chat", page = 1) {
    return requestJson<Paged<MeetingMessage>>(`/api/meetings/${enc(roomId)}/messages?kind=${kind}&page=${page}`);
  },

  /** Short-lived signed URL; request a fresh one for every play/download. */
  playbackUrl(recordingId: string) {
    return requestJson<{ url: string; expires_in: number }>(`/api/recordings/${enc(recordingId)}/playback-url`, {
      method: "POST",
      body: "{}",
    });
  },

  downloadUrl(recordingId: string) {
    return requestJson<{ url: string; expires_in: number }>(`/api/recordings/${enc(recordingId)}/download-url`, {
      method: "POST",
      body: "{}",
    });
  },
};
