import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { useSessionStore } from "../state/session";
import type { Language, RoomSnapshotResponse } from "../types/api";
import { AudioTrackSink, VideoTrackView } from "../components/MediaElements";
import { JoinRoomCard } from "../components/JoinRoomCard";
import { ConnectionBadge } from "../components/ConnectionBadge";
import { AudioDevicePanel } from "../components/AudioDevicePanel";
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

  const activeScreenShareParticipants = meeting.participants.filter(
    (participant) => participant.is_screen_sharing,
  );
  const selectedScreenSharer =
    activeScreenShareParticipants.find(
      (participant) => participant.participant_id === meeting.selfState?.participant_id,
    ) || activeScreenShareParticipants[0] || null;
  const selectedScreenFeed = selectedScreenSharer
    ? meeting.screenShares.find(
        (feed) => feed.participantId === selectedScreenSharer.participant_id,
      ) || null
    : null;

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
            {meeting.meetingMode === "brse_relay"
              ? "Everyone hears original human audio. BRSE AI joins as a virtual participant and relays across languages."
              : "Language still controls meeting interpretation behavior for this room."}
          </p>
        </div>

        <div className="room-header-actions">
          <ConnectionBadge state={meeting.connectionState} />

          <label className="compact-field">
            <span>Your Language</span>
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
            className="button-secondary"
            onClick={() => {
              if (meeting.isScreenSharing) {
                void meeting.stopScreenShare({ reason: "manual_stop" });
                return;
              }

              void meeting.startScreenShare();
            }}
            disabled={
              meeting.isStartingScreenShare
              || meeting.isStoppingScreenShare
              || meeting.isLeaving
            }
          >
            {meeting.isStartingScreenShare
              ? "Requesting screen permission..."
              : meeting.isStoppingScreenShare
                ? "Stopping share..."
                : meeting.isScreenSharing
                  ? "Stop sharing screen"
                  : "Start sharing screen"}
          </button>

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
      {meeting.screenShareError ? (
        <div className="banner banner-warning">{meeting.screenShareError}</div>
      ) : null}

      <div className="room-layout">
        <section className="video-stage">
          <section className="panel screen-stage-panel">
            <div className="panel-header">
              <div>
                <h3>Shared Screen Stage</h3>
                <p>
                  {selectedScreenSharer
                    ? `${selectedScreenSharer.display_name} is sharing screen`
                    : "No active screen share"}
                </p>
              </div>
              <span className="panel-count">{activeScreenShareParticipants.length}</span>
            </div>

            {selectedScreenSharer ? (
              <div className="screen-stage-frame">
                {selectedScreenFeed?.track ? (
                  <VideoTrackView track={selectedScreenFeed.track} />
                ) : (
                  <div className="screen-stage-placeholder">
                    <strong>{selectedScreenSharer.display_name}</strong>
                    <p>Screen stream is starting or reconnecting.</p>
                  </div>
                )}
              </div>
            ) : (
              <div className="empty-state small">
                <strong>No one is sharing screen</strong>
                <p>Start sharing to present documents, code, or slides to the room.</p>
              </div>
            )}
          </section>

          <div className="video-grid">
            {meeting.videos.map((feed) => (
              <ParticipantTile
                key={feed.participantId}
                feed={feed}
                isScreenSharing={Boolean(
                  meeting.participants.find(
                    (participant) => participant.participant_id === feed.participantId,
                  )?.is_screen_sharing,
                )}
                label={
                  feed.isLocal
                    ? "You"
                    : feed.kind === "virtual_brse"
                      ? "AI BRSE relay"
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
            {meeting.humanAudioFeeds.map((feed) => (
              <AudioTrackSink
                key={`human-${feed.participantId}-${feed.track.sid}`}
                track={feed.track}
                onOutputDeviceError={meeting.reportAudioOutputApplyError}
              />
            ))}

            {meeting.brseAudioFeeds.map((feed) => (
              <AudioTrackSink
                key={`brse-${feed.trackSid}`}
                track={feed.track}
                onOutputDeviceError={meeting.reportAudioOutputApplyError}
              />
            ))}
          </div>
        </section>

        <aside className="sidebar-stack">
          <AudioDevicePanel
            isMicMuted={meeting.isMicMuted}
            isTogglingMic={meeting.isTogglingMic}
            micToggleError={meeting.micToggleError}
            onToggleMic={() => {
              void meeting.toggleMicrophoneMuted();
            }}
            audioInputDevices={meeting.audioInputDevices}
            selectedAudioInputDeviceId={meeting.selectedAudioInputDeviceId}
            isSwitchingAudioInput={meeting.isSwitchingAudioInput}
            audioInputError={meeting.audioInputError}
            onSelectAudioInput={(deviceId) => {
              void meeting.switchAudioInput(deviceId);
            }}
            audioOutputSupported={meeting.audioOutputSupported}
            audioOutputDevices={meeting.audioOutputDevices}
            selectedAudioOutputDeviceId={meeting.selectedAudioOutputDeviceId}
            isSwitchingAudioOutput={meeting.isSwitchingAudioOutput}
            audioOutputError={meeting.audioOutputError}
            onSelectAudioOutput={(deviceId) => {
              void meeting.switchAudioOutput(deviceId);
            }}
          />
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
