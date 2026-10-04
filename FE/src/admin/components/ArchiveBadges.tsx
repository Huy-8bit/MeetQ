import { Badge } from "../../components/ui/Badge";
import type { ArchiveRecordingSummary, ArchiveStatus } from "../api/types";

const ARCHIVE_LABELS: Record<ArchiveStatus, string> = {
  open: "Meeting live",
  finalizing: "Archiving",
  processing_recording: "Processing recording",
  ready: "Archived",
  partial: "Archived · recording failed",
  failed: "Archive failed",
  deleting: "Deleting",
  deleted: "Deleted",
};

export function ArchiveStatusBadge({ status }: { status: ArchiveStatus }) {
  const tone =
    status === "ready" ? "success" : status === "failed" ? "danger" : status === "partial" ? "warning" : status === "deleted" ? "neutral" : "info";
  return (
    <Badge tone={tone} dot>
      {ARCHIVE_LABELS[status] ?? status}
    </Badge>
  );
}

/** "None" means no recording; the meeting's data can still be archived. */
export function RecordingStatusBadge({ summary }: { summary: ArchiveRecordingSummary }) {
  if (summary.status === "none") return <span className="adm-muted">None</span>;
  if (summary.status === "ready") return <Badge tone="success">Ready{summary.count > 1 ? ` · ${summary.count}` : ""}</Badge>;
  if (summary.status === "processing") return <Badge tone="info">Processing</Badge>;
  if (summary.status === "partial") return <Badge tone="warning">Partial</Badge>;
  return <Badge tone="danger">Failed</Badge>;
}
