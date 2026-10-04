import { useSearchParams } from "react-router-dom";
import { Bot } from "lucide-react";
import { Alert } from "../../components/ui/Alert";
import { EmptyState } from "../../components/ui/EmptyState";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import type { AiMetricsResponse, HealthStatus, LanguagePairStats, StageStats, WindowKey } from "../api/types";
import { useAdminApi } from "../auth/AdminSession";
import { DataTable, type Column } from "../components/DataTable";
import { LiveIndicator, PageHeader, QueryBoundary, Section, Unavailable } from "../components/Page";
import { HealthBadge } from "../components/StatusBadges";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { formatMs, formatNumber, formatPercent, humanize, languagePairLabel } from "../lib/format";

const METRICS_POLL_MS = 30_000;
export const WINDOW_OPTIONS: Array<{ value: WindowKey; label: string }> = [
  { value: "15m", label: "15 min" },
  { value: "1h", label: "1 hour" },
  { value: "24h", label: "24 hours" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];

export function useWindowParam(fallback: WindowKey): [WindowKey, (value: WindowKey) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("window") as WindowKey | null;
  const value = raw && WINDOW_OPTIONS.some((option) => option.value === raw) ? raw : fallback;
  const setValue = (next: WindowKey) =>
    setParams((current) => {
      const updated = new URLSearchParams(current);
      updated.set("window", next);
      return updated;
    }, { replace: true });
  return [value, setValue];
}

const STAGES: Array<{ key: keyof AiMetricsResponse["stages"]; title: string; help: string; health?: "stt" | "translation" | "voice" }> = [
  { key: "stt", title: "STT", help: "Committed speech → transcript (gpt-4o-transcribe inside the realtime session).", health: "stt" },
  { key: "translation", title: "Translation", help: "Relay request → first translated text, plus caption translations in 3+ language rooms.", health: "translation" },
  { key: "voice", title: "AI voice (TTS)", help: "Relay request → first AI voice audio, for delivered Voice + Text relays.", health: "voice" },
  { key: "delivery", title: "Delivery (end to end)", help: "End of speech → relay text published, for relays the policy approved." },
];

function Percentile({ value, samples, minimum }: { value: number | null; samples: number; minimum: number }) {
  if (value === null) {
    return <span className="text-tertiary" title={`Needs at least ${minimum} samples (have ${samples})`}>—</span>;
  }
  return <>{formatMs(value)}</>;
}

function StageBlock({
  title,
  help,
  stats,
  health,
  minimums,
}: {
  title: string;
  help: string;
  stats: StageStats;
  health?: { status: HealthStatus; reason: string | null };
  minimums: Record<string, number>;
}) {
  return (
    <section className="adm-stage-block" aria-label={title}>
      <header>
        <h3>{title}</h3>
        {health ? <HealthBadge status={health.status} title={health.reason} /> : null}
      </header>
      <p className="adm-stage-help">{help}</p>
      <dl className="adm-stage-stats">
        <div><dt>Requests</dt><dd>{formatNumber(stats.requests)}</dd></div>
        <div><dt>Success rate</dt><dd>{formatPercent(stats.success_rate)}</dd></div>
        <div><dt>Error rate</dt><dd className={stats.errors > 0 ? "adm-text-danger" : undefined}>{formatPercent(stats.error_rate)}</dd></div>
        <div><dt>p50</dt><dd><Percentile value={stats.latency.p50} samples={stats.latency.samples} minimum={minimums.p50 ?? 5} /></dd></div>
        <div><dt>p95</dt><dd><Percentile value={stats.latency.p95} samples={stats.latency.samples} minimum={minimums.p95 ?? 20} /></dd></div>
        <div><dt>p99</dt><dd><Percentile value={stats.latency.p99} samples={stats.latency.samples} minimum={minimums.p99 ?? 100} /></dd></div>
      </dl>
      {stats.error_breakdown.length ? (
        <ul className="adm-breakdown" aria-label={`${title} errors`}>
          {stats.error_breakdown.map((row) => (
            <li key={row.reason}>
              <span>{humanize(row.reason)}</span>
              <span>{formatNumber(row.count)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

const PAIR_COLUMNS: Array<Column<LanguagePairStats>> = [
  { key: "pair", header: "Pair", render: (row) => <strong>{languagePairLabel(row.pair)}</strong> },
  { key: "relays", header: "Relays", align: "right", render: (row) => formatNumber(row.relays) },
  { key: "success", header: "Success", align: "right", render: (row) => formatPercent(row.success_rate) },
  { key: "errors", header: "Error rate", align: "right", render: (row) => <span className={row.errors ? "adm-text-danger" : undefined}>{formatPercent(row.error_rate)}</span> },
  { key: "avg", header: "Avg latency", align: "right", render: (row) => formatMs(row.avg_latency_ms) },
  { key: "p95", header: "p95 latency", align: "right", render: (row) => (row.p95_latency_ms === null ? <span className="text-tertiary" title="Needs 20+ samples">—</span> : formatMs(row.p95_latency_ms)) },
];

export function AiRelayPage() {
  const api = useAdminApi();
  const [windowKey, setWindowKey] = useWindowParam("1h");
  const query = useAdminQuery(`ai-metrics:${windowKey}`, () => api.aiMetrics(windowKey), { intervalMs: METRICS_POLL_MS });

  return (
    <>
      <PageHeader
        title="AI Relay"
        description="How each BRSE AI stage is performing, from per-utterance relay traces."
        actions={<LiveIndicator query={query} />}
      />
      <div className="adm-toolbar">
        <SegmentedControl ariaLabel="Time window" value={windowKey} onChange={setWindowKey} options={WINDOW_OPTIONS} />
      </div>
      <QueryBoundary query={query} skeletonLines={10}>
        {(data) => (
          <>
            {data.truncated ? <Alert tone="info">Showing the latest {formatNumber(data.sample_limit)} utterances of this window.</Alert> : null}
            {data.sampled === 0 ? (
              <EmptyState icon={<Bot size={20} />} title="No relay traffic in this window" description="Stage metrics appear once people speak in rooms with BRSE AI on. Traces are recorded from this release on." />
            ) : null}
            <div className="adm-stage-grid">
              {STAGES.map((stage) => (
                <StageBlock
                  key={stage.key}
                  title={stage.title}
                  help={stage.help}
                  stats={data.stages[stage.key]}
                  health={stage.health ? data.health[stage.health] : undefined}
                  minimums={data.percentile_min_samples}
                />
              ))}
              <section className="adm-stage-block" aria-label="Summary">
                <header>
                  <h3>Summary</h3>
                  <HealthBadge status={data.health.summary.status} title={data.health.summary.reason} />
                </header>
                <p className="adm-stage-help">Live and final meeting summaries requested in this window.</p>
                <dl className="adm-stage-stats">
                  <div><dt>Requests</dt><dd>{formatNumber(data.summary.requests)}</dd></div>
                  <div><dt>Completed</dt><dd>{formatNumber(data.summary.completed)}</dd></div>
                  <div><dt>Failed</dt><dd className={data.summary.failed ? "adm-text-danger" : undefined}>{formatNumber(data.summary.failed)}</dd></div>
                  <div><dt>Not enough content</dt><dd>{formatNumber(data.summary.skipped)}</dd></div>
                  <div><dt>p50</dt><dd><Percentile value={data.summary.latency.p50} samples={data.summary.latency.samples} minimum={data.percentile_min_samples.p50 ?? 5} /></dd></div>
                  <div><dt>p95</dt><dd><Percentile value={data.summary.latency.p95} samples={data.summary.latency.samples} minimum={data.percentile_min_samples.p95 ?? 20} /></dd></div>
                </dl>
              </section>
            </div>

            <Section
              title="Language pairs"
              description="A pair can degrade on its own; compare success and latency across pairs."
            >
              <DataTable
                caption="Language pair performance"
                columns={PAIR_COLUMNS}
                rows={data.language_pairs}
                getRowKey={(row) => row.pair}
                empty={<EmptyState title="No translated relays in this window" />}
              />
            </Section>

            <Section title="AI usage & cost">
              <Unavailable title="Usage data unavailable">
                MeetQ does not record OpenAI token, audio-minute or cost data yet, so no usage or cost figures are shown.
                Request counts above are the closest real signal.
              </Unavailable>
            </Section>
          </>
        )}
      </QueryBoundary>
    </>
  );
}
