import { AlertTriangle, Check, Minus, X } from "lucide-react";
import { Badge } from "../../components/ui/Badge";
import type { StageStatus, TimelineItem, TraceStage } from "../api/types";
import { formatClock, formatMs, humanize, languageShort } from "../lib/format";
import { OutcomeBadge, SeverityBadge } from "./StatusBadges";

const STAGE_ICONS: Record<StageStatus, typeof Check> = {
  ok: Check,
  failed: X,
  warning: AlertTriangle,
  skipped: Minus,
  pending: Minus,
};

const STAGE_STATUS_TEXT: Record<StageStatus, string> = {
  ok: "OK",
  failed: "Failed",
  warning: "Warning",
  skipped: "Skipped",
  pending: "Pending",
};

function StageChip({ stage }: { stage: TraceStage }) {
  const Icon = STAGE_ICONS[stage.status] ?? Minus;
  return (
    <li className={`adm-stage is-${stage.status}`}>
      <span className="adm-stage-icon" aria-hidden="true">
        <Icon size={12} />
      </span>
      <span className="adm-stage-label">{stage.label}</span>
      <span className="sr-only">{STAGE_STATUS_TEXT[stage.status]}</span>
      {stage.ms !== null && stage.ms !== undefined ? <span className="adm-stage-ms">{formatMs(stage.ms)}</span> : null}
      {stage.note && stage.status !== "ok" ? <span className="adm-stage-note">{humanize(stage.note)}</span> : null}
    </li>
  );
}

function TraceEntry({ item }: { item: TimelineItem }) {
  const isError = item.event_type === "ai_error";
  return (
    <li className={["adm-timeline-item", isError ? "is-error" : ""].filter(Boolean).join(" ")}>
      <div className="adm-timeline-meta">
        <time dateTime={item.occurred_at ?? undefined}>{formatClock(item.occurred_at, true)}</time>
        {isError ? (
          <>
            <Badge tone="danger" outline>AI error</Badge>
            <SeverityBadge severity={item.severity} />
          </>
        ) : (
          <OutcomeBadge outcome={item.outcome} />
        )}
        {item.speaker_name ? <span className="adm-timeline-speaker">{item.speaker_name}</span> : null}
        {item.src_lang ? (
          <span className="adm-timeline-route">
            {languageShort(item.src_lang)}
            {item.target_lang && item.target_lang !== item.src_lang ? ` → ${languageShort(item.target_lang)}` : ""}
          </span>
        ) : null}
        {item.relay_style === "summary" ? <Badge tone="info" outline>Overlap summary</Badge> : null}
      </div>

      {isError ? (
        <p className="adm-timeline-message">
          <strong>{humanize(item.issue_code ?? item.code)}</strong>
          {item.message ? ` — ${item.message}` : null}
        </p>
      ) : (
        <>
          {item.source_text || item.relay_text ? (
            <div className="adm-timeline-text">
              {item.source_text ? <p><span className="adm-timeline-text-label">Source</span>{item.source_text}</p> : null}
              {item.relay_text ? <p><span className="adm-timeline-text-label">Relay</span>{item.relay_text}</p> : null}
            </div>
          ) : null}
          <ol className="adm-stages" aria-label="Relay pipeline">
            {item.stages.map((stage) => (
              <StageChip key={stage.key} stage={stage} />
            ))}
          </ol>
        </>
      )}
    </li>
  );
}

export function RelayTimeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol className="adm-timeline">
      {items.map((item) => (
        <TraceEntry key={item.event_id} item={item} />
      ))}
    </ol>
  );
}
