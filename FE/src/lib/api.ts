import type {
  ApiErrorEnvelope,
  BrseOutputMode,
  CreateRoomRequest,
  CreateRoomResponse,
  MuteParticipantRequest,
  MuteParticipantResponse,
  RoomPermissionsResponse,
  RoomRole,
  ScreenShareStartRequest,
  ScreenShareStateResponse,
  CreateTranslationTestRequest,
  FetchMeetingSummaryResponse,
  GenerateMeetingSummaryResponse,
  JoinRoomRequest,
  JoinRoomResponse,
  MeetingSummaryType,
  MicTestSessionResponse,
  RoomSummary,
  RoomSnapshotResponse,
  TranslationTestSessionResponse,
} from "../types/api";
import { normalizeLanguageList } from "./languages";
import { buildApiUrl } from "./urls";

export { buildApiUrl, getApiBaseUrl } from "./urls";

export class ApiError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;
  requestId?: string | null;

  constructor(
    message: string,
    {
      code,
      status,
      details,
      requestId,
    }: {
      code: string;
      status: number;
      details?: Record<string, unknown>;
      requestId?: string | null;
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
    this.requestId = requestId;
  }
}

function buildAuthHeaders(token: string): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

export function leaveRoomBestEffort(roomId: string, token: string): boolean {
  const url = buildApiUrl(`/api/rooms/${roomId}/leave`);
  void fetch(url, {
    method: "DELETE",
    headers: buildAuthHeaders(token),
    body: "{}",
    keepalive: true,
    credentials: "include",
  }).catch(() => undefined);
  return true;
}

/** Called for every 401 response; each auth realm (user, admin) decides if it is about its session. */
export type UnauthorizedListener = (error: ApiError, path: string) => void;

const unauthorizedListeners = new Set<UnauthorizedListener>();

export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
}

function apiPathOf(pathOrUrl: string): string {
  try {
    return new URL(buildApiUrl(pathOrUrl)).pathname;
  } catch {
    return pathOrUrl;
  }
}

export async function requestJson<T>(
  pathOrUrl: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(buildApiUrl(pathOrUrl), {
    // Sessions are backend-managed HttpOnly cookies on the API origin.
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    let envelope: ApiErrorEnvelope | null = null;

    try {
      envelope = (await response.json()) as ApiErrorEnvelope;
    } catch {
      envelope = null;
    }

    const error = new ApiError(
      envelope?.error?.message || `Request failed with status ${response.status}`,
      {
        code: envelope?.error?.code || "http_error",
        status: response.status,
        details: envelope?.error?.details,
        requestId:
          envelope?.error?.request_id || response.headers.get("X-Request-ID"),
      },
    );
    if (response.status === 401) {
      const path = apiPathOf(pathOrUrl);
      unauthorizedListeners.forEach((listener) => listener(error, path));
    }
    throw error;
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export interface PublicConfig {
  room_meeting_duration_seconds: number;
  supported_languages: string[];
  recording_available?: boolean;
  meeting_history_available?: boolean;
}

export const api = {
  getPublicConfig() {
    return requestJson<PublicConfig>("/api/config");
  },

  createRoom(body: CreateRoomRequest) {
    const roomLanguages = normalizeLanguageList(body.room_languages);
    const payload: CreateRoomRequest = {
      ...body,
      room_languages: roomLanguages,
      meeting_languages: body.meeting_languages ?? roomLanguages,
      language_a: body.language_a ?? roomLanguages[0],
      language_b: body.language_b ?? roomLanguages[1],
    };

    return requestJson<CreateRoomResponse>("/api/rooms", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getRoom(roomId: string) {
    return requestJson<RoomSnapshotResponse>(`/api/rooms/${roomId}`);
  },

  joinRoom(roomId: string, body: JoinRoomRequest) {
    return requestJson<JoinRoomResponse>(`/api/rooms/${roomId}/join`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  leaveRoom(roomId: string, token: string) {
    return requestJson<void>(`/api/rooms/${roomId}/leave`, {
      method: "DELETE",
      headers: buildAuthHeaders(token),
    });
  },

  startScreenShare(roomId: string, token: string, body: ScreenShareStartRequest) {
    return requestJson<ScreenShareStateResponse>(`/api/rooms/${roomId}/screen-share/start`, {
      method: "POST",
      headers: buildAuthHeaders(token),
      body: JSON.stringify(body),
    });
  },

  stopScreenShare(roomId: string, token: string) {
    return requestJson<ScreenShareStateResponse>(`/api/rooms/${roomId}/screen-share/stop`, {
      method: "POST",
      headers: buildAuthHeaders(token),
      body: JSON.stringify({}),
    });
  },

  enableBrse(roomId: string, token: string) {
    return requestJson<RoomSummary>(`/api/rooms/${roomId}/brse/enable`, {
      method: "POST",
      headers: buildAuthHeaders(token),
      body: JSON.stringify({}),
    });
  },

  updateRelayMode(roomId: string, token: string, mode: BrseOutputMode) {
    return requestJson<RoomSummary>(`/api/rooms/${roomId}/relay-mode`, {
      method: "PATCH",
      headers: buildAuthHeaders(token),
      body: JSON.stringify({ mode }),
    });
  },

  disableBrse(roomId: string, token: string) {
    return requestJson<RoomSummary>(`/api/rooms/${roomId}/brse/disable`, {
      method: "POST",
      headers: buildAuthHeaders(token),
      body: JSON.stringify({}),
    });
  },

  getRoomSummary(roomId: string, type: MeetingSummaryType = "final", token?: string | null) {
    const query = new URLSearchParams({ type });
    return requestJson<FetchMeetingSummaryResponse>(
      `/api/rooms/${roomId}/summary?${query.toString()}`,
      token ? { headers: buildAuthHeaders(token) } : undefined,
    );
  },

  generateRoomSummary(
    roomId: string,
    type?: MeetingSummaryType,
    options: { language?: string | null; token?: string | null } = {},
  ) {
    const query = new URLSearchParams();
    if (type) {
      query.set("type", type);
    }
    if (options.language) {
      query.set("language", options.language);
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return requestJson<GenerateMeetingSummaryResponse>(`/api/rooms/${roomId}/summary${suffix}`, {
      method: "POST",
      headers: options.token ? buildAuthHeaders(options.token) : undefined,
      body: JSON.stringify({}),
    });
  },

  muteParticipant(roomId: string, token: string, body: MuteParticipantRequest) {
    return requestJson<MuteParticipantResponse>(
      `/api/rooms/${roomId}/participants/${encodeURIComponent(body.target_participant_id)}/mute`,
      { method: "POST", headers: buildAuthHeaders(token), body: JSON.stringify({}) },
    );
  },

  // ─── Room management (the server checks the caller's role every time) ────

  getRoomPermissions(roomId: string, token: string) {
    return requestJson<RoomPermissionsResponse>(`/api/rooms/${roomId}/permissions`, {
      headers: buildAuthHeaders(token),
    });
  },

  removeParticipant(roomId: string, token: string, participantId: string) {
    return requestJson<{ participant_id: string; removed: boolean }>(
      `/api/rooms/${roomId}/participants/${encodeURIComponent(participantId)}/remove`,
      { method: "POST", headers: buildAuthHeaders(token), body: JSON.stringify({}) },
    );
  },

  setParticipantRole(roomId: string, token: string, participantId: string, role: Exclude<RoomRole, "host">) {
    return requestJson<{ participant_id: string; role: RoomRole; changed: boolean }>(
      `/api/rooms/${roomId}/participants/${encodeURIComponent(participantId)}/role`,
      { method: "PATCH", headers: buildAuthHeaders(token), body: JSON.stringify({ role }) },
    );
  },

  setRoomLocked(roomId: string, token: string, locked: boolean) {
    return requestJson<RoomSummary>(`/api/rooms/${roomId}/${locked ? "lock" : "unlock"}`, {
      method: "POST",
      headers: buildAuthHeaders(token),
      body: JSON.stringify({}),
    });
  },

  /** Sent in the body, never in the URL; the response never contains it. */
  changeRoomPassword(roomId: string, token: string, password: string) {
    return requestJson<RoomSummary>(`/api/rooms/${roomId}/password`, {
      method: "PATCH",
      headers: buildAuthHeaders(token),
      body: JSON.stringify({ password }),
    });
  },

  removeRoomPassword(roomId: string, token: string) {
    return requestJson<RoomSummary>(`/api/rooms/${roomId}/password`, {
      method: "DELETE",
      headers: buildAuthHeaders(token),
    });
  },

  createMicTest() {
    return requestJson<MicTestSessionResponse>("/api/test/mic", {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  deleteMicTest(sessionId: string) {
    return requestJson<void>(`/api/test/mic/${sessionId}`, {
      method: "DELETE",
    });
  },

  createTranslationTest(body: CreateTranslationTestRequest) {
    return requestJson<TranslationTestSessionResponse>("/api/test/translation", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  deleteTranslationTest(sessionId: string) {
    return requestJson<void>(`/api/test/translation/${sessionId}`, {
      method: "DELETE",
    });
  },
};
