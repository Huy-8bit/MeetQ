import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { shouldPlayHumanAudio } from "../lib/livekit";
import { useSessionStore } from "../state/session";
import type { Language, RoomSnapshotResponse } from "../types/api";
import { AudioTrackSink } from "../components/MediaElements";
import { JoinRoomCard } from "../components/JoinRoomCard";
import { ConnectionBadge } from "../components/ConnectionBadge";
import { InterpreterStatusPanel } from "../components/InterpreterStatusPanel";
import { ParticipantList } from "../components/ParticipantList";
import { ParticipantTile } from "../components/ParticipantTile";
import { TranscriptPanel } from "../components/TranscriptPanel";
import { useMeetingRoom } from "../features/room/useMeetingRoom";

const APP_VERSION = "0.1.0";

export function RoomPage() {
  const navigate = useNavigate();
  const params = useParams();
  const roomId = params.roomId ?? "";
  const { getSession, saveSession, clearSession } = useSessionStore();
  const [roomSnapshot, setRoomSnapshot] = useState<RoomSnapshotResponse | null>(null);
  const [loadingSnapshot, setLoadingSnapshot] = useState(true);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);
  const session = getSession(roomId);
  const handleSessionInvalidated = useCallback(() => {
    clearSession(roomId);
  }, [clearSession, roomId]);

  useEffect(() => {
    if (!roomId) {
      setSnapshotError("Room id is missing.");
      setLoadingSnapshot(false);
      return;
    }

    let cancelled = false;
    setLoadingSnapshot(true);
    setSnapshotError(null);

    void (async () => {
      try {
        const response = await api.getRoom(roomId);
        if (!cancelled) {
          setRoomSnapshot(response);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }

        setSnapshotError(
          error instanceof ApiError
            ? mapRoomSnapshotError(error)
            : "Could not load room details.",
        );
      } finally {
        if (!cancelled) {
          setLoadingSnapshot(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [roomId]);

  const meeting = useMeetingRoom({
    roomId,
    initialRoom: roomSnapshot,
    session,
    onSessionInvalidated: handleSessionInvalidated,
  });

  async function handleJoin(payload: {
    displayName: string;
    language: Language;
  }) {
    if (!roomId) {
      return;
    }

    setJoining(true);
    setJoinError(null);

    try {
      const response = await api.joinRoom(roomId, {
        display_name: payload.displayName,
        language: payload.language,
        client: {
          sdk: "web",
          version: APP_VERSION,
        },
      });
      saveSession(response);
    } catch (error) {
      setJoinError(
        error instanceof ApiError
          ? mapJoinError(error)
          : "Could not join room. Check backend availability.",
      );
    } finally {
      setJoining(false);
    }
  }

  if (loadingSnapshot && !roomSnapshot && !session) {
    return (
      <main className="room-boot">
        <div className="empty-state">
          <strong>Loading room</strong>
          <p>Fetching room snapshot from the gateway.</p>
        </div>
      </main>
    );
  }

  if (snapshotError && !roomSnapshot && !session) {
    return (
      <main className="room-boot">
        <div className="empty-state">
          <strong>Room unavailable</strong>
          <p>{snapshotError}</p>
          <button className="button-secondary" onClick={() => navigate("/")}>
            Back Home
          </button>
        </div>
      </main>
    );
  }

  if (!session) {
    if (!roomSnapshot) {
      return null;
    }

    return (
      <main className="room-boot">
        <JoinRoomCard
          room={roomSnapshot.room}
          participants={roomSnapshot.participants}
          onJoin={handleJoin}
          isSubmitting={joining}
          error={joinError}
        />
      </main>
    );
  }

  return (
    <main className="room-page">
      <header className="room-header panel">
        <div>
          <span className="eyebrow">Room {roomId}</span>
          <h1>{meeting.selfState?.display_name || "Meeting Room"}</h1>
          <p>
            Listening language controls translated audio routing and transcript targeting.
          </p>
        </div>

        <div className="room-header-actions">
          <ConnectionBadge state={meeting.connectionState} />

          <label className="compact-field">
            <span>Language</span>
            <select
              value={meeting.selfState?.language || session.participant.language}
              onChange={(event) =>
                meeting.changeLanguage(event.target.value as Language)
              }
            >
              <option value="vi">VI</option>
              <option value="en">EN</option>
              <option value="ja">JA</option>
            </select>
          </label>

          <button
            className="button-danger"
            onClick={() => {
              void meeting.leaveRoom().then(() => navigate("/"));
            }}
            disabled={meeting.isLeaving}
          >
            {meeting.isLeaving ? "Leaving..." : "Leave Room"}
          </button>
        </div>
      </header>

      {meeting.connectionError ? (
        <div className="banner banner-danger">{meeting.connectionError}</div>
      ) : null}
      {meeting.mediaError ? (
        <div className="banner banner-warning">{meeting.mediaError}</div>
      ) : null}

      <div className="room-layout">
        <section className="video-stage">
          <div className="video-grid">
            {meeting.videos.map((feed) => (
              <ParticipantTile
                key={feed.participantId}
                feed={feed}
                label={
                  feed.isLocal
                    ? "You"
                    : meeting.participants.find(
                        (participant) => participant.participant_id === feed.participantId,
                      )?.status || "Participant"
                }
              />
            ))}
          </div>

          <ParticipantList
            participants={meeting.participants}
            selfParticipantId={meeting.selfState?.participant_id}
          />

          <div className="audio-sinks" aria-hidden="true">
            {meeting.humanAudioFeeds
              .filter((feed) =>
                shouldPlayHumanAudio(
                  feed.language,
                  meeting.selfState?.language || session.participant.language,
                ),
              )
              .map((feed) => (
                <AudioTrackSink
                  key={`human-${feed.participantId}-${feed.track.sid}`}
                  track={feed.track}
                />
              ))}

            {meeting.interpreterAudioFeeds.map((feed) => (
              <AudioTrackSink
                key={`interp-${feed.trackSid}`}
                track={feed.track}
              />
            ))}
          </div>
        </section>

        <aside className="sidebar-stack">
          <InterpreterStatusPanel statuses={meeting.interpreterStatuses} />
          <TranscriptPanel entries={meeting.transcripts} />
        </aside>
      </div>
    </main>
  );
}

function mapRoomSnapshotError(error: ApiError): string {
  if (error.code === "room_not_found") {
    return "Room not found.";
  }
  return error.message;
}

function mapJoinError(error: ApiError): string {
  if (error.code === "room_full") {
    return "Room is full.";
  }
  if (error.code === "room_not_found") {
    return "Room not found.";
  }
  if (error.code === "livekit_unavailable") {
    return "LiveKit is unavailable right now.";
  }
  if (error.code === "invalid_display_name") {
    return "Display name must be 1 to 40 characters.";
  }
  return error.message;
}
