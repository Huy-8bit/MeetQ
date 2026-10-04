import { Link } from "react-router-dom";
import { Radio } from "lucide-react";
import { Alert } from "../../components/ui/Alert";
import { EmptyState } from "../../components/ui/EmptyState";
import type { AiHealth, IssueOccurrence, OverviewResponse } from "../api/types";
import { useAdminApi } from "../auth/AdminSession";
import { LiveRoomsTable } from "../components/LiveRoomsTable";
import { LiveIndicator, MetricTile, PageHeader, QueryBoundary, Section } from "../components/Page";
import { HealthBadge, SeverityBadge } from "../components/StatusBadges";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { formatRelative, languagePairLabel, startOfLocalDay } from "../lib/format";

const OVERVIEW_POLL_MS = 10_000;

const AI_STAGES: Array<{ key: keyof Omit<AiHealth, "window_minutes">; label: string; help: string }> = [
  { key: "stt", label: "STT", help: "Speech → transcript inside the realtime session" },
  { key: "translation", label: "Translation", help: "Relay text from the realtime model / caption translation" },
  { key: "voice", label: "AI voice (TTS)", help: "AI voice audio for Voice + Text rooms" },
  { key: "summary", label: "Summary", help: "Live and final meeting summaries (last 24 h)" },
];

function KpiRow({ data }: { data: OverviewResponse }) {
  const k = data.kpis;
  return (
    <div className="adm-metrics">
      <MetricTile label="Active rooms" value={k.active_rooms?.value} note={`${k.open_rooms?.value ?? 0} open in total`} href="/admin/live-rooms" />
      <MetricTile label="Participants online" value={k.participants_online?.value} href="/admin/live-rooms" />
      <MetricTile
        label="Meetings today"
        value={k.meetings_today?.value}
        previous={k.meetings_today?.previous}
        previousLabel="vs this time yesterday"
        available={k.meetings_today?.available}
        href="/admin/meetings"
      />
      <MetricTile label="AI-enabled rooms" value={k.ai_enabled_rooms?.value} href="/admin/live-rooms" />
      <MetricTile
        label="AI relay issues (1 h)"
        value={k.relay_errors_1h?.value}
        previous={k.relay_errors_1h?.previous}
        previousLabel="vs previous hour"
        goodDirection="down"
        available={k.relay_errors_1h?.available}
        emphasis={(k.relay_errors_1h?.value ?? 0) > 0 ? "warning" : null}
        href="/admin/issues?window=1h"
      />
      <MetricTile
        label="Summary failures today"
        value={k.summary_failures_today?.value}
        previous={k.summary_failures_today?.previous}
        previousLabel="vs yesterday"
        goodDirection="down"
        available={k.summary_failures_today?.available}
        emphasis={(k.summary_failures_today?.value ?? 0) > 0 ? "danger" : null}
        href="/admin/issues/SUMMARY_FAILED"
      />
    </div>
  );
}

function HealthList({ data }: { data: OverviewResponse }) {
  return (
    <>
      <ul className="adm-health-list" aria-label={`AI health, last ${data.ai_health.window_minutes} minutes`}>
        {AI_STAGES.map((stage) => {
          const health = data.ai_health[stage.key];
          return (
            <li key={stage.key}>
              <span className="adm-health-name" title={stage.help}>{stage.label}</span>
              <span className="adm-health-reason">{health.reason}</span>
              <HealthBadge status={health.status} />
            </li>
          );
        })}
      </ul>
      <h3 className="adm-subheading">Infrastructure</h3>
      <ul className="adm-health-list">
        {data.system_health.components.map((component) => (
          <li key={component.key}>
            <span className="adm-health-name">{component.label}</span>
            <span className="adm-health-reason">{component.detail}</span>
            <HealthBadge status={component.status} />
          </li>
        ))}
      </ul>
    </>
  );
}

function RecentIssues({ items }: { items: IssueOccurrence[] }) {
  if (items.length === 0) {
    return <p className="adm-muted-row">No warnings or errors recorded recently.</p>;
  }
  return (
    <ul className="adm-issue-feed">
      {items.map((item) => (
        <li key={item.event_id}>
          <SeverityBadge severity={item.severity} />
          <Link to={`/admin/issues/${item.issue_code}`} className="adm-issue-feed-title">{item.title}</Link>
          {item.room_id ? (
            <Link className="adm-mono-link" to={`/admin/live-rooms/${encodeURIComponent(item.room_id)}`}>{item.room_id}</Link>
          ) : null}
          {item.language_pair ? <span className="text-tertiary">{languagePairLabel(item.language_pair)}</span> : null}
          <time className="adm-issue-feed-time" dateTime={item.occurred_at ?? undefined}>{formatRelative(item.occurred_at)}</time>
        </li>
      ))}
    </ul>
  );
}

export function OverviewPage() {
  const api = useAdminApi();
  const query = useAdminQuery("overview", () => api.overview(startOfLocalDay().toISOString()), {
    intervalMs: OVERVIEW_POLL_MS,
  });

  return (
    <>
      <PageHeader
        title="Overview"
        description="What is running right now and whether BRSE AI is healthy."
        actions={<LiveIndicator query={query} />}
      />
      <QueryBoundary query={query} skeletonLines={10}>
        {(data) => (
          <>
            {!data.history_available ? (
              <Alert tone="warning">
                History storage is unavailable, so meeting counts, issues and AI health cannot be computed. Live room data is still shown.
              </Alert>
            ) : null}
            <KpiRow data={data} />
            <div className="adm-grid-2">
              <Section
                title="Live rooms"
                description="Most urgent first: rooms with errors, then live, then empty."
                actions={<Link to="/admin/live-rooms" className="btn btn--ghost btn--sm">All live rooms</Link>}
              >
                <LiveRoomsTable
                  compact
                  rows={data.live_rooms}
                  busy={query.isRefreshing}
                  empty={<EmptyState icon={<Radio size={20} />} title="No open rooms" description="Rooms appear here as soon as they are created." />}
                />
              </Section>
              <Section
                title="Health"
                description={`AI stages from the last ${data.ai_health.window_minutes} minutes of real traffic.`}
              >
                <HealthList data={data} />
              </Section>
            </div>
            <Section
              title="Recent issues"
              actions={<Link to="/admin/issues" className="btn btn--ghost btn--sm">Issues explorer</Link>}
            >
              <RecentIssues items={data.recent_issues} />
            </Section>
          </>
        )}
      </QueryBoundary>
    </>
  );
}
