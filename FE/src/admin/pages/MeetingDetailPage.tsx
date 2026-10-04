import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { FileText, History, MessageSquare, Radio, Users } from "lucide-react";
import { ApiError } from "../../lib/api";
import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button, buttonClassName } from "../../components/ui/Button";
import { CustomSelect } from "../../components/CustomSelect";
import { EmptyState } from "../../components/ui/EmptyState";
import type { MeetingDetail, MeetingParticipantRow, RelayRow } from "../api/types";
import { useAdminApi } from "../auth/AdminSession";
import { DataTable, Pagination, type Column } from "../components/DataTable";
import { KeyValueList, PageHeader, QueryBoundary, Section, Tabs, errorMessage } from "../components/Page";
import { OutcomeBadge, SummaryStatusBadge } from "../components/StatusBadges";
import { SummaryView } from "../components/SummaryView";
import { TranscriptList } from "../components/TranscriptList";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { LANGUAGE_OPTIONS } from "../lib/filters";
import {
  AI_MODE_LABELS,
  accessLabel,
  formatClock,
  formatDateTime,
  formatDuration,
  formatMs,
  formatNumber,
  humanize,
  languageName,
  languageShort,
} from "../lib/format";

type TabId = "overview" | "transcript" | "relay" | "chat" | "summary" | "participants";
const TAB_IDS: TabId[] = ["overview", "transcript", "relay", "chat", "summary", "participants"];

function OverviewTab({ detail }: { detail: MeetingDetail }) {
  const { meeting, counts } = detail;
  return (
    <KeyValueList
      items={[
        { label: "Room ID", value: <span className="mono">{meeting.room_id}</span> },
        { label: "Created", value: formatDateTime(meeting.created_at) },
        { label: "Started", value: formatDateTime(detail.activated_at) },
        { label: "Ended", value: meeting.ended_at ? `${formatDateTime(meeting.ended_at)}${meeting.end_reason ? ` (${humanize(meeting.end_reason).toLowerCase()})` : ""}` : meeting.status === "live" ? "Still live" : "—" },
        { label: "Duration", value: formatDuration(meeting.duration_seconds) },
        { label: "Room languages", value: meeting.room_languages.map(languageName).join(", ") || "—" },
        { label: "AI mode", value: AI_MODE_LABELS[meeting.ai_mode] },
        { label: "Access", value: accessLabel(meeting.password_protected) },
        { label: "Participants", value: formatNumber(meeting.participant_count) },
        { label: "Source transcript lines", value: formatNumber(counts.source) },
        { label: "Relay lines", value: formatNumber(counts.relay + counts.translated) },
        { label: "Chat messages", value: formatNumber(counts.chat) },
        { label: "Final summary", value: <SummaryStatusBadge status={detail.summaries.final?.status} /> },
        { label: "Live summary", value: <SummaryStatusBadge status={detail.summaries.interim?.status} /> },
      ]}
    />
  );
}

function usePage() {
  const [page, setPage] = useState(1);
  return { page, setPage };
}

function TranscriptTab({ roomId, kind }: { roomId: string; kind: "transcript" | "chat" }) {
  const api = useAdminApi();
  const { page, setPage } = usePage();
  const query = useAdminQuery(`meeting-${kind}:${roomId}:${page}`, () =>
    kind === "chat" ? api.meetingChat(roomId, page) : api.meetingTranscripts(roomId, page),
  );
  return (
    <QueryBoundary query={query}>
      {(data) =>
        data.items.length ? (
          <>
            <TranscriptList lines={data.items} showDate />
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
          </>
        ) : (
          <EmptyState
            icon={kind === "chat" ? <MessageSquare size={20} /> : <FileText size={20} />}
            title={kind === "chat" ? "No chat messages" : "No source transcript"}
            description={kind === "chat" ? undefined : "Nothing was transcribed, or BRSE AI was off for this meeting."}
          />
        )
      }
    </QueryBoundary>
  );
}

const RELAY_COLUMNS: Array<Column<RelayRow>> = [
  { key: "time", header: "Time", render: (row) => formatClock(row.created_at, true) },
  { key: "speaker", header: "Speaker", render: (row) => row.speaker_name ?? "—" },
  { key: "route", header: "Route", render: (row) => `${languageShort(row.source_language)} → ${languageShort(row.target_language)}` },
  {
    key: "text",
    header: "Original → Translation",
    className: "adm-cell-text",
    render: (row) => (
      <span className="adm-cell-stack">
        <span>{row.translation}</span>
        {row.original ? <span className="text-tertiary">{row.original}</span> : null}
        {row.relay_style === "summary" ? <Badge tone="info" outline>Overlap summary</Badge> : null}
      </span>
    ),
  },
  {
    key: "delivery",
    header: "Delivery",
    render: (row) =>
      row.delivery_state ? (
        <span className="adm-cell-stack">
          <OutcomeBadge outcome={row.delivery_state} />
          {row.voice_delivered === false ? <span className="adm-cell-warning">No AI voice</span> : null}
        </span>
      ) : (
        <span className="text-tertiary" title="Recorded before relay tracing was enabled">Not traced</span>
      ),
  },
  { key: "latency", header: "Latency", align: "right", render: (row) => formatMs(row.latency_ms) },
];

function RelayTab({ roomId }: { roomId: string }) {
  const api = useAdminApi();
  const { page, setPage } = usePage();
  const query = useAdminQuery(`meeting-relays:${roomId}:${page}`, () => api.meetingRelays(roomId, page));
  return (
    <QueryBoundary query={query}>
      {(data) => (
        <>
          <DataTable
            caption="Relay lines"
            columns={RELAY_COLUMNS}
            rows={data.items}
            getRowKey={(row) => row.id}
            empty={<EmptyState icon={<Radio size={20} />} title="No relay lines" description="Relays exist only for rooms with BRSE AI on and more than one language." />}
          />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
        </>
      )}
    </QueryBoundary>
  );
}

function SummaryTab({ detail }: { detail: MeetingDetail }) {
  const api = useAdminApi();
  const roomId = detail.meeting.room_id;
  const query = useAdminQuery(`meeting-summaries:${roomId}`, () => api.meetingSummaries(roomId));
  const [language, setLanguage] = useState(detail.summaries.final?.summary_language ?? "");
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const ended = detail.meeting.status === "ended";

  async function regenerate() {
    setRunning(true);
    setActionError(null);
    try {
      await api.regenerateFinalSummary(roomId, language || null);
      setConfirming(false);
      query.refetch();
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : errorMessage(error as Error));
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <div className="adm-summary-actions">
        {ended ? (
          <>
            <CustomSelect
              ariaLabel="Summary language"
              size="compact"
              value={language}
              onChange={setLanguage}
              options={[{ value: "", label: "Default language" }, ...LANGUAGE_OPTIONS.slice(1)]}
            />
            {confirming ? (
              <>
                <Button size="sm" variant="primary" loading={running} onClick={() => void regenerate()}>Confirm — regenerate</Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirming(false)} disabled={running}>Cancel</Button>
              </>
            ) : (
              <Button size="sm" variant="secondary" onClick={() => setConfirming(true)}>Regenerate final summary</Button>
            )}
          </>
        ) : (
          <p className="adm-footnote">The final summary can be generated only after the meeting ends.</p>
        )}
      </div>
      {confirming ? <Alert tone="info">This calls the summary model again and replaces the stored final summary for this meeting.</Alert> : null}
      {actionError ? <Alert tone="danger">{actionError}</Alert> : null}
      <QueryBoundary query={query}>
        {(data) =>
          data.final || data.interim ? (
            <div className="adm-summaries">
              {data.final ? <SummaryView summary={data.final} title="Final summary" /> : null}
              {data.interim ? <SummaryView summary={data.interim} title="Live summary (latest checkpoint)" /> : null}
            </div>
          ) : (
            <EmptyState icon={<FileText size={20} />} title="No summary for this meeting" />
          )
        }
      </QueryBoundary>
    </>
  );
}

const PARTICIPANT_COLUMNS: Array<Column<MeetingParticipantRow>> = [
  {
    key: "name",
    header: "Name",
    render: (row) => (
      <span className="adm-cell-stack">
        <strong>{row.display_name ?? row.participant_id}</strong>
        {row.is_virtual ? <span className="text-tertiary">Virtual (BRSE AI)</span> : null}
      </span>
    ),
  },
  { key: "language", header: "Language", render: (row) => (row.is_virtual ? "Auto" : languageName(row.language)) },
  { key: "joined", header: "First joined", render: (row) => formatDateTime(row.first_joined_at) },
  { key: "left", header: "Last left", render: (row) => formatDateTime(row.last_left_at) },
  { key: "joins", header: "Joins", align: "right", render: (row) => row.join_count },
];

function ParticipantsTab({ roomId }: { roomId: string }) {
  const api = useAdminApi();
  const query = useAdminQuery(`meeting-participants:${roomId}`, () => api.meetingParticipants(roomId));
  return (
    <QueryBoundary query={query}>
      {(rows) => (
        <DataTable
          caption="Participants"
          columns={PARTICIPANT_COLUMNS}
          rows={rows}
          getRowKey={(row) => row.participant_id}
          empty={<EmptyState icon={<Users size={20} />} title="No participants recorded" />}
        />
      )}
    </QueryBoundary>
  );
}

export function MeetingDetailPage() {
  const { roomId = "" } = useParams();
  const api = useAdminApi();
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as TabId | null;
  const tab: TabId = requested && TAB_IDS.includes(requested) ? requested : "overview";
  const query = useAdminQuery(`meeting:${roomId}`, () => api.meeting(roomId));
  const notFound = query.error instanceof ApiError && query.error.status === 404;

  const setTab = (next: TabId) =>
    setParams((current) => {
      const updated = new URLSearchParams(current);
      if (next === "overview") updated.delete("tab");
      else updated.set("tab", next);
      return updated;
    }, { replace: true });

  if (notFound) {
    return (
      <>
        <PageHeader title={<span className="mono">{roomId}</span>} breadcrumb={{ label: "Meetings", to: "/admin/meetings" }} />
        <EmptyState icon={<History size={20} />} title="Meeting not found in history" description="History is stored in MongoDB; rooms created while it was unavailable are not archived." />
      </>
    );
  }

  return (
    <>
      <PageHeader
        breadcrumb={{ label: "Meetings", to: "/admin/meetings" }}
        title={<span className="mono">{roomId}</span>}
        description={query.data ? query.data.meeting.room_languages.map(languageName).join(" ⇄ ") : undefined}
        actions={
          query.data?.is_live_in_runtime_store ? (
            <Link className={buttonClassName({ variant: "primary", size: "sm" })} to={`/admin/live-rooms/${encodeURIComponent(roomId)}`}>
              Open live inspector
            </Link>
          ) : undefined
        }
      />
      <QueryBoundary query={query}>
        {(detail) => (
          <>
            <Tabs
              idPrefix="meeting"
              label="Meeting sections"
              active={tab}
              onChange={setTab}
              tabs={[
                { id: "overview", label: "Overview" },
                { id: "transcript", label: "Transcript", count: detail.counts.source },
                { id: "relay", label: "Relay", count: detail.counts.relay + detail.counts.translated },
                { id: "chat", label: "Chat", count: detail.counts.chat },
                { id: "summary", label: "Summary" },
                { id: "participants", label: "Participants", count: detail.counts.participants },
              ]}
            />
            <Section title={humanize(tab)}>
              <div id="meeting-panel" role="tabpanel" aria-labelledby={`meeting-tab-${tab}`}>
                {tab === "overview" ? <OverviewTab detail={detail} /> : null}
                {tab === "transcript" ? <TranscriptTab roomId={roomId} kind="transcript" /> : null}
                {tab === "relay" ? <RelayTab roomId={roomId} /> : null}
                {tab === "chat" ? <TranscriptTab roomId={roomId} kind="chat" /> : null}
                {tab === "summary" ? <SummaryTab detail={detail} /> : null}
                {tab === "participants" ? <ParticipantsTab roomId={roomId} /> : null}
              </div>
            </Section>
          </>
        )}
      </QueryBoundary>
    </>
  );
}
