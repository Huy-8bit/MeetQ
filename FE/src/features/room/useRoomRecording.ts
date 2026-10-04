import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../lib/api";
import { recordingApi } from "../../lib/recordingApi";
import type { GatewayConnectionState } from "../../types/livekit";
import { isRecordingActive, type RecordingState } from "../../types/recording";
import type { RecordingEvent } from "../../types/ws";

export interface RecordingNotice {
  id: string;
  tone: "info" | "warning" | "danger";
  message: string;
}

/** Recordings known to this client, keyed by id. The server `version` decides which copy wins. */
export type RecordingMap = Record<string, RecordingState>;

export function mergeRecording(current: RecordingMap, incoming: RecordingState | null | undefined): RecordingMap {
  if (!incoming) return current;
  const existing = current[incoming.recording_id];
  if (existing && existing.version > incoming.version) return current;
  return { ...current, [incoming.recording_id]: incoming };
}

/** The room indicator follows the newest recording that is starting, recording or stopping. */
export function activeRecording(recordings: RecordingMap): RecordingState | null {
  const active = Object.values(recordings).filter(isRecordingActive);
  active.sort((a, b) => (b.requested_at ?? "").localeCompare(a.requested_at ?? ""));
  return active[0] ?? null;
}

export function noticeForEvent(event: RecordingEvent, previous: RecordingState | undefined): RecordingNotice | null {
  const recording = event.payload.recording;
  const id = `${recording.recording_id}:${event.type}`;
  if (event.type === "recording.started" && previous?.status !== "recording") {
    const name = recording.started_by.display_name;
    return { id, tone: "info", message: name ? `Recording started by ${name}.` : "Recording started." };
  }
  if (event.type === "recording.stopped") {
    return { id, tone: "info", message: "Recording stopped." };
  }
  if (event.type === "recording.failed" && previous?.status !== "failed") {
    return { id, tone: "danger", message: "Recording failed. The meeting continues normally." };
  }
  return null;
}

function startErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "recording_unavailable") return "Recording isn't available on this server.";
    if (error.code === "recording_failed") return "Recording couldn't start. The meeting continues normally.";
    if (error.code === "recording_busy") return "Another recording change is in progress. Try again.";
    if (error.status === 401) return "Sign in again to control recording.";
  }
  return "Couldn't change the recording. Try again.";
}

const NOTICE_MS = 6000;

interface UseRoomRecordingOptions {
  roomId: string;
  roomToken: string | null;
  gatewayState: GatewayConnectionState;
  subscribe: (listener: (event: RecordingEvent) => void) => () => void;
  /** From the room snapshot loaded before joining. */
  initial?: RecordingState | null;
  available: boolean;
}

export function useRoomRecording({ roomId, roomToken, gatewayState, subscribe, initial, available }: UseRoomRecordingOptions) {
  const [recordings, setRecordings] = useState<RecordingMap>(() => mergeRecording({}, initial));
  const recordingsRef = useRef(recordings);
  recordingsRef.current = recordings;
  const [notices, setNotices] = useState<RecordingNotice[]>([]);
  const [pending, setPending] = useState<"start" | "stop" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isAvailable, setIsAvailable] = useState(available);
  const announcedJoinRef = useRef(false);

  const pushNotice = useCallback((notice: RecordingNotice) => {
    setNotices((current) => [...current.filter((item) => item.id !== notice.id), notice]);
    window.setTimeout(() => setNotices((current) => current.filter((item) => item.id !== notice.id)), NOTICE_MS);
  }, []);

  // Realtime: every participant applies the same server events.
  useEffect(
    () =>
      subscribe((event) => {
        const incoming = event.payload.recording;
        if (!incoming || incoming.room_id !== roomId) return;
        const previous = recordingsRef.current[incoming.recording_id];
        const notice = noticeForEvent(event, previous);
        setRecordings((current) => mergeRecording(current, incoming));
        if (notice) pushNotice(notice);
      }),
    [pushNotice, roomId, subscribe],
  );

  // Join, reconnect and refresh: the server state is authoritative, never local state.
  useEffect(() => {
    if (gatewayState !== "connected" || !roomToken) return;
    let cancelled = false;
    recordingApi
      .current(roomId, roomToken)
      .then(({ recording, available: serverAvailable }) => {
        if (cancelled) return;
        setIsAvailable(serverAvailable);
        setRecordings((current) => {
          // Anything we believed was active but the server no longer lists is over.
          const next: RecordingMap = {};
          for (const [id, item] of Object.entries(current)) {
            next[id] = isRecordingActive(item) && id !== recording?.recording_id ? { ...item, status: "processing" } : item;
          }
          return mergeRecording(next, recording);
        });
        if (recording && isRecordingActive(recording) && !announcedJoinRef.current) {
          announcedJoinRef.current = true;
          pushNotice({ id: `join:${recording.recording_id}`, tone: "warning", message: "This meeting is being recorded." });
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [gatewayState, pushNotice, roomId, roomToken]);

  const active = activeRecording(recordings);

  const start = useCallback(async () => {
    if (!roomToken || pending) return;
    setPending("start");
    setError(null);
    try {
      const { recording } = await recordingApi.start(roomId, roomToken);
      setRecordings((current) => mergeRecording(current, recording));
    } catch (caught) {
      setError(startErrorMessage(caught));
    } finally {
      setPending(null);
    }
  }, [pending, roomId, roomToken]);

  const stop = useCallback(async () => {
    const target = activeRecording(recordingsRef.current);
    if (!roomToken || !target || pending) return;
    setPending("stop");
    setError(null);
    try {
      const { recording } = await recordingApi.stop(roomId, target.recording_id, roomToken);
      setRecordings((current) => mergeRecording(current, recording));
    } catch (caught) {
      setError(startErrorMessage(caught));
    } finally {
      setPending(null);
    }
  }, [pending, roomId, roomToken]);

  return {
    available: isAvailable,
    active,
    isStarting: pending === "start" || active?.status === "starting",
    isStopping: pending === "stop" || active?.status === "stopping",
    notices,
    error,
    clearError: () => setError(null),
    start,
    stop,
  };
}
