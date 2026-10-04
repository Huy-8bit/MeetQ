import { Link } from "react-router-dom";
import { History, SearchX } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { CustomSelect } from "../../components/CustomSelect";
import { EmptyState } from "../../components/ui/EmptyState";
import type { MeetingRow } from "../api/types";
import { useAdminApi } from "../auth/AdminSession";
import { DataTable, Pagination, type Column } from "../components/DataTable";
import { FilterBar, PageHeader, QueryBoundary, SearchInput } from "../components/Page";
import { SummaryStatusBadge } from "../components/StatusBadges";
import { Badge } from "../../components/ui/Badge";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { AI_MODE_OPTIONS, LANGUAGE_OPTIONS, useUrlFilters } from "../lib/filters";
import { AI_MODE_LABELS, formatDateTime, formatDuration, humanize, languageList } from "../lib/format";

const PAGE_SIZE = 25;
const FILTER_KEYS = ["q", "from", "to", "language", "ai_mode", "summary_status", "status"] as const;

export const meetingHref = (roomId: string) => `/admin/meetings/${encodeURIComponent(roomId)}`;

/** yyyy-mm-dd (local) -> ISO instant at local midnight; `endOfDay` gives the next midnight. */
export function localDateToIso(value: string, endOfDay = false): string | undefined {
  if (!value) return undefined;
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return undefined;
  const date = new Date(year, month - 1, day + (endOfDay ? 1 : 0));
  return date.toISOString();
}

const COLUMNS: Array<Column<MeetingRow>> = [
  { key: "room", header: "Room", render: (row) => <Link className="adm-mono-link" to={meetingHref(row.room_id)}>{row.room_id}</Link> },
  { key: "languages", header: "Languages", render: (row) => languageList(row.room_languages) },
  { key: "created", header: "Created", render: (row) => formatDateTime(row.created_at) },
  { key: "ended", header: "Ended", render: (row) => formatDateTime(row.ended_at), hideOnNarrow: true },
  { key: "duration", header: "Duration", align: "right", render: (row) => formatDuration(row.duration_seconds) },
  { key: "participants", header: "Participants", align: "right", render: (row) => row.participant_count },
  { key: "mode", header: "AI mode", render: (row) => AI_MODE_LABELS[row.ai_mode], hideOnNarrow: true },
  { key: "summary", header: "Final summary", render: (row) => <SummaryStatusBadge status={row.final_summary_status} /> },
  {
    key: "status",
    header: "Status",
    render: (row) =>
      row.status === "live" ? (
        <Badge tone="success" dot pulse>Live</Badge>
      ) : (
        <Badge dot>{row.end_reason === "empty" ? "Ended · empty" : row.end_reason ? `Ended · ${humanize(row.end_reason).toLowerCase()}` : "Ended"}</Badge>
      ),
  },
];

export function MeetingsPage() {
  const api = useAdminApi();
  const { values, page, setFilter, clear, active } = useUrlFilters(FILTER_KEYS);
  const key = JSON.stringify({ ...values, page });
  const query = useAdminQuery(`meetings:${key}`, () =>
    api.meetings({
      q: values.q,
      from: localDateToIso(values.from),
      to: localDateToIso(values.to, true),
      language: values.language,
      ai_mode: values.ai_mode,
      summary_status: values.summary_status,
      status: values.status,
      page,
      page_size: PAGE_SIZE,
    }),
  );

  return (
    <>
      <PageHeader
        title="Meetings"
        description="Every meeting in history. Transcripts, relays, chat and summaries are kept until the meeting archive expires; recordings are under Recordings."
        actions={<Button size="sm" variant="secondary" onClick={query.refetch} loading={query.isRefreshing}>Refresh</Button>}
      />
      <FilterBar trailing={active ? <Button size="sm" variant="ghost" onClick={clear}>Clear filters</Button> : null}>
        <SearchInput label="Search room ID or participant name" placeholder="Room ID or participant name" value={values.q} onChange={(value) => setFilter("q", value)} />
        <label className="adm-date">
          <span>From</span>
          <input className="input" type="date" value={values.from} max={values.to || undefined} onChange={(event) => setFilter("from", event.target.value)} />
        </label>
        <label className="adm-date">
          <span>To</span>
          <input className="input" type="date" value={values.to} min={values.from || undefined} onChange={(event) => setFilter("to", event.target.value)} />
        </label>
        <CustomSelect ariaLabel="Language" size="compact" value={values.language} onChange={(value) => setFilter("language", value)} options={LANGUAGE_OPTIONS} />
        <CustomSelect ariaLabel="AI mode" size="compact" value={values.ai_mode} onChange={(value) => setFilter("ai_mode", value)} options={AI_MODE_OPTIONS} />
        <CustomSelect
          ariaLabel="Summary status"
          size="compact"
          value={values.summary_status}
          onChange={(value) => setFilter("summary_status", value)}
          options={[
            { value: "", label: "Any summary" },
            { value: "completed", label: "Completed" },
            { value: "failed", label: "Failed" },
            { value: "skipped", label: "Not enough content" },
            { value: "pending", label: "Pending" },
            { value: "none", label: "No summary" },
          ]}
        />
        <CustomSelect
          ariaLabel="Meeting status"
          size="compact"
          value={values.status}
          onChange={(value) => setFilter("status", value)}
          options={[
            { value: "", label: "Any status" },
            { value: "live", label: "Live" },
            { value: "ended", label: "Ended" },
          ]}
        />
      </FilterBar>
      <QueryBoundary query={query}>
        {(data) => (
          <>
            <DataTable
              caption="Meetings"
              columns={COLUMNS}
              rows={data.items}
              getRowKey={(row) => row.room_id}
              getRowHref={(row) => meetingHref(row.room_id)}
              busy={query.isRefreshing}
              empty={
                active ? (
                  <EmptyState icon={<SearchX size={20} />} title="No meetings match these filters" action={<Button size="sm" onClick={clear}>Clear filters</Button>} />
                ) : (
                  <EmptyState icon={<History size={20} />} title="No meetings yet" description="Meetings appear here once a room is created." />
                )
              }
            />
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={(next) => setFilter("page", next)} />
          </>
        )}
      </QueryBoundary>
    </>
  );
}
