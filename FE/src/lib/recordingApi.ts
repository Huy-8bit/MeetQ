import { requestJson } from "./api";
import type {
  MeetingDetailResponse,
  MeetingMessage,
  MeetingRow,
  Paged,
  RecordingState,
} from "../types/recording";

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

  listMeetings(page = 1) {
    return requestJson<Paged<MeetingRow>>(`/api/meetings?page=${page}`);
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
