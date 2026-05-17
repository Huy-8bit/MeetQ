import type {
  ApiErrorEnvelope,
  CreateRoomRequest,
  CreateRoomResponse,
  MuteParticipantRequest,
  MuteParticipantResponse,
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
  }).catch(() => undefined);
  return true;
}

async function requestJson<T>(
  pathOrUrl: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(buildApiUrl(pathOrUrl), {
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

    throw new ApiError(
      envelope?.error.message || `Request failed with status ${response.status}`,
      {
        code: envelope?.error.code || "http_error",
        status: response.status,
        details: envelope?.error.details,
        requestId:
          envelope?.error.request_id || response.headers.get("X-Request-ID"),
      },
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const api = {
  createRoom(body: CreateRoomRequest) {
    return requestJson<CreateRoomResponse>("/api/rooms", {
      method: "POST",
      body: JSON.stringify(body),
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

  disableBrse(roomId: string, token: string) {
    return requestJson<RoomSummary>(`/api/rooms/${roomId}/brse/disable`, {
      method: "POST",
      headers: buildAuthHeaders(token),
      body: JSON.stringify({}),
    });
  },

  getRoomSummary(roomId: string, type: MeetingSummaryType = "final") {
    const query = new URLSearchParams({ type });
    return requestJson<FetchMeetingSummaryResponse>(
      `/api/rooms/${roomId}/summary?${query.toString()}`,
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
    return requestJson<MuteParticipantResponse>(`/api/rooms/${roomId}/moderation/mute`, {
      method: "POST",
      headers: buildAuthHeaders(token),
      body: JSON.stringify(body),
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
