import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { recordingApi } from "../lib/recordingApi";
import { formatExpiresIn } from "../lib/recordingFormat";
import type { MeetingDetailResponse } from "../types/recording";
import { RecordingList } from "./RecordingList";

const POLL_MS = 5000;

/** Meeting Ended (S4): recording status until ready. Shows nothing if the meeting wasn't recorded. */
export function MeetingRecordingSection({ roomId }: { roomId: string }) {
  const [detail, setDetail] = useState<MeetingDetailResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = async () => {
      try {
        const next = await recordingApi.meeting(roomId);
        if (cancelled) return;
        setDetail(next);
        const pending = next.recordings.some((r) => r.status !== "ready" && r.status !== "failed");
        if (pending) timer = window.setTimeout(load, POLL_MS);
      } catch {
        // Not a participant, history unavailable or expired: nothing to show.
      }
    };
    void load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [roomId]);

  if (!detail || detail.recordings.length === 0) return null;
  return (
    <section className="ended-body card" aria-labelledby="ended-recording-title">
      <div className="card-body ended-recording">
        <div className="ended-recording-head">
          <h2 className="card-title" id="ended-recording-title">
            Recording
          </h2>
          {detail.meeting.expires_at ? (
            <span className="text-secondary">{formatExpiresIn(detail.meeting.expires_at)}</span>
          ) : null}
        </div>
        <RecordingList recordings={detail.recordings} />
        <Link to={`/meetings/${roomId}`} className="link-button">
          Open meeting archive
        </Link>
      </div>
    </section>
  );
}
