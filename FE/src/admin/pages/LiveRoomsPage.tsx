import { Radio, SearchX } from "lucide-react";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { CustomSelect } from "../../components/CustomSelect";
import { EmptyState } from "../../components/ui/EmptyState";
import type { RoomStatus } from "../api/types";
import { useAdminApi } from "../auth/AdminSession";
import { Pagination } from "../components/DataTable";
import { LiveRoomsTable } from "../components/LiveRoomsTable";
import { FilterBar, LiveIndicator, PageHeader, QueryBoundary, SearchInput } from "../components/Page";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { AI_MODE_OPTIONS, LANGUAGE_OPTIONS, useUrlFilters } from "../lib/filters";
import { ROOM_STATUS_LABELS } from "../lib/format";

const LIVE_ROOMS_POLL_MS = 5_000;
const PAGE_SIZE = 25;
const FILTER_KEYS = ["q", "status", "ai_mode", "language"] as const;
const STATUSES: RoomStatus[] = ["live", "error", "empty", "expired"];

export function LiveRoomsPage() {
  const api = useAdminApi();
  const { values, page, setFilter, clear, active } = useUrlFilters(FILTER_KEYS);
  const key = JSON.stringify({ ...values, page });
  // useAdminQuery keeps the latest fetcher; `key` decides when to refetch.
  const query = useAdminQuery(`live-rooms:${key}`, () => api.liveRooms({ ...values, page, page_size: PAGE_SIZE }), {
    intervalMs: LIVE_ROOMS_POLL_MS,
  });
  const counts = query.data?.counts_by_status ?? {};

  return (
    <>
      <PageHeader
        title="Live Rooms"
        description="Every room that still exists in the live store, refreshed every few seconds."
        actions={<LiveIndicator query={query} />}
      />
      <FilterBar
        trailing={active ? <Button size="sm" variant="ghost" onClick={clear}>Clear filters</Button> : null}
      >
        <SearchInput label="Search room ID" placeholder="Search room ID" value={values.q} onChange={(value) => setFilter("q", value)} />
        <CustomSelect
          ariaLabel="Status"
          size="compact"
          value={values.status}
          onChange={(value) => setFilter("status", value)}
          options={[
            { value: "", label: "All statuses" },
            ...STATUSES.map((status) => ({ value: status, label: `${ROOM_STATUS_LABELS[status]} (${counts[status] ?? 0})` })),
          ]}
        />
        <CustomSelect ariaLabel="AI mode" size="compact" value={values.ai_mode} onChange={(value) => setFilter("ai_mode", value)} options={AI_MODE_OPTIONS} />
        <CustomSelect ariaLabel="Language" size="compact" value={values.language} onChange={(value) => setFilter("language", value)} options={LANGUAGE_OPTIONS} />
      </FilterBar>

      <QueryBoundary query={query}>
        {(data) => (
          <>
            {data.runtime_online === false ? (
              <Alert tone="danger">
                The BRSE runtime has not sent a heartbeat. AI relay is not running in any room until it is back.
              </Alert>
            ) : null}
            <LiveRoomsTable
              rows={data.items}
              busy={query.isRefreshing}
              empty={
                active ? (
                  <EmptyState icon={<SearchX size={20} />} title="No rooms match these filters" action={<Button size="sm" onClick={clear}>Clear filters</Button>} />
                ) : (
                  <EmptyState icon={<Radio size={20} />} title="No rooms right now" description="Rooms appear here as soon as someone creates one." />
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
