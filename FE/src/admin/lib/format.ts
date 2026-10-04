import { getLanguageLabel } from "../../lib/languages";
import type { Language } from "../../types/api";
import type { AiMode, HealthStatus, RoomStatus, Severity } from "../api/types";

export const AI_MODE_LABELS: Record<AiMode, string> = {
  voice_text: "Voice + Text",
  text_only: "Text Only",
  captions: "Captions",
  summary_capture: "Summary capture",
  off: "Off",
};

export const ROOM_STATUS_LABELS: Record<RoomStatus, string> = {
  live: "Live",
  empty: "Empty",
  error: "Error",
  expired: "Expired",
};

export const HEALTH_LABELS: Record<HealthStatus, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  down: "Down",
  unknown: "No data",
};

export const SEVERITY_LABELS: Record<Severity, string> = {
  error: "Error",
  warning: "Warning",
  info: "Info",
};

// Same vocabulary as the meeting UI's BRSE AI tile.
const AI_STATE_LABELS: Record<string, string> = {
  idle: "Idle",
  capturing: "Capturing",
  queued: "Queued",
  translating: "Translating",
  playing: "Playing",
  blocked_due_to_overlap: "Blocked Due To Overlap",
  error: "Error",
  relay_off: "Relay Off",
};

export function aiStateLabel(state: string | null | undefined): string {
  if (!state) return "No status yet";
  return AI_STATE_LABELS[state] ?? humanize(state);
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "";
  const text = value.replace(/[_:]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function languageName(code: string | null | undefined): string {
  if (!code) return "—";
  return getLanguageLabel(code as Language);
}

export function languageShort(code: string | null | undefined): string {
  return code ? code.toUpperCase() : "—";
}

export function languageList(codes: readonly string[]): string {
  if (codes.length === 0) return "—";
  if (codes.length === 2) return `${languageShort(codes[0])} ⇄ ${languageShort(codes[1])}`;
  return codes.map(languageShort).join(" · ");
}

/** "vi>ja" -> "VI → JA" */
export function languagePairLabel(pair: string | null | undefined): string {
  if (!pair) return "—";
  const [source, target] = pair.split(">");
  return `${languageShort(source)} → ${languageShort(target)}`;
}

const numberFormatter = new Intl.NumberFormat();

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return numberFormatter.format(value);
}

export function formatPercent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "—";
  const percent = rate * 100;
  return `${percent >= 10 || percent === 0 ? Math.round(percent) : percent.toFixed(1)}%`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${String(Math.round(seconds % 60)).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

export function formatTimeLeft(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds <= 0) return "Ended";
  if (seconds < 60) return `${seconds}s`;
  return `${Math.ceil(seconds / 60)}m`;
}

function toDate(value: string | number | null | undefined): Date | null {
  if (value === null || value === undefined) return null;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date : null;
}

export function formatClock(value: string | null | undefined, withSeconds = false): string {
  const date = toDate(value);
  if (!date) return "—";
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
  });
}

export function formatDateTime(value: string | null | undefined): string {
  const date = toDate(value);
  if (!date) return "—";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function formatRelative(value: string | number | null | undefined, now = Date.now()): string {
  const date = toDate(value);
  if (!date) return "—";
  const seconds = Math.round((now - date.getTime()) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return formatDateTime(typeof value === "number" ? new Date(value).toISOString() : value);
}

export function startOfLocalDay(date = new Date()): Date {
  const start = new Date(date);
  start.setHours(0, 0, 0, 0);
  return start;
}

/** Room access type for admins. Admins never see the room password itself. */
export function accessLabel(passwordProtected: boolean | undefined): string {
  return passwordProtected ? "Password protected" : "Public link";
}
