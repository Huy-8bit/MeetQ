import { useEffect, useState } from "react";
import { Circle, Square } from "lucide-react";
import { formatElapsed } from "../lib/recordingFormat";
import type { RecordingState } from "../types/recording";
import { Spinner } from "./ui/Spinner";
import { ConfirmDialog } from "./ui/ConfirmDialog";

function useElapsed(startedAt: string | null | undefined): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);
  return startedAt ? (now - new Date(startedAt).getTime()) / 1000 : 0;
}

/** Always-visible room indicator while a recording is starting, running or stopping. */
export function RecordingIndicator({ recording }: { recording: RecordingState | null }) {
  const elapsed = useElapsed(recording?.status === "recording" ? recording.started_at : null);
  if (!recording) return null;
  if (recording.status === "starting") {
    return (
      <span className="rec-indicator is-pending" role="status">
        <Spinner /> Starting recording…
      </span>
    );
  }
  if (recording.status === "stopping") {
    return (
      <span className="rec-indicator is-pending" role="status">
        <Spinner /> Stopping recording…
      </span>
    );
  }
  if (recording.status !== "recording") return null;
  return (
    <span className="rec-indicator" role="status" aria-label={`This meeting is being recorded, ${formatElapsed(elapsed)}`}>
      <span className="rec-dot" aria-hidden="true" />
      REC <span className="rec-time">{formatElapsed(elapsed)}</span>
    </span>
  );
}

interface RecordButtonProps {
  recording: RecordingState | null;
  isStarting: boolean;
  isStopping: boolean;
  disabled?: boolean;
  onStart: () => void;
  onStop: () => void;
}

/** Control-bar button. Starting always goes through a confirmation that the room will be notified. */
export function RecordButton({ recording, isStarting, isStopping, disabled = false, onStart, onStop }: RecordButtonProps) {
  const [confirming, setConfirming] = useState(false);
  const isRecording = recording?.status === "recording";
  const busy = isStarting || isStopping;
  const label = isStarting ? "Starting…" : isStopping ? "Stopping…" : isRecording ? "Stop recording" : "Record";

  return (
    <>
      <button
        className={`control-btn ${isRecording ? "is-recording" : "is-on"}`}
        type="button"
        onClick={() => (isRecording ? onStop() : setConfirming(true))}
        disabled={disabled || busy}
        aria-label={label}
        aria-busy={busy || undefined}
        title={label}
      >
        <span className="control-btn-icon" aria-hidden="true">
          {busy ? <Spinner /> : isRecording ? <Square size={16} /> : <Circle size={18} className="rec-icon" />}
        </span>
        <span className="control-btn-label">{label}</span>
      </button>
      <ConfirmDialog
        open={confirming}
        title="Start recording?"
        confirmLabel="Start recording"
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          onStart();
        }}
      >
        <p>Everyone in this meeting will be notified that recording has started.</p>
        <p className="text-secondary">
          The recording captures the meeting&apos;s audio, video, screen sharing and AI voice. It is stored privately and
          deleted automatically when the meeting&apos;s retention period ends.
        </p>
      </ConfirmDialog>
    </>
  );
}
