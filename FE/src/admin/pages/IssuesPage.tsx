import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { CheckCircle2 } from "lucide-react";
import { ApiError } from "../../lib/api";
import { Alert } from "../../components/ui/Alert";
import { EmptyState } from "../../components/ui/EmptyState";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { Switch } from "../../components/ui/Switch";
import type { IssueAggregate, IssueOccurrence } from "../api/types";
import { useAdminApi } from "../auth/AdminSession";
import { DataTable, Pagination, type Column } from "../components/DataTable";
import { KeyValueList, LiveIndicator, PageHeader, QueryBoundary, Section } from "../components/Page";
import { SeverityBadge } from "../components/StatusBadges";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { formatDateTime, formatNumber, formatRelative, humanize, languagePairLabel } from "../lib/format";
import { useWindowParam, WINDOW_OPTIONS } from "./AiRelayPage";

const ISSUES_POLL_MS = 30_000;

const issueHref = (code: string, window: string) => `/admin/issues/${encodeURIComponent(code)}?window=${window}`;

export function IssuesPage() {
  const api = useAdminApi();
  const [windowKey, setWindowKey] = useWindowParam("24h");
  const [params, setParams] = useSearchParams();
  const includeInfo = params.get("info") === "1";
  const query = useAdminQuery(`issues:${windowKey}:${includeInfo}`, () => api.issues(windowKey, includeInfo), {
    intervalMs: ISSUES_POLL_MS,
  });

  const columns: Array<Column<IssueAggregate>> = [
    {
      key: "issue",
      header: "Issue",
      render: (row) => (
        <span className="adm-cell-stack">
          <Link to={issueHref(row.code, windowKey)}>{row.title}</Link>
          <span className="adm-code">{row.code}</span>
        </span>
      ),
    },
    { key: "severity", header: "Severity", render: (row) => <SeverityBadge severity={row.severity} /> },
    { key: "stage", header: "Stage", render: (row) => humanize(row.stage), hideOnNarrow: true },
    { key: "count", header: "Occurrences", align: "right", render: (row) => <strong>{formatNumber(row.occurrences)}</strong> },
    { key: "rooms", header: "Rooms", align: "right", render: (row) => formatNumber(row.affected_rooms) },
    { key: "pair", header: "Top pair", render: (row) => languagePairLabel(row.top_language_pair), hideOnNarrow: true },
    { key: "latest", header: "Latest", render: (row) => formatRelative(row.latest_at) },
  ];

  return (
    <>
      <PageHeader
        title="Issues"
        description="AI relay problems grouped by type, so you can see what is failing and where."
        actions={<LiveIndicator query={query} />}
      />
      <div className="adm-toolbar">
        <SegmentedControl ariaLabel="Time window" value={windowKey} onChange={setWindowKey} options={WINDOW_OPTIONS} />
        <Switch
          checked={includeInfo}
          onChange={(checked) =>
            setParams((current) => {
              const next = new URLSearchParams(current);
              if (checked) next.set("info", "1");
              else next.delete("info");
              return next;
            }, { replace: true })
          }
          label="Include info (filtered speech, overlap)"
        />
      </div>
      <QueryBoundary query={query}>
        {(data) => (
          <>
            {data.truncated ? <Alert tone="info">Counts are based on the latest 20,000 events in this window.</Alert> : null}
            <DataTable
              caption="Issues by type"
              columns={columns}
              rows={data.items}
              getRowKey={(row) => row.code}
              getRowHref={(row) => issueHref(row.code, windowKey)}
              empty={<EmptyState icon={<CheckCircle2 size={20} />} title="No issues in this window" description="No warning or error was recorded. Turn on “Include info” to see filtered speech and overlap events." />}
            />
          </>
        )}
      </QueryBoundary>
    </>
  );
}

export function IssueDetailPage() {
  const { code = "" } = useParams();
  const api = useAdminApi();
  const [windowKey, setWindowKey] = useWindowParam("24h");
  const [page, setPage] = useState(1);
  const query = useAdminQuery(`issue:${code}:${windowKey}:${page}`, () => api.issue(code, windowKey, page), {
    intervalMs: ISSUES_POLL_MS,
  });
  const notFound = query.error instanceof ApiError && query.error.status === 404;

  const columns: Array<Column<IssueOccurrence>> = [
    { key: "time", header: "Time", render: (row) => formatDateTime(row.occurred_at) },
    {
      key: "room",
      header: "Room",
      render: (row) =>
        row.room_id ? <Link className="adm-mono-link" to={`/admin/meetings/${encodeURIComponent(row.room_id)}`}>{row.room_id}</Link> : "—",
    },
    { key: "speaker", header: "Speaker", render: (row) => row.speaker_name ?? "—", hideOnNarrow: true },
    { key: "pair", header: "Language pair", render: (row) => languagePairLabel(row.language_pair) },
    { key: "detail", header: "Details", className: "adm-cell-text", render: (row) => (row.detail ? humanize(row.detail) : "—") },
  ];

  return (
    <>
      <PageHeader breadcrumb={{ label: "Issues", to: `/admin/issues?window=${windowKey}` }} title={query.data?.issue.title ?? code} actions={<LiveIndicator query={query} />} />
      <div className="adm-toolbar">
        <SegmentedControl ariaLabel="Time window" value={windowKey} onChange={(next) => { setPage(1); setWindowKey(next); }} options={WINDOW_OPTIONS} />
      </div>
      {notFound ? (
        <EmptyState title="Unknown issue type" description={`${code} is not an issue code MeetQ records.`} />
      ) : (
        <QueryBoundary query={query}>
          {(data) => (
            <>
              <p className="adm-page-description">{data.issue.description}</p>
              <KeyValueList
                items={[
                  { label: "Issue", value: <span className="adm-code">{data.issue.code}</span> },
                  { label: "Severity", value: <SeverityBadge severity={data.issue.severity} /> },
                  { label: "Stage", value: humanize(data.issue.stage) },
                  { label: "Occurrences", value: formatNumber(data.issue.occurrences) },
                  { label: "Affected rooms", value: formatNumber(data.issue.affected_rooms) },
                  { label: "Most affected pair", value: languagePairLabel(data.issue.top_language_pair) },
                  { label: "First occurrence", value: formatDateTime(data.issue.first_at) },
                  { label: "Latest occurrence", value: formatDateTime(data.issue.latest_at) },
                ]}
              />
              <Section title="Occurrences">
                <DataTable
                  caption="Issue occurrences"
                  columns={columns}
                  rows={data.occurrences.items}
                  getRowKey={(row) => row.event_id}
                  empty={<EmptyState title="No occurrences in this window" />}
                />
                <Pagination page={data.occurrences.page} pageSize={data.occurrences.page_size} total={data.occurrences.total} onPageChange={setPage} />
              </Section>
            </>
          )}
        </QueryBoundary>
      )}
    </>
  );
}
