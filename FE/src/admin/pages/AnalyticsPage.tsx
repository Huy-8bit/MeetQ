import { useSearchParams } from "react-router-dom";
import { Alert } from "../../components/ui/Alert";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { useAdminApi } from "../auth/AdminSession";
import { BarList, ColumnChart } from "../components/Charts";
import { MetricTile, PageHeader, QueryBoundary, Section } from "../components/Page";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { AI_MODE_LABELS, formatDuration, startOfLocalDay } from "../lib/format";
import { localDateToIso } from "./MeetingsPage";

type RangeKey = "today" | "7d" | "30d" | "custom";
const RANGE_OPTIONS: Array<{ value: RangeKey; label: string }> = [
  { value: "today", label: "Today" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "custom", label: "Custom" },
];

function toInputDate(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

export function resolveRange(range: RangeKey, from: string, to: string, now = new Date()): { from: string; to: string } | null {
  const today = startOfLocalDay(now);
  if (range === "today") return { from: today.toISOString(), to: now.toISOString() };
  if (range === "7d" || range === "30d") {
    const days = range === "7d" ? 6 : 29;
    const start = new Date(today);
    start.setDate(start.getDate() - days);
    return { from: start.toISOString(), to: now.toISOString() };
  }
  const start = localDateToIso(from);
  const end = localDateToIso(to, true);
  if (!start || !end || end <= start) return null;
  return { from: start, to: end };
}

export function AnalyticsPage() {
  const api = useAdminApi();
  const [params, setParams] = useSearchParams();
  const range = (RANGE_OPTIONS.some((option) => option.value === params.get("range")) ? params.get("range") : "7d") as RangeKey;
  const customFrom = params.get("from") ?? toInputDate(new Date(Date.now() - 6 * 86_400_000));
  const customTo = params.get("to") ?? toInputDate(new Date());
  const resolved = resolveRange(range, customFrom, customTo);
  const tzOffset = -new Date().getTimezoneOffset();
  const key = resolved ? `${resolved.from}:${resolved.to}` : "invalid";
  // Rounded to the minute so "today"/"7 days" don't refetch on every render.
  const query = useAdminQuery(
    `analytics:${range}:${range === "custom" ? key : new Date().toISOString().slice(0, 16)}`,
    () => api.analytics(resolved!.from, resolved!.to, tzOffset),
    { enabled: resolved !== null },
  );

  const update = (changes: Record<string, string>) =>
    setParams((current) => {
      const next = new URLSearchParams(current);
      Object.entries(changes).forEach(([name, value]) => next.set(name, value));
      return next;
    }, { replace: true });

  return (
    <>
      <PageHeader title="Analytics" description="Product usage from the meeting archive. Counts are per meeting; MeetQ has no user accounts, so there are no per-user metrics." />
      <div className="adm-toolbar">
        <SegmentedControl ariaLabel="Date range" value={range} onChange={(value) => update({ range: value })} options={RANGE_OPTIONS} />
        {range === "custom" ? (
          <>
            <label className="adm-date">
              <span>From</span>
              <input className="input" type="date" value={customFrom} max={customTo} onChange={(event) => update({ from: event.target.value })} />
            </label>
            <label className="adm-date">
              <span>To</span>
              <input className="input" type="date" value={customTo} min={customFrom} onChange={(event) => update({ to: event.target.value })} />
            </label>
          </>
        ) : null}
      </div>
      {!resolved ? <Alert tone="warning">Pick a valid date range (start before end).</Alert> : null}
      {resolved ? (
        <QueryBoundary query={query} skeletonLines={10}>
          {(data) => {
            const t = data.totals;
            const usage = data.feature_usage;
            return (
              <>
                {data.truncated ? <Alert tone="info">Range contains more than 20,000 rooms; figures cover the first 20,000.</Alert> : null}
                <div className="adm-metrics">
                  <MetricTile label="Meetings" value={t.meetings} note={`${t.rooms_created ?? 0} rooms created`} />
                  <MetricTile label="Avg duration" value={t.avg_duration_seconds} format={(value) => formatDuration(value)} />
                  <MetricTile label="Avg participants" value={t.avg_participants} format={(value) => value.toFixed(1)} />
                  <MetricTile label="Total participants" value={t.total_participants} />
                  <MetricTile label="Relay sentences" value={t.relay_lines} note={`${t.source_lines ?? 0} source lines`} />
                  <MetricTile label="Chat messages" value={t.chat_messages} />
                </div>
                <Section title="Meetings over time" description="Meetings with at least one participant, per day (your local time).">
                  <ColumnChart
                    ariaLabel="Meetings per day"
                    valueLabel="meetings"
                    data={data.meetings_over_time.map((day) => {
                      const date = new Date(`${day.date}T00:00:00`);
                      return {
                        key: day.date,
                        label: date.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }),
                        axisLabel: date.toLocaleDateString([], { month: "numeric", day: "numeric" }),
                        value: day.meetings,
                      };
                    })}
                  />
                </Section>
                <div className="adm-grid-2 is-even">
                  <Section title="Language distribution" description="Room language combinations.">
                    {data.language_distribution.length ? (
                      <BarList
                        ariaLabel="Meetings by room languages"
                        valueLabel="meetings"
                        data={data.language_distribution.map((row) => ({ key: row.key, label: row.label, value: row.count }))}
                      />
                    ) : (
                      <p className="adm-muted-row">No meetings in this range.</p>
                    )}
                  </Section>
                  <Section title="AI mode usage" description="Mode each meeting ran with (as configured at the time it was archived).">
                    <BarList
                      ariaLabel="Meetings by AI mode"
                      valueLabel="meetings"
                      data={data.ai_mode_usage.map((row) => ({ key: row.mode, label: AI_MODE_LABELS[row.mode], value: row.count }))}
                    />
                  </Section>
                </div>
                <Section title="Feature usage">
                  <div className="adm-metrics">
                    <MetricTile label="Translated chat messages" value={usage.translated_chat_messages?.value} available={usage.translated_chat_messages?.available} />
                    <MetricTile label="Live summaries" value={usage.live_summaries?.value} note={usage.live_summaries?.note} />
                    <MetricTile label="Final summaries" value={usage.final_summaries?.value} note={usage.final_summaries?.note} />
                    <MetricTile label="Screen share" value={usage.screen_share?.value} available={usage.screen_share?.available} note={usage.screen_share?.note} />
                  </div>
                </Section>
              </>
            );
          }}
        </QueryBoundary>
      ) : null}
    </>
  );
}
