import { Link } from "react-router-dom";
import { Film, SearchX } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { Alert } from "../../components/ui/Alert";
import { EmptyState } from "../../components/ui/EmptyState";
import { formatBytes } from "../../lib/recordingFormat";
import type { ArchiveRow } from "../api/types";
import { useAdminApi } from "../auth/AdminSession";
import { ArchiveStatusBadge, RecordingStatusBadge } from "../components/ArchiveBadges";
import { DataTable, Pagination, type Column } from "../components/DataTable";
import { FilterBar, PageHeader, QueryBoundary, SearchInput } from "../components/Page";
import { CustomSelect } from "../../components/CustomSelect";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { useUrlFilters } from "../lib/filters";
import { formatDateTime, languageList } from "../lib/format";

const PAGE_SIZE = 25;
const FILTER_KEYS = ["q", "filter"] as const;
type ArchiveFilter = "all" | "ready" | "processing" | "failed" | "expiring_soon" | "expired";

export const archiveHref = (archiveId: string) => `/admin/recordings/${encodeURIComponent(archiveId)}`;

const COLUMNS: Array<Column<ArchiveRow>> = [
  { key: "room", header: "Room", render: (row) => <Link className="adm-mono-link" to={archiveHref(row.archive_id)}>{row.room_id}</Link> },
  { key: "languages", header: "Languages", render: (row) => languageList(row.room_languages), hideOnNarrow: true },
  { key: "ended", header: "Ended", render: (row) => formatDateTime(row.ended_at) },
  { key: "participants", header: "Participants", align: "right", render: (row) => row.participant_count ?? "—", hideOnNarrow: true },
  { key: "recording", header: "Recording", render: (row) => <RecordingStatusBadge summary={row.recording} /> },
  {
    key: "duration",
    header: "Duration",
    align: "right",
    render: (row) => (row.recording.total_duration_seconds ? `${Math.round(row.recording.total_duration_seconds / 60)} min` : "—"),
    hideOnNarrow: true,
  },
  { key: "size", header: "Size", align: "right", render: (row) => formatBytes(row.recording.total_bytes) },
  {
    key: "retention",
    header: "Retention",
    render: (row) => `${row.retention_days} days${row.retention_source === "custom" ? " (custom)" : ""}`,
  },
  { key: "expires", header: "Expires", render: (row) => (row.deleted_at ? `Deleted ${formatDateTime(row.deleted_at)}` : formatDateTime(row.expires_at)) },
  { key: "status", header: "Archive", render: (row) => <ArchiveStatusBadge status={row.status} /> },
];

export function RecordingsPage() {
  const api = useAdminApi();
  const { values, page, setFilter, clear, active } = useUrlFilters(FILTER_KEYS);
  const filter = (values.filter || "all") as ArchiveFilter;
  const query = useAdminQuery(
    `archives:${JSON.stringify({ ...values, page })}`,
    () => api.archives({ q: values.q, filter, page, page_size: PAGE_SIZE }),
    { intervalMs: 15000 },
  );

  return (
    <>
      <PageHeader
        title="Recordings & archives"
        description="Every ended meeting is archived: recording (if someone pressed Record), transcript, relay, chat and summaries. Everything is deleted when the archive expires."
        actions={<Button size="sm" variant="secondary" onClick={query.refetch} loading={query.isRefreshing}>Refresh</Button>}
      />
      <FilterBar trailing={active ? <Button size="sm" variant="ghost" onClick={clear}>Clear filters</Button> : null}>
        <SearchInput label="Search room ID" placeholder="Room ID" value={values.q} onChange={(value) => setFilter("q", value)} />
        <CustomSelect<ArchiveFilter>
          ariaLabel="Archive filter"
          size="compact"
          value={filter}
          onChange={(next) => setFilter("filter", next === "all" ? "" : next)}
          options={[
            { value: "all", label: "All archives" },
            { value: "ready", label: "Recording ready" },
            { value: "processing", label: "Processing" },
            { value: "failed", label: "Failed" },
            { value: "expiring_soon", label: "Expiring in 48 h" },
            { value: "expired", label: "Expired / deleted" },
          ]}
        />
      </FilterBar>
      <QueryBoundary query={query}>
        {(data) => (
          <>
            {!data.storage_configured ? (
              <Alert tone="warning">
                No archive bucket is configured (MEETING_ARCHIVE_BUCKET). Meeting data stays in MongoDB and still expires;
                recording is unavailable.
              </Alert>
            ) : null}
            <DataTable
              caption="Meeting archives"
              columns={COLUMNS}
              rows={data.items}
              getRowKey={(row) => row.archive_id}
              getRowHref={(row) => archiveHref(row.archive_id)}
              busy={query.isRefreshing}
              empty={
                active ? (
                  <EmptyState icon={<SearchX size={20} />} title="No archives match" action={<Button size="sm" onClick={clear}>Clear filters</Button>} />
                ) : (
                  <EmptyState icon={<Film size={20} />} title="No archives yet" description="Meetings are archived here when they end." />
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
