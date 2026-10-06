import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { AlertCircle, ArrowLeft, Search } from "lucide-react";
import { UserMenu } from "../../auth/UserMenu";
import { MeetingSummaryPanel } from "../../components/MeetingSummaryPanel";
import { RecordingList } from "../../components/RecordingList";
import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button, buttonClassName } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { SkeletonLines } from "../../components/ui/Spinner";
import { ApiError } from "../../lib/api";
import { formatMeetingLanguageBridge, getLanguageLabel } from "../../lib/languages";
import { recordingApi, type ContentQuery } from "../../lib/recordingApi";
import { formatExpiresIn } from "../../lib/recordingFormat";
import { formatMeetingTitle, roleLabel } from "../../lib/roomRoles";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import type { Language, MeetingLanguage, MeetingSummaryResponse } from "../../types/api";
import type {
  ChatHistoryItem,
  CursorPage,
  MeetingDetailResponse,
  RelayItem,
  SearchResultItem,
  SearchResults,
  TranscriptItem,
} from "../../types/recording";
import { formatMeetingDate, formatMeetingDateTime, formatMinutes } from "./MyMeetingsPage";
import { SearchResultList } from "./SearchResultList";

type Tab = "overview" | "recording" | "transcript" | "relay" | "chat" | "summary" | "participants";
const TABS: Tab[] = ["overview", "recording", "transcript", "relay", "chat", "summary", "participants"];

const POLL_MS = 5000;
const SEARCH_DEBOUNCE_MS = 300;

interface Focus {
  cursor: string | null;
  itemId: string | null;
}

function loadError(error: unknown): { title: string; description: string } {
  if (error instanceof ApiError && error.status === 410) {
    return {
      title: "This meeting has expired",
      description: "Its recording, summary, transcript and chat were deleted when the retention period ended.",
    };
  }
  if (error instanceof ApiError && error.status === 404) {
    return { title: "Meeting not found", description: "You can only open meetings you created or took part in." };
  }
  return { title: "Couldn't load this meeting", description: "Check your connection and try again." };
}

function language(value: string | null | undefined): string {
  return value ? getLanguageLabel(value as Language) : "";
}

function clock(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/**
 * Oldest-first list loaded a page at a time from the server (never the whole meeting).
 * Opening a search result starts the list at that item, with "Load earlier" above it.
 */
function CursorFeed<T extends { cursor: string; message_id: string | null }>({
  load,
  focus,
  renderItem,
  emptyText,
  label,
}: {
  load: (query: ContentQuery) => Promise<CursorPage<T>>;
  focus: Focus | null;
  renderItem: (item: T) => ReactNode;
  emptyText: string;
  label: string;
}) {
  const [items, setItems] = useState<T[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [prev, setPrev] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const listRef = useRef<HTMLOListElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setFailed(false);
    load({ start: focus?.cursor ?? null })
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setNext(page.next_cursor);
        setPrev(page.prev_cursor);
      })
      .catch(() => {
        if (!cancelled) {
          setItems([]);
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [load, focus?.cursor]);

  useLayoutEffect(() => {
    if (!focus?.itemId || !items) return;
    const element = listRef.current?.querySelector<HTMLElement>(`[data-item-id="${CSS.escape(focus.itemId)}"]`);
    element?.scrollIntoView?.({ block: "center" });
  }, [focus?.itemId, items]);

  async function more(direction: "next" | "prev") {
    setBusy(true);
    try {
      if (direction === "next" && next) {
        const page = await load({ cursor: next });
        setItems((current) => [...(current ?? []), ...page.items]);
        setNext(page.next_cursor);
      } else if (direction === "prev" && prev) {
        const page = await load({ before: prev });
        setItems((current) => [...page.items, ...(current ?? [])]);
        setPrev(page.prev_cursor);
      }
    } finally {
      setBusy(false);
    }
  }

  if (!items) return <SkeletonLines count={5} />;
  if (failed) return <Alert tone="warning">Couldn&apos;t load this part of the meeting.</Alert>;
  if (items.length === 0) return <p className="text-secondary">{emptyText}</p>;
  return (
    <div className="archive-messages">
      {prev ? (
        <Button size="sm" variant="ghost" onClick={() => void more("prev")} loading={busy}>
          Load earlier
        </Button>
      ) : null}
      <ol className="archive-message-list" ref={listRef} aria-label={label}>
        {items.map((item, index) => (
          <li
            key={item.message_id ?? `${item.cursor}-${index}`}
            data-item-id={item.message_id ?? undefined}
            className={["archive-message", focus?.itemId && item.message_id === focus.itemId ? "is-focused" : ""].filter(Boolean).join(" ")}
          >
            {renderItem(item)}
          </li>
        ))}
      </ol>
      {next ? (
        <Button size="sm" onClick={() => void more("next")} loading={busy}>
          Load more
        </Button>
      ) : null}
    </div>
  );
}

function TranscriptEntry({ item }: { item: TranscriptItem }) {
  return (
    <>
      <div className="archive-message-meta">
        <time dateTime={item.created_at ?? undefined}>{clock(item.created_at)}</time>
        <strong>{item.speaker_name ?? "Participant"}</strong>
        {item.language ? <span>{language(item.language)}</span> : null}
      </div>
      <p>{item.text}</p>
      {item.translations.map((translation, index) => (
        <p key={`${translation.language}-${index}`} className="archive-translation">
          <span className="archive-translation-label">Translated{translation.language ? ` · ${language(translation.language)}` : ""}</span>
          {translation.text}
        </p>
      ))}
    </>
  );
}

function RelayEntry({ item }: { item: RelayItem }) {
  return (
    <>
      <div className="archive-message-meta">
        <time dateTime={item.created_at ?? undefined}>{clock(item.created_at)}</time>
        <strong>{item.speaker_name ?? "Participant"}</strong>
        {item.source_language || item.target_language ? (
          <span>
            {language(item.source_language)} → {language(item.target_language)}
          </span>
        ) : null}
      </div>
      <p>{item.translated_text}</p>
      {item.source_text ? (
        <p className="archive-translation">
          <span className="archive-translation-label">Original</span>
          {item.source_text}
        </p>
      ) : null}
    </>
  );
}

function ChatEntry({ item }: { item: ChatHistoryItem }) {
  return (
    <>
      <div className="archive-message-meta">
        <time dateTime={item.created_at ?? undefined}>{clock(item.created_at)}</time>
        <strong>{item.sender_name ?? "Participant"}</strong>
        {item.language ? <span>{language(item.language)}</span> : null}
      </div>
      <p>{item.text}</p>
      {item.translations.map((translation) => (
        <p key={translation.language} className="archive-translation">
          <span className="archive-translation-label">{language(translation.language)}</span>
          {translation.text}
        </p>
      ))}
    </>
  );
}

function Overview({ detail }: { detail: MeetingDetailResponse }) {
  const { meeting } = detail;
  const rows: Array<[string, ReactNode]> = [
    ["Title", meeting.title || <span className="text-tertiary">No title</span>],
    ["Room ID", <span className="mono">{meeting.room_id}</span>],
    ["Languages", formatMeetingLanguageBridge(meeting.room_languages as MeetingLanguage[])],
    ["Created", formatMeetingDateTime(meeting.created_at)],
    ["Started", formatMeetingDateTime(meeting.meeting_started_at)],
    ["Ended", meeting.meeting_state === "live" ? "In progress" : formatMeetingDateTime(meeting.ended_at)],
    ["Duration", formatMinutes(meeting.duration_seconds)],
    [
      "AI relay",
      meeting.brse_enabled === false
        ? "Off"
        : meeting.relay_mode === "text_only"
          ? "Text only"
          : meeting.relay_mode === "voice_text"
            ? "Voice + Text"
            : "—",
    ],
    ["Host", meeting.host ?? "—"],
    ["Co-hosts", meeting.co_hosts && meeting.co_hosts.length > 0 ? meeting.co_hosts.join(", ") : "—"],
    ["Participants", meeting.participant_count ?? "—"],
    ["Recording", detail.recordings.length > 0 ? `${detail.recordings.length} ${detail.recordings.length === 1 ? "segment" : "segments"}` : "Not recorded"],
    ["Summary", meeting.summary_status === "completed" ? "Ready" : meeting.summary_status ? meeting.summary_status : "None"],
    ["Access", meeting.password_protected ? "Password protected" : "Anyone with the link"],
    [
      "Available until",
      meeting.expires_at ? `${formatMeetingDate(meeting.expires_at)} (${formatExpiresIn(meeting.expires_at).toLowerCase()})` : "Until the meeting is archived",
    ],
  ];
  return (
    <dl className="overview-list">
      {rows.map(([term, value]) => (
        <div key={term} className="overview-row">
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function MyMeetingDetailPage() {
  const { roomId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const initialTab = searchParams.get("tab");
  const [detail, setDetail] = useState<MeetingDetailResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<Tab>(TABS.includes(initialTab as Tab) ? (initialTab as Tab) : "overview");
  const [focus, setFocus] = useState<Focus | null>(
    searchParams.get("at") || searchParams.get("item")
      ? { cursor: searchParams.get("at"), itemId: searchParams.get("item") }
      : null,
  );
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const debouncedQuery = useDebouncedValue(query.trim(), SEARCH_DEBOUNCE_MS);

  const load = useCallback(async () => {
    try {
      setDetail(await recordingApi.meeting(roomId));
      setError(null);
    } catch (caught) {
      setError(caught);
    }
  }, [roomId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll while a recording is still being prepared; never show a broken player.
  const pending = detail?.recordings.some((r) => r.status !== "ready" && r.status !== "failed");
  useEffect(() => {
    if (!pending) return;
    const timer = window.setTimeout(() => void load(), POLL_MS);
    return () => window.clearTimeout(timer);
  }, [detail, load, pending]);

  useEffect(() => {
    if (!debouncedQuery) {
      setResults(null);
      setSearchError(null);
      return;
    }
    let cancelled = false;
    recordingApi
      .searchMeeting(roomId, debouncedQuery)
      .then((found) => {
        if (!cancelled) {
          setResults(found);
          setSearchError(null);
        }
      })
      .catch((caught) => {
        if (cancelled) return;
        setResults(null);
        setSearchError(caught instanceof ApiError && caught.status === 422 ? caught.message : "Search isn't available right now.");
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery, roomId]);

  const loadTranscript = useCallback((q: ContentQuery) => recordingApi.transcript(roomId, q), [roomId]);
  const loadRelay = useCallback((q: ContentQuery) => recordingApi.relay(roomId, q), [roomId]);
  const loadChat = useCallback((q: ContentQuery) => recordingApi.chat(roomId, q), [roomId]);

  function openResult(item: SearchResultItem) {
    setTab(item.source_type);
    setFocus(item.source_type === "summary" ? null : { cursor: item.cursor, itemId: item.source_item_id });
  }

  function changeTab(next: Tab) {
    setTab(next);
    setFocus(null);
  }

  async function loadMoreResults() {
    if (!results) return;
    const nextPage = await recordingApi.searchMeeting(roomId, debouncedQuery, results.page + 1);
    setResults({ ...nextPage, items: [...results.items, ...nextPage.items] });
  }

  const header = (
    <div className="page-header-bar">
      <Link to="/meetings" className={buttonClassName({ variant: "ghost", size: "sm", className: "page-back" })}>
        <ArrowLeft size={16} aria-hidden="true" />
        My meetings
      </Link>
      <UserMenu />
    </div>
  );

  if (error) {
    const view = loadError(error);
    return (
      <div className="page">
        <header className="page-header">{header}</header>
        <EmptyState icon={<AlertCircle size={20} />} title={view.title} description={view.description} />
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="page">
        <header className="page-header">{header}</header>
        <SkeletonLines count={6} />
      </div>
    );
  }

  const { meeting, recordings, participants, counts } = detail;
  const expiresAt = meeting.expires_at ? new Date(meeting.expires_at) : null;
  const myRole = roleLabel(meeting.my_role);

  return (
    <div className="page">
      <header className="page-header">
        {header}
        <h1 className="page-title">{formatMeetingTitle(meeting.title, meeting.room_languages)}</h1>
        <p className="page-description">
          {[
            meeting.meeting_state === "live" ? "In progress" : formatMeetingDateTime(meeting.ended_at ?? meeting.meeting_started_at),
            meeting.duration_seconds ? formatMinutes(meeting.duration_seconds) : null,
          ]
            .filter(Boolean)
            .join(" · ")}{" "}
          · <span className="mono">{meeting.room_id}</span> {myRole ? <Badge>{myRole}</Badge> : null}
        </p>
        {expiresAt ? (
          <Alert tone="info">
            Available until {expiresAt.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })} (
            {formatExpiresIn(meeting.expires_at).toLowerCase()}). Recording, summary, transcript and chat are deleted
            after that.
          </Alert>
        ) : null}
      </header>

      <main className="archive-detail">
        <section className="meeting-search" aria-label="Search this meeting">
          <label className="meetings-search">
            <Search size={16} aria-hidden="true" />
            <span className="sr-only">Search this meeting</span>
            <input
              className="input"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search this meeting…"
              maxLength={100}
            />
          </label>
          {searchError ? <p className="field-helper">{searchError}</p> : null}
          {results ? (
            results.items.length > 0 ? (
              <>
                <SearchResultList items={results.items} total={results.total} onOpen={openResult} />
                {results.items.length < results.total ? (
                  <Button size="sm" onClick={() => void loadMoreResults()}>
                    Show more results
                  </Button>
                ) : null}
              </>
            ) : (
              <p className="text-secondary" role="status">
                No results for “{results.query}”.
              </p>
            )
          ) : null}
        </section>

        <div className="archive-tabs">
          <SegmentedControl<Tab>
            ariaLabel="Meeting sections"
            value={tab}
            onChange={changeTab}
            options={[
              { value: "overview", label: "Overview" },
              { value: "recording", label: `Recording${recordings.length > 1 ? ` (${recordings.length})` : ""}` },
              { value: "transcript", label: `Transcript${counts.transcript ? ` (${counts.transcript})` : ""}` },
              { value: "relay", label: "Relay" },
              { value: "chat", label: `Chat${counts.chat ? ` (${counts.chat})` : ""}` },
              { value: "summary", label: "Summary" },
              { value: "participants", label: "Participants" },
            ]}
          />
        </div>
        <section className="card">
          <div className="card-body">
            {tab === "overview" ? <Overview detail={detail} /> : null}
            {tab === "recording" ? (
              recordings.length > 0 ? (
                <RecordingList recordings={recordings} />
              ) : (
                <p className="text-secondary">This meeting wasn&apos;t recorded.</p>
              )
            ) : null}
            {tab === "summary" ? (
              <MeetingSummaryPanel
                summary={(detail.summary as MeetingSummaryResponse | null) ?? null}
                intent="final"
                roomEnded
                embedded
                onRefreshInterim={() => undefined}
                onCheckInterim={() => undefined}
                onCheckFinal={() => void load()}
                onPrepareFinal={() => void load()}
              />
            ) : null}
            {tab === "transcript" ? (
              <CursorFeed<TranscriptItem>
                label="Transcript"
                load={loadTranscript}
                focus={focus}
                emptyText="Nothing was transcribed in this meeting."
                renderItem={(item) => <TranscriptEntry item={item} />}
              />
            ) : null}
            {tab === "relay" ? (
              <CursorFeed<RelayItem>
                label="AI relay"
                load={loadRelay}
                focus={focus}
                emptyText="No AI relay in this meeting."
                renderItem={(item) => <RelayEntry item={item} />}
              />
            ) : null}
            {tab === "chat" ? (
              <CursorFeed<ChatHistoryItem>
                label="Chat"
                load={loadChat}
                focus={focus}
                emptyText="No chat messages in this meeting."
                renderItem={(item) => <ChatEntry item={item} />}
              />
            ) : null}
            {tab === "participants" ? (
              <ul className="archive-people">
                {participants
                  .filter((p) => p.kind === "human")
                  .map((p) => (
                    <li key={p.participant_id ?? p.display_name ?? ""} className="archive-person">
                      <span className="archive-person-name">
                        <strong>{p.display_name}</strong>
                        {p.is_you ? <span className="text-tertiary"> (you)</span> : null}
                        {roleLabel(p.role) ? <Badge>{roleLabel(p.role)}</Badge> : null}
                        {p.removed ? <Badge tone="danger">Removed</Badge> : null}
                      </span>
                      <span className="text-secondary">
                        {[
                          p.language ? language(p.language) : null,
                          p.joined_at ? `Joined ${clock(p.joined_at)}` : null,
                          p.left_at ? `Left ${clock(p.left_at)}` : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </li>
                  ))}
              </ul>
            ) : null}
          </div>
        </section>
      </main>
    </div>
  );
}
