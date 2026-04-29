import type {
  ApiErrorEnvelope,
  CreateRoomResponse,
  JoinRoomRequest,
  JoinRoomResponse,
  RoomSnapshotResponse,
} from "../types/api";

const DEFAULT_API_BASE_URL = "http://localhost:8000";

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

export function getApiBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;
}

export function buildApiUrl(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) {
    return pathOrUrl;
  }

  return new URL(pathOrUrl, ensureTrailingSlash(getApiBaseUrl())).toString();
}

function ensureTrailingSlash(input: string): string {
  return input.endsWith("/") ? input : `${input}/`;
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
  createRoom() {
    return requestJson<CreateRoomResponse>("/api/rooms", {
      method: "POST",
      body: JSON.stringify({}),
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
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
  },
};
