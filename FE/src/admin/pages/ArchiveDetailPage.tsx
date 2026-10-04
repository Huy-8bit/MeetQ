import { useState } from "react";
import { useParams } from "react-router-dom";
import { Trash2 } from "lucide-react";
import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { ApiError } from "../../lib/api";
import { formatBytes, formatElapsed } from "../../lib/recordingFormat";
import type { ArchiveDetailResponse } from "../api/types";
import { useAdminApi } from "../auth/AdminSession";
import { ArchiveStatusBadge, RecordingStatusBadge } from "../components/ArchiveBadges";
import { KeyValueList, PageHeader, QueryBoundary, Section } from "../components/Page";
import { useAdminQuery } from "../hooks/useAdminQuery";
import { formatDateTime, humanize, languageList } from "../lib/format";

const MIN_DAYS = 1;
const MAX_DAYS = 365;

function RetentionEditor({ detail, onSaved }: { detail: ArchiveDetailResponse; onSaved: () => void }) {
  const api = useAdminApi();
  const { archive } = detail;
  const snapshot = archive.default_retention_days_snapshot ?? detail.system_default_retention_days;
  const [days, setDays] = useState(String(archive.retention_days));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingExpire, setPendingExpire] = useState<{ body: Record<string, unknown>; expiresAt: string | null } | null>(null);
  const parsed = Number(days);
  const valid = Number.isInteger(parsed) && parsed >= MIN_DAYS && parsed <= MAX_DAYS;
  const ended = archive.ended_at ? new Date(archive.ended_at) : null;
  const preview = ended && valid ? new Date(ended.getTime() + parsed * 86_400_000) : null;
  const deleted = archive.status === "deleted";

  async function save(body: { retention_days?: number; use_default?: boolean; confirm_expire?: boolean }) {
    setSaving(true);
    setError(null);
    try {
      await api.updateArchiveRetention(archive.archive_id, body);
      setPendingExpire(null);
      onSaved();
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "retention_expires_immediately") {
        setPendingExpire({ body, expiresAt: (caught.details?.expires_at as string | undefined) ?? null });
      } else {
        setError(caught instanceof ApiError ? caught.message : "Couldn't save the retention.");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section title="Data retention" description="Recording, transcript, relay, chat, summaries and participant data share this expiry.">
      <KeyValueList
        items={[
          { label: "Policy", value: archive.retention_source === "custom" ? <Badge tone="info">Custom</Badge> : <Badge>Default</Badge> },
          { label: "Retention", value: `${archive.retention_days} days` },
          { label: "Default for this archive", value: `${snapshot} days (system default when the meeting was archived)` },
          { label: "Meeting ended", value: formatDateTime(archive.ended_at) },
          { label: "Expires", value: formatDateTime(archive.expires_at) },
        ]}
      />
      {!deleted ? (
        <form
          className="adm-retention-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (valid) void save({ retention_days: parsed });
          }}
        >
          <label className="adm-retention-field">
            <span>Retention (days)</span>
            <input
              className="input"
              type="number"
              min={MIN_DAYS}
              max={MAX_DAYS}
              step={1}
              value={days}
              onChange={(event) => setDays(event.target.value)}
              aria-describedby="retention-preview"
            />
          </label>
          <p id="retention-preview" className="adm-muted">
            {valid ? (preview ? `New expiry: ${formatDateTime(preview.toISOString())}` : "Expiry is set when the meeting ends.") : `Enter ${MIN_DAYS}–${MAX_DAYS} days.`}
          </p>
          <div className="adm-retention-actions">
            <Button type="submit" variant="primary" size="sm" disabled={!valid || saving} loading={saving}>
              Save
            </Button>
            {archive.retention_source === "custom" ? (
              <Button type="button" variant="secondary" size="sm" disabled={saving} onClick={() => void save({ use_default: true })}>
                Use default ({snapshot} days)
              </Button>
            ) : null}
          </div>
          {error ? <Alert tone="danger">{error}</Alert> : null}
        </form>
      ) : null}
      <ConfirmDialog
        open={pendingExpire !== null}
        title="Expire this meeting now?"
        tone="danger"
        confirmLabel="Apply and expire"
        busy={saving}
        onCancel={() => setPendingExpire(null)}
        onConfirm={() => pendingExpire && void save({ ...pendingExpire.body, confirm_expire: true })}
      >
        <p>This meeting is already older than the new retention period.</p>
        <p>Applying this change makes it eligible for deletion immediately: its recording and all meeting content will be removed.</p>
      </ConfirmDialog>
    </Section>
  );
}

export function ArchiveDetailPage() {
  const { archiveId = "" } = useParams();
  const api = useAdminApi();
  const query = useAdminQuery(`archive:${archiveId}`, () => api.archive(archiveId), { intervalMs: 15000 });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function remove() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteArchive(archiveId);
      setConfirmDelete(false);
      query.refetch();
    } catch (caught) {
      setDeleteError(caught instanceof ApiError ? caught.message : "Delete failed.");
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <QueryBoundary query={query}>
      {(detail) => {
        const { archive } = detail;
        const deleted = archive.status === "deleted";
        return (
          <>
            <PageHeader
              breadcrumb={{ label: "Recordings & archives", to: "/admin/recordings" }}
              title={<span className="adm-mono">{archive.room_id}</span>}
              description={languageList(archive.room_languages)}
              actions={
                !deleted && archive.status !== "open" ? (
                  <Button size="sm" variant="danger" icon={<Trash2 size={14} />} onClick={() => setConfirmDelete(true)}>
                    Delete now
                  </Button>
                ) : null
              }
            />
            {deleteError ? <Alert tone="danger">{deleteError}</Alert> : null}
            {deleted ? (
              <Alert tone="info">
                Deleted {formatDateTime(archive.deleted_at)} ({humanize(archive.deletion_reason ?? "")}). Only this tombstone
                remains; no meeting content is kept.
              </Alert>
            ) : null}
            <Section title="Archive">
              <KeyValueList
                items={[
                  { label: "Status", value: <ArchiveStatusBadge status={archive.status} /> },
                  { label: "Archive ID", value: <span className="adm-mono">{archive.archive_id}</span> },
                  { label: "Meeting started", value: formatDateTime(archive.meeting_started_at) },
                  { label: "Meeting ended", value: formatDateTime(archive.ended_at) },
                  { label: "Participants", value: archive.participant_count ?? "—" },
                  { label: "Recording", value: <RecordingStatusBadge summary={archive.recording} /> },
                  { label: "Storage", value: `${formatBytes(detail.storage_bytes)}${detail.s3_prefix ? ` · s3://${detail.s3_bucket}/${detail.s3_prefix}` : ""}` },
                  ...(archive.error_code ? [{ label: "Error", value: humanize(archive.error_code) }] : []),
                ]}
              />
            </Section>
            <Section title="Recording segments">
              {detail.recordings.length === 0 ? (
                <p className="adm-muted">Nobody recorded this meeting. Its transcript, relay, chat and summaries are still archived.</p>
              ) : (
                <div className="adm-table-scroll">
                  <table className="adm-table">
                    <caption className="sr-only">Recording segments</caption>
                    <thead>
                      <tr>
                        <th scope="col">Segment</th>
                        <th scope="col">Status</th>
                        <th scope="col">Started by</th>
                        <th scope="col">Time</th>
                        <th scope="col" className="is-right">Duration</th>
                        <th scope="col" className="is-right">Size</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.recordings.map((recording, index) => (
                        <tr key={recording.recording_id}>
                          <td>
                            <span className="adm-cell-stack">
                              <span>Recording {index + 1}</span>
                              <span className="adm-code">{recording.recording_id}</span>
                            </span>
                          </td>
                          <td>
                            <Badge tone={recording.status === "ready" ? "success" : recording.status === "failed" ? "danger" : "info"}>
                              {humanize(recording.status)}
                            </Badge>
                            {recording.error_code ? <span className="adm-code"> {recording.error_code}</span> : null}
                          </td>
                          <td>{recording.started_by.display_name ?? "—"}</td>
                          <td>
                            {formatDateTime(recording.started_at ?? recording.requested_at)} → {formatDateTime(recording.stopped_at)}
                          </td>
                          <td className="is-right">{recording.duration_seconds ? formatElapsed(recording.duration_seconds) : "—"}</td>
                          <td className="is-right">{formatBytes(recording.size_bytes)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>
            <RetentionEditor detail={detail} onSaved={query.refetch} />
            {detail.files.length > 0 ? (
              <Section title="Archive files" description="Private S3 objects; never public.">
                <ul className="adm-file-list">
                  {detail.files.map((file) => (
                    <li key={file.name}>
                      <span className="adm-code">{file.key}</span> <span className="adm-muted">{formatBytes(file.size)}</span>
                    </li>
                  ))}
                </ul>
              </Section>
            ) : null}
            <ConfirmDialog
              open={confirmDelete}
              title="Delete meeting archive?"
              tone="danger"
              confirmLabel="Delete permanently"
              requireText="DELETE"
              busy={deleting}
              onCancel={() => setConfirmDelete(false)}
              onConfirm={() => void remove()}
            >
              <p>This will permanently delete:</p>
              <ul>
                <li>recording{detail.recordings.length > 1 ? "s" : ""}</li>
                <li>transcript and relay</li>
                <li>chat</li>
                <li>summaries</li>
                <li>archived participant data</li>
              </ul>
              <p>
                <strong>This action cannot be undone.</strong>
              </p>
            </ConfirmDialog>
          </>
        );
      }}
    </QueryBoundary>
  );
}
