import { Badge, type BadgeTone } from "../../components/ui/Badge";
import type { HealthStatus, RoomStatus, Severity } from "../api/types";
import {
  aiStateLabel,
  HEALTH_LABELS,
  humanize,
  ROOM_STATUS_LABELS,
  SEVERITY_LABELS,
} from "../lib/format";

// Every badge pairs a colored dot with text, so status never relies on color alone.

const ROOM_TONES: Record<RoomStatus, BadgeTone> = {
  live: "success",
  empty: "neutral",
  error: "danger",
  expired: "neutral",
};

export function RoomStatusBadge({ status }: { status: RoomStatus }) {
  return (
    <Badge tone={ROOM_TONES[status]} dot pulse={status === "live"}>
      {ROOM_STATUS_LABELS[status]}
    </Badge>
  );
}

const HEALTH_TONES: Record<HealthStatus, BadgeTone> = {
  healthy: "success",
  degraded: "warning",
  down: "danger",
  unknown: "neutral",
};

export function HealthBadge({ status, title }: { status: HealthStatus; title?: string | null }) {
  return (
    <Badge tone={HEALTH_TONES[status]} dot title={title ?? undefined}>
      {HEALTH_LABELS[status]}
    </Badge>
  );
}

const AI_STATE_TONES: Record<string, BadgeTone> = {
  playing: "accent",
  translating: "accent",
  capturing: "info",
  queued: "warning",
  blocked_due_to_overlap: "warning",
  error: "danger",
  idle: "neutral",
  relay_off: "neutral",
};

export function AiStateBadge({ state }: { state: string | null | undefined }) {
  const tone = (state && AI_STATE_TONES[state]) || "neutral";
  return (
    <Badge tone={tone} dot pulse={state === "playing" || state === "translating"}>
      {aiStateLabel(state)}
    </Badge>
  );
}

const SEVERITY_TONES: Record<Severity, BadgeTone> = {
  error: "danger",
  warning: "warning",
  info: "info",
};

export function SeverityBadge({ severity }: { severity: Severity | null | undefined }) {
  if (!severity) return null;
  return (
    <Badge tone={SEVERITY_TONES[severity]} outline>
      {SEVERITY_LABELS[severity]}
    </Badge>
  );
}

const OUTCOME_TONES: Record<string, BadgeTone> = {
  delivered: "success",
  caption_delivered: "success",
  source_only: "neutral",
  source_rejected: "neutral",
  stt_empty: "neutral",
  superseded: "neutral",
  relay_suppressed: "warning",
  relay_dropped: "danger",
  output_rejected: "danger",
  stt_failed: "danger",
  abandoned: "neutral",
};

const OUTCOME_LABELS: Record<string, string> = {
  delivered: "Delivered",
  caption_delivered: "Captions delivered",
  source_only: "Transcript only",
  source_rejected: "Filtered",
  stt_empty: "No speech",
  superseded: "Superseded",
  relay_suppressed: "Suppressed",
  relay_dropped: "Dropped",
  output_rejected: "Output rejected",
  stt_failed: "STT failed",
  abandoned: "Abandoned",
};

export function OutcomeBadge({ outcome }: { outcome: string | null | undefined }) {
  if (!outcome) return <span className="text-tertiary">—</span>;
  return (
    <Badge tone={OUTCOME_TONES[outcome] ?? "neutral"} dot>
      {OUTCOME_LABELS[outcome] ?? humanize(outcome)}
    </Badge>
  );
}

const SUMMARY_TONES: Record<string, BadgeTone> = {
  completed: "success",
  pending: "info",
  skipped: "neutral",
  failed: "danger",
};

export function SummaryStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="text-tertiary">None</span>;
  const label = status === "skipped" ? "Not enough content" : humanize(status);
  return (
    <Badge tone={SUMMARY_TONES[status] ?? "neutral"} dot>
      {label}
    </Badge>
  );
}
