import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Video } from "lucide-react";
import { UserMenu } from "../../auth/UserMenu";
import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { buttonClassName } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { SkeletonLines } from "../../components/ui/Spinner";
import { formatMeetingLanguageBridge } from "../../lib/languages";
import { recordingApi } from "../../lib/recordingApi";
import { formatExpiresIn } from "../../lib/recordingFormat";
import type { MeetingLanguage } from "../../types/api";
import type { MeetingRow, RecordingSummary } from "../../types/recording";

export function RecordingSummaryBadge({ summary }: { summary: RecordingSummary }) {
  if (summary.status === "none") return <span className="text-tertiary">None</span>;
  if (summary.status === "ready") return <Badge tone="success">Ready</Badge>;
  if (summary.status === "processing") return <Badge tone="warning">Processing</Badge>;
  if (summary.status === "partial") return <Badge tone="warning">Partly failed</Badge>;
  return <Badge tone="danger">Failed</Badge>;
}

export function formatMeetingDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

export function formatMinutes(seconds: number | null): string {
  if (!seconds) return "—";
  return `${Math.max(1, Math.round(seconds / 60))} min`;
}

/** Meetings this signed-in user took part in, while their archive is retained. */
export function MyMeetingsPage() {
  const [rows, setRows] = useState<MeetingRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    recordingApi
      .listMeetings()
      .then((page) => setRows(page.items))
      .catch(() => setError("Couldn't load your meetings."));
  }, []);

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
          Meetings you joined, with their recordings, summaries and transcripts. Everything is deleted automatically when
          its retention period ends, so download what you need to keep.
        </p>
      </header>

      <main>
        {error ? <Alert tone="danger">{error}</Alert> : null}
        {!rows && !error ? <SkeletonLines count={4} /> : null}
        {rows && rows.length === 0 ? (
          <EmptyState
            icon={<Video size={20} />}
            title="No meetings yet"
            description="Meetings you join appear here after they end."
          />
        ) : null}
        {rows && rows.length > 0 ? (
          <div className="table-wrap card">
            <table className="data-table meetings-table">
              <thead>
                <tr>
                  <th scope="col">Meeting</th>
                  <th scope="col">Date</th>
                  <th scope="col">Duration</th>
                  <th scope="col">Recording</th>
                  <th scope="col">Expires</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.room_id}>
                    <td>
                      <Link to={`/meetings/${row.room_id}`} className="meetings-room-link">
                        {formatMeetingLanguageBridge(row.room_languages as MeetingLanguage[])}
                      </Link>
                      <span className="mono text-tertiary meetings-room-id">{row.room_id}</span>
                    </td>
                    <td>{formatMeetingDate(row.ended_at)}</td>
                    <td>{formatMinutes(row.duration_seconds)}</td>
                    <td>
                      <RecordingSummaryBadge summary={row.recording} />
                    </td>
                    <td title={row.expires_at ? new Date(row.expires_at).toLocaleString() : undefined}>
                      {formatExpiresIn(row.expires_at).replace("Expires in ", "") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </main>
    </div>
  );
}
