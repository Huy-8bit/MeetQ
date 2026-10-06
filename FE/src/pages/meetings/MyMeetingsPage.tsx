import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Search, Video } from "lucide-react";
import { UserMenu } from "../../auth/UserMenu";
import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button, buttonClassName } from "../../components/ui/Button";
import { CustomSelect } from "../../components/CustomSelect";
import { EmptyState } from "../../components/ui/EmptyState";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { SkeletonLines } from "../../components/ui/Spinner";
import { ApiError } from "../../lib/api";
import { formatMeetingLanguageBridge } from "../../lib/languages";
import { recordingApi } from "../../lib/recordingApi";
import { formatExpiresIn } from "../../lib/recordingFormat";
import { formatMeetingTitle, roleLabel } from "../../lib/roomRoles";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import type { MeetingLanguage } from "../../types/api";
import type {
  MeetingListFilter,
  MeetingListRange,
  MeetingRow,
  Paged,
  RecordingSummary,
  SearchResultItem,
  SearchResults,
} from "../../types/recording";
import { SearchResultList } from "./SearchResultList";

const PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 300;

export function RecordingSummaryBadge({ summary }: { summary: RecordingSummary }) {
  if (summary.status === "none") return <span className="text-tertiary">None</span>;
  if (summary.status === "ready") return <Badge tone="success">Ready</Badge>;
  if (summary.status === "processing") return <Badge tone="warning">Processing</Badge>;
  if (summary.status === "partial") return <Badge tone="warning">Partly failed</Badge>;
  return <Badge tone="danger">Failed</Badge>;
}

export function formatMeetingDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

export function formatMeetingDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return `${formatMeetingDate(value)} · ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

export function formatMinutes(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  return `${Math.max(1, Math.round(seconds / 60))} min`;
}

const FILTERS: Array<{ value: MeetingListFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "created", label: "Created by me" },
  { value: "recorded", label: "Recorded" },
  { value: "summary", label: "With summary" },
];

const RANGES: Array<{ value: MeetingListRange; label: string }> = [
  { value: "all", label: "Any time" },
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
];

function recordingLabel(summary: RecordingSummary): { text: string; tone: "success" | "warning" | "danger" | "neutral" } | null {
  if (summary.status === "ready") return { text: "Recording available", tone: "success" };
  if (summary.status === "processing") return { text: "Recording is being prepared", tone: "warning" };
  if (summary.status === "partial") return { text: "Recording partly failed", tone: "warning" };
  if (summary.status === "failed") return { text: "Recording failed", tone: "danger" };
  return null;
}

function MeetingCard({ row }: { row: MeetingRow }) {
  const title = formatMeetingTitle(row.title, row.room_languages);
  const recording = recordingLabel(row.recording);
  const role = roleLabel(row.my_role);
  const live = row.meeting_state === "live";
  const when = row.ended_at ?? row.meeting_started_at ?? row.created_at;
  return (
    <li className="meeting-card card">
      <div className="card-body meeting-card-body">
        <div className="meeting-card-head">
          <Link to={`/meetings/${row.room_id}`} className="meeting-card-title">
            {title}
          </Link>
          <div className="meeting-card-badges">
            {live ? <Badge tone="accent" dot pulse>In progress</Badge> : null}
            {role ? <Badge>{role}</Badge> : null}
          </div>
        </div>
        <p className="meeting-card-languages">
          {row.title ? `${formatMeetingLanguageBridge(row.room_languages as MeetingLanguage[])} · ` : ""}
          <span className="mono">{row.room_id}</span>
        </p>
        <p className="meeting-card-meta">
          {[
            formatMeetingDateTime(when),
            row.duration_seconds ? formatMinutes(row.duration_seconds) : null,
            row.participant_count ? `${row.participant_count} ${row.participant_count === 1 ? "participant" : "participants"}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
        <div className="meeting-card-badges">
          {row.summary_status === "completed" ? <Badge tone="success">Summary ready</Badge> : null}
          {recording ? <Badge tone={recording.tone}>{recording.text}</Badge> : <span className="text-tertiary">No recording</span>}
        </div>
        {row.expires_at ? (
          <p className="meeting-card-expiry text-tertiary" title={new Date(row.expires_at).toLocaleString()}>
            Available until {formatMeetingDate(row.expires_at)} · {formatExpiresIn(row.expires_at).replace("Expires in ", "")} left
          </p>
        ) : null}
      </div>
    </li>
  );
}

/** Meetings the signed-in user created or joined, newest first, while they are retained. */
export function MyMeetingsPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<MeetingListFilter>("all");
  const [range, setRange] = useState<MeetingListRange>("all");
  // The page belongs to one search/filter combination; changing either starts at page 1.
  const [pageState, setPageState] = useState({ key: "", page: 1 });
  const [data, setData] = useState<Paged<MeetingRow> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [content, setContent] = useState<SearchResults | null>(null);
  const [contentError, setContentError] = useState<string | null>(null);
  const debouncedQuery = useDebouncedValue(query.trim(), SEARCH_DEBOUNCE_MS);
  const searching = debouncedQuery.length > 0;
  const listKey = `${debouncedQuery}\u0000${filter}\u0000${range}`;
  const page = pageState.key === listKey ? pageState.page : 1;
  const setPage = (update: (value: number) => number) => setPageState({ key: listKey, page: update(page) });

  useEffect(() => {
    let cancelled = false;
    setError(null);
    recordingApi
      .listMeetings({ page, pageSize: PAGE_SIZE, q: debouncedQuery, filter, range })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((caught) => {
        if (cancelled) return;
        setError(
          caught instanceof ApiError && caught.status === 422 ? caught.message : "Couldn't load your meetings.",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [page, debouncedQuery, filter, range]);

  // Content search runs on the server across your own meetings only.
  useEffect(() => {
    if (!searching) {
      setContent(null);
      setContentError(null);
      return;
    }
    let cancelled = false;
    recordingApi
      .searchAll(debouncedQuery)
      .then((result) => {
        if (!cancelled) {
          setContent(result);
          setContentError(null);
        }
      })
      .catch((caught) => {
        if (cancelled) return;
        setContent(null);
        setContentError(caught instanceof ApiError && caught.status === 422 ? caught.message : null);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery, searching]);

  async function loadMoreContent() {
    if (!content) return;
    const next = await recordingApi.searchAll(debouncedQuery, content.page + 1);
    setContent({ ...next, items: [...content.items, ...next.items] });
  }

  function openResult(item: SearchResultItem) {
    const params = new URLSearchParams({ tab: item.source_type });
    if (item.cursor) params.set("at", item.cursor);
    if (item.source_item_id) params.set("item", item.source_item_id);
    navigate(`/meetings/${item.meeting_id}?${params.toString()}`);
  }

  const rows = data?.items ?? null;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const filtered = searching || filter !== "all" || range !== "all";

  return (
    <div className="page">
      <header className="page-header">
        <div className="page-header-bar">
          <Link to="/" className={buttonClassName({ variant: "ghost", size: "sm", className: "page-back" })}>
            <ArrowLeft size={16} aria-hidden="true" />
            Home
          </Link>
          <UserMenu />
        </div>
        <h1 className="page-title">My meetings</h1>
        <p className="page-description">
          Meetings you created or joined, with their recordings, summaries and transcripts. Everything is deleted
          automatically when its retention period ends, so download what you need to keep.
        </p>
      </header>

      <main className="meetings-main">
        <div className="meetings-toolbar">
          <label className="meetings-search">
            <Search size={16} aria-hidden="true" />
            <span className="sr-only">Search meetings</span>
            <input
              className="input"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search meetings…"
              maxLength={100}
            />
          </label>
          <SegmentedControl<MeetingListFilter> ariaLabel="Filter meetings" value={filter} onChange={setFilter} options={FILTERS} />
          <div className="meetings-range">
            <CustomSelect<MeetingListRange> ariaLabel="Date range" value={range} onChange={setRange} options={RANGES} size="compact" />
          </div>
        </div>

        {error ? <Alert tone="danger">{error}</Alert> : null}
        {!rows && !error ? <SkeletonLines count={4} /> : null}
        {rows && rows.length === 0 ? (
          <EmptyState
            icon={<Video size={20} />}
            title={filtered ? "No meetings match" : "No meetings yet"}
            description={
              filtered
                ? "Try a different search or filter."
                : "Meetings you create or join appear here."
            }
          />
        ) : null}
        {rows && rows.length > 0 ? (
          <>
            <ul className="meeting-cards" aria-label="Meetings">
              {rows.map((row) => (
                <MeetingCard key={row.room_id} row={row} />
              ))}
            </ul>
            {pages > 1 ? (
              <nav className="pager" aria-label="Pages">
                <Button size="sm" onClick={() => setPage((value) => value - 1)} disabled={page <= 1}>
                  Previous
                </Button>
                <span className="text-secondary">
                  Page {page} of {pages}
                </span>
                <Button size="sm" onClick={() => setPage((value) => value + 1)} disabled={page >= pages}>
                  Next
                </Button>
              </nav>
            ) : null}
          </>
        ) : null}

        {searching ? (
          <section className="meetings-content-search" aria-labelledby="content-search-title">
            <h2 className="section-title" id="content-search-title">
              In meeting content
            </h2>
            <p className="field-helper">Keyword matches in transcripts, relay, chat and summaries of your meetings.</p>
            {contentError ? <Alert tone="warning">{contentError}</Alert> : null}
            {content && content.items.length > 0 ? (
              <>
                <SearchResultList items={content.items} total={content.total} showMeeting onOpen={openResult} />
                {content.items.length < content.total ? (
                  <Button size="sm" onClick={() => void loadMoreContent()}>
                    Show more results
                  </Button>
                ) : null}
              </>
            ) : content ? (
              <p className="text-secondary">No matches in meeting content.</p>
            ) : null}
          </section>
        ) : null}
      </main>
    </div>
  );
}
