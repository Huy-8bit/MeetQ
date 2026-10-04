import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertCircle, ArrowLeft } from "lucide-react";
import { UserMenu } from "../../auth/UserMenu";
import { MeetingSummaryPanel } from "../../components/MeetingSummaryPanel";
import { RecordingList } from "../../components/RecordingList";
import { Alert } from "../../components/ui/Alert";
import { buttonClassName } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { SkeletonLines } from "../../components/ui/Spinner";
import { ApiError } from "../../lib/api";
import { getLanguageLabel, formatMeetingLanguageBridge } from "../../lib/languages";
import { recordingApi } from "../../lib/recordingApi";
import { formatExpiresIn } from "../../lib/recordingFormat";
import type { MeetingLanguage, MeetingSummaryResponse } from "../../types/api";
import type { MeetingDetailResponse, MeetingMessage } from "../../types/recording";
import { formatMeetingDate, formatMinutes } from "./MyMeetingsPage";

type Tab = "recording" | "summary" | "transcript" | "relay" | "chat" | "participants";
type MessageKind = "transcript" | "relay" | "chat";

const POLL_MS = 5000;

function loadError(error: unknown): { title: string; description: string } {
  if (error instanceof ApiError && error.status === 410) {
    return {
      title: "This meeting has expired",
      description: "Its recording, summary, transcript and chat were deleted when the retention period ended.",
    };
  }
  if (error instanceof ApiError && error.status === 404) {
    return { title: "Meeting not found", description: "You can only open meetings you took part in." };
  }
  return { title: "Couldn't load this meeting", description: "Check your connection and try again." };
}

function MessageList({ roomId, kind, total }: { roomId: string; kind: MessageKind; total: number }) {
  const [items, setItems] = useState<MeetingMessage[] | null>(null);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);

  useEffect(() => {
    let cancelled = false;
    recordingApi
      .messages(roomId, kind, page)
      .then((result) => {
        if (cancelled) return;
        setItems((current) => (page === 1 ? result.items : [...(current ?? []), ...result.items]));
        setPages(Math.max(1, Math.ceil(result.total / result.page_size)));
      })
      .catch(() => setItems((current) => current ?? []));
    return () => {
      cancelled = true;
    };
  }, [kind, page, roomId]);

  if (!items) return <SkeletonLines count={5} />;
  if (items.length === 0) return <p className="text-secondary">Nothing was recorded here.</p>;
  return (
    <div className="archive-messages">
      <ol className="archive-message-list">
        {items.map((message, index) => (
          <li key={message.message_id ?? index} className="archive-message">
            <div className="archive-message-meta">
              <strong>{message.speaker_name ?? "Participant"}</strong>
              {message.language ? <span>{getLanguageLabel(message.language as MeetingLanguage)}</span> : null}
              {message.created_at ? <time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString()}</time> : null}
            </div>
            {kind === "relay" ? (
              <>
                {message.source_text ? <p className="text-secondary">{message.source_text}</p> : null}
                <p>{message.translated_text ?? message.text}</p>
              </>
            ) : (
              <p>{message.text}</p>
            )}
          </li>
        ))}
      </ol>
      {page < pages ? (
        <button type="button" className="link-button" onClick={() => setPage((value) => value + 1)}>
          Show more ({total - items.length} left)
        </button>
      ) : null}
    </div>
  );
}

export function MyMeetingDetailPage() {
  const { roomId = "" } = useParams();
  const [detail, setDetail] = useState<MeetingDetailResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<Tab>("recording");

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

  return (
    <div className="page">
      <header className="page-header">
        {header}
        <h1 className="page-title">{formatMeetingLanguageBridge(meeting.room_languages as MeetingLanguage[])}</h1>
        <p className="page-description">
          {[meeting.ended_at ? formatMeetingDate(meeting.ended_at) : "In progress", meeting.duration_seconds ? formatMinutes(meeting.duration_seconds) : null]
            .filter(Boolean)
            .join(" · ")}{" "}
          · <span className="mono">{meeting.room_id}</span>
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
        <SegmentedControl<Tab>
          ariaLabel="Meeting archive sections"
          value={tab}
          onChange={setTab}
          options={[
            { value: "recording", label: `Recording${recordings.length > 1 ? ` (${recordings.length})` : ""}` },
            { value: "summary", label: "Summary" },
            { value: "transcript", label: "Transcript" },
            { value: "relay", label: "Relay" },
            { value: "chat", label: "Chat" },
            { value: "participants", label: "People" },
          ]}
        />
        <section className="card">
          <div className="card-body">
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
            {tab === "transcript" ? <MessageList roomId={roomId} kind="transcript" total={counts.transcript} /> : null}
            {tab === "relay" ? <MessageList roomId={roomId} kind="relay" total={counts.relay} /> : null}
            {tab === "chat" ? <MessageList roomId={roomId} kind="chat" total={counts.chat} /> : null}
            {tab === "participants" ? (
              <ul className="archive-people">
                {participants
                  .filter((p) => p.kind === "human")
                  .map((p) => (
                    <li key={p.participant_id ?? p.display_name ?? ""}>
                      <strong>{p.display_name}</strong>
                      {p.is_you ? <span className="text-tertiary"> (you)</span> : null}
                      {p.language ? <span className="text-secondary"> · {getLanguageLabel(p.language as MeetingLanguage)}</span> : null}
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
