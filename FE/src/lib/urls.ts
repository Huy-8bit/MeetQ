const LOCAL_DEV_APP_ORIGIN = "http://localhost:3000";
const LOCAL_DEV_API_BASE_URL = "http://localhost:8000";
const LOCAL_DEV_GATEWAY_WS_BASE_URL = "ws://localhost:8000";
const LOCAL_DEV_LIVEKIT_WS_URL = "ws://localhost:7880";

const PRODUCTION_APP_ORIGIN = "https://meetqapp.com";
const PRODUCTION_API_BASE_URL = "https://api.meetqapp.com";
const PRODUCTION_GATEWAY_WS_BASE_URL = "wss://api.meetqapp.com";
const PRODUCTION_LIVEKIT_WS_URL = "wss://rtc.meetqapp.com";

const ABSOLUTE_HTTP_URL_RE = /^https?:\/\//i;
const ABSOLUTE_WS_URL_RE = /^wss?:\/\//i;

export function getPublicAppOrigin(): string {
  const configuredOrigin = firstConfiguredUrl([
    import.meta.env.VITE_APP_ORIGIN,
    import.meta.env.VITE_PUBLIC_APP_URL,
  ]);
  if (configuredOrigin) {
    return stripTrailingSlash(configuredOrigin);
  }

  if (import.meta.env.PROD) {
    return PRODUCTION_APP_ORIGIN;
  }

  const browserOrigin = getBrowserOrigin();
  return browserOrigin ?? LOCAL_DEV_APP_ORIGIN;
}

export function getApiBaseUrl(): string {
  const configuredBaseUrl = normalizeOptionalUrl(import.meta.env.VITE_API_BASE_URL);
  if (configuredBaseUrl) {
    return configuredBaseUrl === "/" && !import.meta.env.PROD
      ? getPublicAppOrigin()
      : stripTrailingSlash(configuredBaseUrl);
  }

  if (import.meta.env.PROD) {
    return PRODUCTION_API_BASE_URL;
  }

  return LOCAL_DEV_API_BASE_URL;
}

export function buildApiUrl(pathOrUrl: string): string {
  if (ABSOLUTE_HTTP_URL_RE.test(pathOrUrl)) {
    return pathOrUrl;
  }

  return new URL(pathOrUrl, ensureTrailingSlash(getApiBaseUrl())).toString();
}

export function resolveGatewayWebSocketUrl(rawUrl: string): string {
  if (ABSOLUTE_WS_URL_RE.test(rawUrl)) {
    return rawUrl;
  }

  const configuredBaseUrl = firstConfiguredUrl([
    import.meta.env.VITE_WS_BASE_URL,
    import.meta.env.VITE_GATEWAY_WS_BASE_URL,
  ]);
  const wsBase = configuredBaseUrl
    ? normalizeWebSocketBaseUrl(configuredBaseUrl)
    : import.meta.env.PROD
      ? PRODUCTION_GATEWAY_WS_BASE_URL
      : normalizeWebSocketBaseUrl(LOCAL_DEV_GATEWAY_WS_BASE_URL);

  return new URL(rawUrl, ensureTrailingSlash(wsBase)).toString();
}

export function resolveLiveKitUrl(rawUrl?: string | null): string {
  const configuredUrl = normalizeOptionalUrl(import.meta.env.VITE_LIVEKIT_WS_URL);
  const fallbackUrl = configuredUrl
    || (import.meta.env.PROD ? PRODUCTION_LIVEKIT_WS_URL : LOCAL_DEV_LIVEKIT_WS_URL);
  const candidate = rawUrl?.trim();

  if (!candidate) {
    return fallbackUrl;
  }

  if (ABSOLUTE_WS_URL_RE.test(candidate)) {
    return candidate;
  }

  return new URL(candidate, ensureTrailingSlash(fallbackUrl)).toString();
}

export function resolveInviteUrl(pathOrUrl: string): string {
  if (ABSOLUTE_HTTP_URL_RE.test(pathOrUrl)) {
    return pathOrUrl;
  }

  return new URL(pathOrUrl, ensureTrailingSlash(getPublicAppOrigin())).toString();
}

export function buildRoomInviteUrl(roomId: string): string {
  return resolveInviteUrl(`/rooms/${roomId}`);
}

function normalizeWebSocketBaseUrl(input: string): string {
  if (ABSOLUTE_WS_URL_RE.test(input)) {
    return stripTrailingSlash(input);
  }

  return deriveWebSocketBaseUrl(input);
}

function deriveWebSocketBaseUrl(httpBaseUrl: string): string {
  const baseUrl = new URL(httpBaseUrl);
  baseUrl.protocol = baseUrl.protocol === "https:" ? "wss:" : "ws:";
  return stripTrailingSlash(baseUrl.toString());
}

function normalizeOptionalUrl(input: string | undefined): string | null {
  const value = input?.trim();
  return value ? value : null;
}

function firstConfiguredUrl(inputs: Array<string | undefined>): string | null {
  for (const input of inputs) {
    const value = normalizeOptionalUrl(input);
    if (value) {
      return value;
    }
  }

  return null;
}

function getBrowserOrigin(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  return window.location.origin;
}

function ensureTrailingSlash(input: string): string {
  return input.endsWith("/") ? input : `${input}/`;
}

function stripTrailingSlash(input: string): string {
  return input.endsWith("/") ? input.slice(0, -1) : input;
}
