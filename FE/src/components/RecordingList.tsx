import { useState } from "react";
import { Download, Play } from "lucide-react";
import { ApiError } from "../lib/api";
import { recordingApi } from "../lib/recordingApi";
import { formatBytes, formatElapsed } from "../lib/recordingFormat";
import type { RecordingState } from "../types/recording";
import { Alert } from "./ui/Alert";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Spinner } from "./ui/Spinner";

function timeRange(recording: RecordingState): string {
  const fmt = (value: string | null) =>
    value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "…";
  return `${fmt(recording.started_at ?? recording.requested_at)} – ${fmt(recording.stopped_at)}`;
}

function urlError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 410) return "This recording has expired and was deleted.";
    if (error.code === "recording_not_ready") return "The recording is still being prepared.";
  }
  return "Couldn't open the recording. Try again.";
}

function StatusBadge({ recording }: { recording: RecordingState }) {
  if (recording.status === "ready") return <Badge tone="success">Ready</Badge>;
  if (recording.status === "failed") return <Badge tone="danger">Failed</Badge>;
  return <Badge tone="warning">Processing</Badge>;
}

/** Recording segments with play/download. URLs are short-lived and requested on click. */
export function RecordingList({ recordings }: { recordings: RecordingState[] }) {
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [playUrl, setPlayUrl] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function play(recording: RecordingState) {
    setBusyId(recording.recording_id);
    setError(null);
    try {
      const { url } = await recordingApi.playbackUrl(recording.recording_id);
      setPlayingId(recording.recording_id);
      setPlayUrl(url);
    } catch (caught) {
      setError(urlError(caught));
    } finally {
      setBusyId(null);
    }
  }

  async function download(recording: RecordingState) {
    setBusyId(recording.recording_id);
    setError(null);
    try {
      const { url } = await recordingApi.downloadUrl(recording.recording_id);
      const link = document.createElement("a");
      link.href = url;
      link.rel = "noopener";
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (caught) {
      setError(urlError(caught));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="recording-list">
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {recordings.map((recording, index) => (
        <div className="recording-item" key={recording.recording_id}>
          <div className="recording-item-head">
            <div className="recording-item-text">
              <span className="recording-item-title">
                {recordings.length > 1 ? `Recording ${index + 1}` : "Recording"}
                <StatusBadge recording={recording} />
              </span>
              <span className="recording-item-meta">
                {timeRange(recording)}
                {recording.duration_seconds ? ` · ${formatElapsed(recording.duration_seconds)}` : ""}
                {recording.size_bytes ? ` · ${formatBytes(recording.size_bytes)}` : ""}
              </span>
            </div>
            {recording.status === "ready" ? (
              <div className="recording-item-actions">
                <Button
                  size="sm"
                  variant="primary"
                  icon={<Play size={14} />}
                  loading={busyId === recording.recording_id && playingId !== recording.recording_id}
                  onClick={() => void play(recording)}
                >
                  Play
                </Button>
                <Button size="sm" variant="secondary" icon={<Download size={14} />} onClick={() => void download(recording)}>
                  Download
                </Button>
              </div>
            ) : recording.status === "failed" ? (
              <span className="text-secondary recording-item-note">This segment could not be recorded.</span>
            ) : (
              <span className="text-secondary recording-item-note">
                <Spinner /> Recording is being prepared.
              </span>
            )}
          </div>
          {playingId === recording.recording_id && playUrl ? (
            <video className="recording-player" src={playUrl} controls autoPlay preload="metadata" />
          ) : null}
        </div>
      ))}
    </div>
  );
}
