import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertCircle, AlertTriangle, CheckCircle2, Info, MessageSquareText, Radio } from "lucide-react";
import { ApiError } from "../../lib/api";
import { Badge } from "../../components/ui/Badge";
import { EmptyState } from "../../components/ui/EmptyState";
import { buttonClassName } from "../../components/ui/Button";
import type { LiveParticipant, LiveRoomDetail, RoomBrseState, TimelineItem } from "../api/types";
import { useAdminApi } from "../auth/AdminSession";
import { DataTable, type Column } from "../components/DataTable";
import { KeyValueList, LiveIndicator, PageHeader, QueryBoundary, Section, Tabs, Unavailable } from "../components/Page";
import { RelayTimeline } from "../components/RelayTimeline";
import { AiStateBadge, RoomStatusBadge } from "../components/StatusBadges";
import { TranscriptList } from "../components/TranscriptList";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { diagnoseRoom, type Finding } from "../lib/diagnosis";
import {
  AI_MODE_LABELS,
  accessLabel,
  formatClock,
  formatDateTime,
  formatMs,
  formatRelative,
  formatTimeLeft,
  humanize,
  languageName,
  languageShort,
} from "../lib/format";

const DETAIL_POLL_MS = 4_000;
const TIMELINE_POLL_MS = 4_000;
const TRANSCRIPT_POLL_MS = 6_000;

type TranscriptFilter = "all" | "source" | "relay" | "chat" | "system";

const FINDING_ICONS = { error: AlertCircle, warning: AlertTriangle, info: Info, ok: CheckCircle2 } as const;

function Diagnosis({ findings }: { findings: Finding[] }) {
  return (
    <ul className="adm-findings" aria-label="Diagnosis">
      {findings.map((finding) => {
        const Icon = FINDING_ICONS[finding.severity];
        return (
          <li key={`${finding.area}:${finding.title}`} className={`adm-finding is-${finding.severity}`}>
            <Icon size={16} aria-hidden="true" />
            <div>
              <p className="adm-finding-title">
                {finding.title}
                <span className="adm-finding-area">{humanize(finding.area)}</span>
              </p>
              <p className="adm-finding-detail">{finding.detail}</p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function MediaState({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-tertiary">—</span>;
  const tone = value === "on" ? "success" : value === "muted" ? "warning" : "neutral";
  return <Badge tone={tone} dot>{humanize(value)}</Badge>;
}

const PARTICIPANT_COLUMNS: Array<Column<LiveParticipant>> = [
  {
    key: "name",
    header: "Name",
    render: (participant) => (
      <span className="adm-cell-stack">
        <strong>{participant.display_name}</strong>
        {participant.is_virtual ? <span className="text-tertiary">Virtual participant</span> : null}
      </span>
    ),
  },
  { key: "language", header: "Language", render: (participant) => (participant.is_virtual ? "Auto" : languageName(participant.language)) },
  {
    key: "connection",
    header: "Connection",
    render: (participant) => (
      <span className="adm-cell-stack">
        <span>{humanize(participant.status)}</span>
        <span className="text-tertiary">
          {participant.is_virtual
            ? "Runtime participant"
            : [participant.ws_connected ? "Signaling ✓" : "Signaling ✗", participant.media?.connection ? `Media ${participant.media.connection}` : null]
                .filter(Boolean)
                .join(" · ")}
        </span>
      </span>
    ),
  },
  { key: "mic", header: "Mic", render: (participant) => (participant.is_virtual ? "—" : <MediaState value={participant.media?.microphone} />) },
  { key: "camera", header: "Camera", render: (participant) => (participant.is_virtual ? "—" : <MediaState value={participant.media?.camera} />), hideOnNarrow: true },
  {
    key: "share",
    header: "Screen share",
    render: (participant) => (participant.is_screen_sharing ? <Badge tone="info" dot>Sharing</Badge> : <span className="text-tertiary">Off</span>),
    hideOnNarrow: true,
  },
  { key: "joined", header: "Joined", render: (participant) => formatClock(participant.joined_at, true), hideOnNarrow: true },
];

function BrsePanel({ brse }: { brse: RoomBrseState }) {
  const last = brse.latency.last ?? {};
  const median = (key: "stt_ms" | "first_text_ms" | "first_audio_ms" | "total_ms") => brse.latency[key]?.p50 ?? null;
  const latencyRows: Array<{ label: string; key: "stt_ms" | "first_text_ms" | "first_audio_ms" | "total_ms" }> = [
    { label: "STT", key: "stt_ms" },
    { label: "Translation (first text)", key: "first_text_ms" },
    { label: "AI voice (first audio)", key: "first_audio_ms" },
    { label: "Total relay", key: "total_ms" },
  ];
  return (
    <div className="adm-brse">
      <div className="adm-brse-state">
        <AiStateBadge state={brse.state} />
        <span className="text-secondary">{AI_MODE_LABELS[brse.ai_mode]}</span>
        {brse.runtime_attached === false ? <Badge tone="danger" outline>Runtime not attached</Badge> : null}
      </div>
      <KeyValueList
        items={[
          { label: "Current speaker", value: brse.current_speaker_name ?? brse.current_speaker_id ?? "—" },
          { label: "Queue depth", value: brse.queue_depth ?? "—" },
          { label: "Last successful relay", value: brse.last_success_at ? formatRelative(brse.last_success_at) : "None yet" },
          {
            label: "Last problem",
            value: brse.last_error ? (
              <span className="adm-cell-stack">
                <span>{humanize(brse.last_error.issue_code ?? brse.last_error.code)}</span>
                <span className="text-tertiary">{formatRelative(brse.last_error.occurred_at)}{brse.last_error.message ? ` · ${brse.last_error.message}` : ""}</span>
              </span>
            ) : "None",
          },
          ...(brse.audio_suppressed_reason ? [{ label: "AI voice", value: humanize(brse.audio_suppressed_reason) }] : []),
        ]}
      />
      {brse.speakers.length ? (
        <>
          <h3 className="adm-subheading">Per speaker</h3>
          <ul className="adm-speakers">
            {brse.speakers.map((speaker) => (
              <li key={speaker.speaker_id}>
                <span className="adm-speaker-name">{speaker.speaker_name ?? speaker.speaker_id}</span>
                <span className="text-tertiary">
                  {languageShort(speaker.source_language)} → {languageShort(speaker.target_language)}
                  {speaker.pending_relay_count ? ` · ${speaker.pending_relay_count} queued` : ""}
                </span>
                <AiStateBadge state={speaker.status} />
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <h3 className="adm-subheading">Latency</h3>
      <table className="adm-table adm-latency-table">
        <caption className="sr-only">Relay latency in this room</caption>
        <thead>
          <tr>
            <th scope="col">Stage</th>
            <th scope="col" className="is-right">Last relay</th>
            <th scope="col" className="is-right" title="Median of recent utterances (needs 5+ samples)">p50</th>
          </tr>
        </thead>
        <tbody>
          {latencyRows.map((row) => (
            <tr key={row.key}>
              <td>{row.label}</td>
              <td className="is-right">{formatMs(last[row.key] ?? null)}</td>
              <td className="is-right">{formatMs(median(row.key))}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="adm-footnote">Translation and AI voice come from the same realtime response, so their timings overlap.</p>
    </div>
  );
}

function TimelineSection({ roomId, onLoaded }: { roomId: string; onLoaded?: (items: TimelineItem[]) => void }) {
  const api = useAdminApi();
  const query = useAdminQuery(`timeline:${roomId}`, async () => {
    const response = await api.roomTimeline(roomId, 60);
    onLoaded?.(response.items);
    return response;
  }, { intervalMs: TIMELINE_POLL_MS });
  return (
    <Section
      id="timeline"
      title="Relay timeline"
      description="One entry per utterance: where it went through STT → validation → policy → translation → voice → delivery. Text is joined from the transcript; nothing here is audio."
      actions={<LiveIndicator query={query} />}
    >
      <QueryBoundary query={query}>
        {(data) =>
          data.items.length ? (
            <RelayTimeline items={data.items} />
          ) : (
            <EmptyState icon={<Radio size={20} />} title="No relay activity yet" description="Entries appear when someone speaks while BRSE AI is on." />
          )
        }
      </QueryBoundary>
    </Section>
  );
}

function TranscriptSection({ roomId }: { roomId: string }) {
  const api = useAdminApi();
  const [filter, setFilter] = useState<TranscriptFilter>("all");
  const query = useAdminQuery(`transcript:${roomId}:${filter}`, () => api.roomTranscript(roomId, filter), {
    intervalMs: TRANSCRIPT_POLL_MS,
  });
  return (
    <Section id="transcript" title="Recent transcript" actions={<LiveIndicator query={query} />}>
      <Tabs
        idPrefix="room-transcript"
        label="Transcript filter"
        active={filter}
        onChange={setFilter}
        tabs={[
          { id: "all", label: "All" },
          { id: "source", label: "Source" },
          { id: "relay", label: "Relay" },
          { id: "chat", label: "Chat" },
          { id: "system", label: "System" },
        ]}
      />
      <div id="room-transcript-panel" role="tabpanel" aria-labelledby={`room-transcript-tab-${filter}`}>
        <QueryBoundary query={query}>
          {(data) =>
            data.items.length ? (
              <>
                <TranscriptList lines={data.items.slice().reverse()} />
                {data.limit_note ? <p className="adm-footnote">{data.limit_note}</p> : null}
              </>
            ) : (
              <EmptyState icon={<MessageSquareText size={20} />} title="Nothing here yet" />
            )
          }
        </QueryBoundary>
      </div>
    </Section>
  );
}

function RoomHeader({ detail }: { detail: LiveRoomDetail }) {
  const { room } = detail;
  return (
    <KeyValueList
      items={[
        { label: "Status", value: <RoomStatusBadge status={room.status} /> },
        { label: "Created", value: formatDateTime(room.created_at) },
        { label: "Expires", value: formatClock(room.expires_at) },
        { label: "Time left", value: formatTimeLeft(room.seconds_left) },
        { label: "AI mode", value: AI_MODE_LABELS[room.ai_mode] },
        { label: "Access", value: accessLabel(room.password_protected) },
        { label: "Participants", value: `${room.participants_online} online · ${room.participants_total} joined` },
      ]}
    />
  );
}

export function LiveRoomDetailPage() {
  const { roomId = "" } = useParams();
  const api = useAdminApi();
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const query = useAdminQuery(`room:${roomId}`, () => api.liveRoom(roomId), { intervalMs: DETAIL_POLL_MS });
  const notFound = query.error instanceof ApiError && query.error.status === 404;
  const languages = query.data?.room.room_languages ?? [];

  if (notFound && !query.data) {
    return (
      <>
        <PageHeader title={<span className="mono">{roomId}</span>} breadcrumb={{ label: "Live Rooms", to: "/admin/live-rooms" }} />
        <EmptyState
          icon={<Radio size={20} />}
          title="This room is no longer live"
          description="It expired or was never created. Its archive, if any, is in Meetings."
          action={<Link className={buttonClassName({ variant: "secondary" })} to={`/admin/meetings/${encodeURIComponent(roomId)}`}>Open meeting history</Link>}
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        breadcrumb={{ label: "Live Rooms", to: "/admin/live-rooms" }}
        title={<span className="mono">{roomId}</span>}
        description={languages.length ? languages.map(languageName).join(" ⇄ ") : undefined}
        actions={
          <>
            <LiveIndicator query={query} />
            <Link className={buttonClassName({ variant: "secondary", size: "sm" })} to={`/admin/meetings/${encodeURIComponent(roomId)}`}>
              Meeting history
            </Link>
          </>
        }
      />
      <QueryBoundary query={query} skeletonLines={8}>
        {(detail) => (
          <>
            <RoomHeader detail={detail} />
            <Section title="Diagnosis" description="Derived from the participants, BRSE state and the last few utterances below.">
              <Diagnosis findings={diagnoseRoom(detail, timeline)} />
            </Section>
            <div className="adm-grid-2">
              <Section title="Participants" description="Meeting media is never recorded or monitored; only track state is shown.">
                {detail.media_source === "unavailable" ? (
                  <Unavailable title="Mic / camera state unavailable">LiveKit's server API could not be reached, so only signaling state is shown.</Unavailable>
                ) : null}
                <DataTable
                  caption="Participants"
                  columns={PARTICIPANT_COLUMNS}
                  rows={detail.participants}
                  getRowKey={(participant) => participant.participant_id}
                  empty={<EmptyState title="No one has joined" />}
                />
              </Section>
              <Section title="BRSE AI">
                <BrsePanel brse={detail.brse} />
              </Section>
            </div>
          </>
        )}
      </QueryBoundary>
      {!notFound ? (
        <>
          <TimelineSection roomId={roomId} onLoaded={setTimeline} />
          <TranscriptSection roomId={roomId} />
        </>
      ) : null}
    </>
  );
}
