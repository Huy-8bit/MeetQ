import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertCircle } from "lucide-react";
import { api, ApiError } from "../lib/api";
import {
  formatRoomLanguageList,
} from "../lib/languages";
import { getBrseModeDescription } from "../lib/brseModes";
import { useSessionStore } from "../state/session";
import { useRoomExpiry } from "../features/room/useRoomExpiry";
import type {
  MeetingLanguage,
  ParticipantSnapshot,
  RoomSnapshotResponse,
} from "../types/api";
import { AudioTrackSink } from "../components/MediaElements";
import { ChatPanel } from "../components/ChatPanel";
import { JoinRoomCard } from "../components/JoinRoomCard";
import { AudioDevicePanel } from "../components/AudioDevicePanel";
import { AiRelaySettingsPanel } from "../components/AiRelaySettingsPanel";
import { ParticipantList } from "../components/ParticipantList";
import { BrseRelayPanel } from "../components/BrseRelayPanel";
import { MeetingSummaryPanel } from "../components/MeetingSummaryPanel";
import { MeetingStage, type PinnedStageTarget } from "../components/MeetingStage";
import { MeetingViewPanel } from "../components/MeetingViewPanel";
import { RoomControlBar } from "../components/RoomControlBar";
import { RecordButton, RecordingIndicator } from "../components/RecordingControls";
import { MeetingRecordingSection } from "../components/MeetingRecordingSection";
import { useRoomRecording } from "../features/room/useRoomRecording";
import { RoomSidePanel, type RoomPanelTab } from "../components/RoomSidePanel";
import { RoomTopBar } from "../components/RoomTopBar";
import { SettingsDrawer } from "../components/SettingsDrawer";
import { useMeetingRoom } from "../features/room/useMeetingRoom";
import {
  applyThemePreference,
  loadRoomLayoutPreference,
  loadThemePreference,
  saveRoomLayoutPreference,
  saveThemePreference,
  type AppThemeMode,
  type RoomLayoutMode,
} from "../lib/uiPreferences";
import { Alert } from "../components/ui/Alert";
import { buttonClassName } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { Spinner } from "../components/ui/Spinner";

const APP_VERSION = "0.1.0";
// Below this width the side panel overlays the stage, so start with it closed.
const SIDE_PANEL_INLINE_MIN_WIDTH = 1024;

export function RoomPage() {
  const navigate = useNavigate();
  const params = useParams();
  const roomId = params.roomId ?? "";
  const { getSession, saveSession, clearSession } = useSessionStore();
  const [roomSnapshot, setRoomSnapshot] = useState<RoomSnapshotResponse | null>(null);
  const [loadingSnapshot, setLoadingSnapshot] = useState(true);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [snapshotExpired, setSnapshotExpired] = useState(false);
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);
  const [joinPasswordError, setJoinPasswordError] = useState<string | null>(null);
  const [activePanel, setActivePanel] = useState<RoomPanelTab>("relay");
  const [sidePanelOpen, setSidePanelOpen] = useState(
    () => typeof window === "undefined" || window.innerWidth >= SIDE_PANEL_INLINE_MIN_WIDTH,
  );
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showEndedSummary, setShowEndedSummary] = useState(false);
  const [themeMode, setThemeMode] = useState<AppThemeMode>(() => loadThemePreference());
  const [layoutMode, setLayoutMode] = useState<RoomLayoutMode>(() => loadRoomLayoutPreference());
  const [pinnedStageTarget, setPinnedStageTarget] = useState<PinnedStageTarget | null>(null);
  const session = getSession(roomId);
  const handleSessionInvalidated = useCallback(() => {
    clearSession(roomId);
  }, [clearSession, roomId]);
  const handleRoomExpired = useCallback(() => {
    clearSession(roomId);
    setSnapshotExpired(true);
    setShowEndedSummary(true);
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
    setSnapshotExpired(false);
    setShowEndedSummary(false);

    void (async () => {
      try {
        const response = await api.getRoom(roomId);
        if (!cancelled) {
          setRoomSnapshot(response);
          // Check if room is already expired from snapshot expires_at
          if (response.room.expires_at) {
            const expired = new Date(response.room.expires_at).getTime() <= Date.now();
            if (expired) {
              setSnapshotExpired(true);
              setShowEndedSummary(true);
            }
          }
        }
      } catch (error) {
        if (cancelled) {
          return;
        }

        if (error instanceof ApiError && error.code === "room_expired") {
          setSnapshotExpired(true);
          setShowEndedSummary(true);
        } else {
          setSnapshotError(
            error instanceof ApiError
              ? mapRoomSnapshotError(error)
              : "Could not load room details.",
          );
        }
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
    onRoomExpired: handleRoomExpired,
  });

  const recording = useRoomRecording({
    roomId,
    roomToken: session?.roomToken ?? null,
    gatewayState: meeting.gatewayState,
    subscribe: meeting.subscribeRecordingEvents,
    initial: roomSnapshot?.room.recording ?? null,
    available: roomSnapshot?.room.recording_available ?? false,
  });

  // expiresAt comes from the live meeting state (updated via WS snapshots) or fallback to REST snapshot
  const expiresAt = meeting.expiresAt ?? roomSnapshot?.room.expires_at ?? null;
  const { isExpired: isTimerExpired } = useRoomExpiry(expiresAt);

  // Room is expired if: backend told us (snapshotExpired), timer ran out, or meeting hook says so
  const isRoomExpired = snapshotExpired || isTimerExpired || meeting.isRoomExpired;

  useEffect(() => {
    applyThemePreference(themeMode);
    saveThemePreference(themeMode);
  }, [themeMode]);

  useEffect(() => {
    saveRoomLayoutPreference(layoutMode);
  }, [layoutMode]);

  useEffect(() => {
    if (!roomId || session || (!snapshotExpired && !showEndedSummary)) {
      return;
    }

    void meeting.fetchMeetingSummary("final", {
      suppressNotFound: true,
    });
  }, [roomId, session, snapshotExpired, showEndedSummary]);

  const activeScreenShareParticipants = meeting.participants.filter(
    (participant) => participant.is_screen_sharing,
  );
  const pinnedScreenShareParticipant =
    pinnedStageTarget?.type === "screen"
      ? activeScreenShareParticipants.find(
          (participant) => participant.participant_id === pinnedStageTarget.participantId,
        ) || null
      : null;
  const selectedScreenSharer =
    pinnedScreenShareParticipant ||
    activeScreenShareParticipants.find(
      (participant) => participant.participant_id === meeting.selfState?.participant_id,
    ) || activeScreenShareParticipants[0] || null;
  const selectedScreenFeed = selectedScreenSharer
    ? (
        meeting.screenShares.find(
          (feed) =>
            feed.participantId === selectedScreenSharer.participant_id
            && (
              pinnedStageTarget?.type !== "screen"
              || !pinnedStageTarget.trackSid
              || feed.trackSid === pinnedStageTarget.trackSid
            ),
        )
        || meeting.screenShares.find(
          (feed) => feed.participantId === selectedScreenSharer.participant_id,
        )
        || null
      )
    : null;
  const roomMeetingLanguages = meeting.meetingLanguages;
  const brseModeDescription =
    roomMeetingLanguages.length === 1 && meeting.brseRoomMode === "text_only"
      ? "Transcript/captions"
      : getBrseModeDescription(meeting.brseRoomMode);
  const relayStatusLabel = meeting.brseEnabled
    ? meeting.interpreterStatuses[0]?.status
      ? formatRelayStatus(meeting.interpreterStatuses[0].status)
      : brseModeDescription
    : "Off";
  const renderSummaryPanel = (roomEnded: boolean) => (
    <MeetingSummaryPanel
      summary={meeting.meetingSummary}
      intent={meeting.summaryIntent}
      roomEnded={roomEnded}
      isLoading={meeting.isLoadingSummary}
      isGenerating={meeting.isGeneratingSummary}
      error={meeting.summaryError}
      errorSource={meeting.summaryErrorSource}
      canRefreshInterim={meeting.canRefreshInterimSummary && !isRoomExpired}
      onRefreshInterim={() => {
        void meeting.refreshInterimSummary();
      }}
      onCheckInterim={() => {
        void meeting.fetchMeetingSummary("interim", {
          suppressNotFound: true,
        });
      }}
      onCheckFinal={() => {
        void meeting.fetchMeetingSummary("final", {
          suppressNotFound: true,
        });
      }}
      onPrepareFinal={() => {
        void meeting.prepareFinalSummary();
      }}
      embedded
    />
  );

  useEffect(() => {
    if (!pinnedStageTarget) {
      return;
    }

    if (pinnedStageTarget.type === "participant") {
      const participantStillVisible = meeting.videos.some(
        (feed) => feed.participantId === pinnedStageTarget.participantId,
      );
      if (!participantStillVisible) {
        setPinnedStageTarget(null);
      }
      return;
    }

    const screenShareStillActive = activeScreenShareParticipants.some(
      (participant) => participant.participant_id === pinnedStageTarget.participantId,
    );
    if (!screenShareStillActive) {
      setPinnedStageTarget(null);
    }
  }, [activeScreenShareParticipants, meeting.videos, pinnedStageTarget]);

  const handleThemeChange = useCallback((nextTheme: AppThemeMode) => {
    setThemeMode(nextTheme);
  }, []);

  const handleLayoutChange = useCallback((nextLayout: RoomLayoutMode) => {
    setLayoutMode(nextLayout);
  }, []);

  const handlePinParticipant = useCallback((participantId: string) => {
    setPinnedStageTarget({ type: "participant", participantId });
  }, []);

  const handlePinScreenShare = useCallback((participantId: string, trackSid?: string) => {
    setPinnedStageTarget({ type: "screen", participantId, trackSid });
  }, []);

  const handleUnpinStage = useCallback(() => {
    setPinnedStageTarget(null);
  }, []);

  const handleToggleSidePanel = useCallback(() => {
    setSidePanelOpen((prev) => !prev);
  }, []);

  async function handleJoin(payload: {
    displayName: string;
    language: MeetingLanguage;
    password?: string;
  }) {
    if (!roomId) {
      return;
    }

    if (isRoomExpired) {
      setJoinError("This meeting has expired and is no longer accepting participants.");
      return;
    }

    if (!payload.displayName.trim()) {
      setJoinError("Please enter your display name.");
      return;
    }

    if (roomMeetingLanguages.length === 0) {
      setJoinError(
        "Room languages are unavailable. Reload room snapshot or ask the host to recreate the room.",
      );
      return;
    }

    if (!roomMeetingLanguages.includes(payload.language)) {
      setJoinError(
        `Choose one of the room languages: ${formatRoomLanguageList(roomMeetingLanguages)}.`,
      );
      return;
    }

    setJoining(true);
    setJoinError(null);
    setJoinPasswordError(null);

    try {
      const response = await api.joinRoom(roomId, {
        display_name: payload.displayName,
        language: payload.language,
        client: {
          sdk: "web",
          version: APP_VERSION,
        },
        // Sent only in the request body; never stored or put in the URL.
        ...(payload.password ? { password: payload.password } : {}),
      });
      saveSession(response);
    } catch (error) {
      if (error instanceof ApiError && (error.code === "invalid_room_password" || error.code === "room_password_required")) {
        setJoinPasswordError(
          error.code === "invalid_room_password" ? "Incorrect meeting password." : "Enter the meeting password.",
        );
      } else if (error instanceof ApiError && error.code === "room_expired") {
        setSnapshotExpired(true);
        setJoinError("This meeting has expired.");
      } else {
        setJoinError(
          error instanceof ApiError
            ? mapJoinError(error, roomMeetingLanguages)
            : "Could not join room. Check backend availability.",
        );
      }
    } finally {
      setJoining(false);
    }
  }

  const roomAlerts: Array<{ tone: "danger" | "warning"; message: string }> = [
    isRoomExpired ? { tone: "danger" as const, message: "This meeting has ended. The room time limit has been reached." } : null,
    meeting.isMutedByHost ? { tone: "danger" as const, message: "The host muted your microphone." } : null,
    meeting.connectionError ? { tone: "danger" as const, message: meeting.connectionError } : null,
    meeting.brseToggleError ? { tone: "warning" as const, message: meeting.brseToggleError } : null,
    meeting.relayModeError ? { tone: "warning" as const, message: meeting.relayModeError } : null,
    meeting.mediaError ? { tone: "warning" as const, message: meeting.mediaError } : null,
    meeting.screenShareError ? { tone: "warning" as const, message: meeting.screenShareError } : null,
    meeting.micToggleError ? { tone: "warning" as const, message: meeting.micToggleError } : null,
    meeting.cameraToggleError ? { tone: "warning" as const, message: meeting.cameraToggleError } : null,
    meeting.moderationError ? { tone: "warning" as const, message: meeting.moderationError } : null,
    recording.error ? { tone: "warning" as const, message: recording.error } : null,
    ...recording.notices.map((notice) => ({
      tone: notice.tone === "danger" ? ("danger" as const) : ("warning" as const),
      message: notice.message,
    })),
  ].filter((alert): alert is { tone: "danger" | "warning"; message: string } => alert !== null);

  if (loadingSnapshot && !roomSnapshot && !session) {
    return (
      <main className="room-boot">
        <div className="room-boot-loading" role="status">
          <Spinner size="lg" />
          <p className="text-secondary">Loading room…</p>
        </div>
      </main>
    );
  }

  // Expired room with no session: show the final summary, not a generic error.
  if ((snapshotExpired || showEndedSummary) && !session) {
    return (
      <div className="ended">
        <header className="ended-header">
          <div>
            <h1 className="page-title">Meeting ended</h1>
            <p className="page-description">
              This room is closed. The final summary appears below once it&apos;s ready.
            </p>
          </div>
          <button type="button" className={buttonClassName({ variant: "secondary" })} onClick={() => navigate("/")}>
            Back to home
          </button>
        </header>
        <main className="ended-body card">
          <div className="card-body">{renderSummaryPanel(true)}</div>
        </main>
        <MeetingRecordingSection roomId={roomId} />
      </div>
    );
  }

  if (snapshotError && !roomSnapshot && !session) {
    return (
      <main className="room-boot">
        <EmptyState
          icon={<AlertCircle size={20} />}
          title="Room unavailable"
          description={snapshotError}
          action={<Link to="/" className={buttonClassName({ variant: "secondary" })}>Back to home</Link>}
        />
      </main>
    );
  }

  if (!session) {
    if (!roomSnapshot) {
      return null;
    }

    return (
      <JoinRoomCard
          room={roomSnapshot.room}
          participants={roomSnapshot.participants}
          meetingLanguages={roomMeetingLanguages}
          isExpired={isRoomExpired}
          onJoin={handleJoin}
          isSubmitting={joining}
        error={joinError}
        passwordError={joinPasswordError}
        onPasswordEdited={() => setJoinPasswordError(null)}
      />
    );
  }

  return (
    <div className={[
      "room",
      `room--${layoutMode}`,
      sidePanelOpen ? "is-panel-open" : "",
    ].filter(Boolean).join(" ")}>
      <RoomTopBar
        roomId={roomId}
        meetingLanguages={roomMeetingLanguages}
        currentLanguage={meeting.selfState?.language || session.participant.language}
        participantCount={meeting.participants.length}
        expiresAt={expiresAt}
        connectionState={meeting.connectionState}
        brseEnabled={meeting.brseEnabled}
        brseRoomMode={meeting.brseRoomMode}
        isTogglingBrse={meeting.isTogglingBrse}
        canToggleBrse={meeting.canToggleBrse && !isRoomExpired}
        onChangeLanguage={(language) => meeting.changeLanguage(language)}
        onToggleBrse={(nextEnabled) => {
          void meeting.toggleBrseMode(nextEnabled);
        }}
        relayMode={meeting.relayMode}
        relayModes={meeting.selectableRelayModes}
        isUpdatingRelayMode={meeting.isUpdatingRelayMode}
        canChangeRelayMode={meeting.canChangeRelayMode && !isRoomExpired}
        onChangeRelayMode={(mode) => {
          void meeting.changeRelayMode(mode);
        }}
        recordingIndicator={<RecordingIndicator recording={recording.active} />}
      />

      {roomAlerts.length > 0 ? (
        <div className="room-alerts">
          {roomAlerts.map((alert) => (
            <Alert key={alert.message} tone={alert.tone}>{alert.message}</Alert>
          ))}
        </div>
      ) : null}

      <div className="room-body">
        <main className="room-main">
          <MeetingStage
            sidePanelOpen={sidePanelOpen}
            videos={meeting.videos}
            participants={meeting.participants}
            selectedScreenSharer={selectedScreenSharer}
            selectedScreenFeed={selectedScreenFeed}
            activeScreenShareCount={activeScreenShareParticipants.length}
            brseEnabled={meeting.brseEnabled}
            brseRoomMode={meeting.brseRoomMode}
            brseAudioExpected={meeting.brseAudioExpected}
            relayStatusLabel={relayStatusLabel}
            pinnedTarget={pinnedStageTarget}
            onPinParticipant={handlePinParticipant}
            onPinScreenShare={handlePinScreenShare}
            onUnpinStage={handleUnpinStage}
          />

          <RoomControlBar
            recordControl={
              recording.available ? (
                <RecordButton
                  recording={recording.active}
                  isStarting={recording.isStarting}
                  isStopping={recording.isStopping}
                  disabled={isRoomExpired || meeting.isLeaving}
                  onStart={() => void recording.start()}
                  onStop={() => void recording.stop()}
                />
              ) : null
            }
            isMicMuted={meeting.isMicMuted}
            isTogglingMic={meeting.isTogglingMic}
            isMutedByHost={meeting.isMutedByHost}
            isCameraOff={meeting.isCameraOff}
            isTogglingCamera={meeting.isTogglingCamera}
            isScreenSharing={meeting.isScreenSharing}
            isStartingScreenShare={meeting.isStartingScreenShare}
            isStoppingScreenShare={meeting.isStoppingScreenShare}
            isLeaving={meeting.isLeaving}
            onToggleMic={() => {
              void meeting.toggleMicrophoneMuted();
            }}
            onToggleCamera={() => {
              void meeting.toggleCameraEnabled();
            }}
            onToggleScreenShare={() => {
              if (isRoomExpired) return;
              if (meeting.isScreenSharing) {
                void meeting.stopScreenShare({ reason: "manual_stop" });
                return;
              }
              void meeting.startScreenShare();
            }}
            sidePanelOpen={sidePanelOpen}
            onToggleSidePanel={handleToggleSidePanel}
            onOpenSettings={() => {
              setSettingsOpen(true);
            }}
            onLeave={() => {
              const shouldShowFinalSummary =
                meeting.participants.filter(isHumanParticipant).length <= 1;
              void meeting.leaveRoom().then(() => {
                if (shouldShowFinalSummary) {
                  setShowEndedSummary(true);
                  void meeting.fetchMeetingSummary("final", {
                    suppressNotFound: true,
                  });
                  return;
                }

                navigate("/");
              });
            }}
          />
        </main>

        <RoomSidePanel
          open={sidePanelOpen}
          onClose={() => setSidePanelOpen(false)}
          activeTab={activePanel}
          transcriptCount={meeting.transcripts.length}
          chatCount={meeting.chatMessages.length}
          summaryCount={meeting.meetingSummary ? 1 : 0}
          participantCount={meeting.participants.length}
          onTabChange={setActivePanel}
          relay={
            <BrseRelayPanel
              brseEnabled={meeting.brseEnabled}
              brseRoomMode={meeting.brseRoomMode}
              brseAudioExpected={meeting.brseAudioExpected}
              statuses={meeting.interpreterStatuses}
              transcripts={meeting.transcripts}
              meetingLanguages={roomMeetingLanguages}
            />
          }
          chat={
            <ChatPanel
              messages={meeting.chatMessages}
              selfParticipantId={meeting.selfState?.participant_id}
              onSend={meeting.sendChatMessage}
              disabled={!meeting.canSendChat || isRoomExpired}
              error={meeting.chatError}
              isSending={meeting.isSendingChat}
              meetingLanguages={roomMeetingLanguages}
              embedded
            />
          }
          summary={renderSummaryPanel(isRoomExpired)}
          people={
            <ParticipantList
              participants={meeting.participants}
              selfParticipantId={meeting.selfState?.participant_id}
              isCurrentUserHost={meeting.isCurrentUserHost}
              onMuteParticipant={(participantId) => {
                void meeting.muteParticipant(participantId);
              }}
              isMutingParticipant={meeting.isMutingParticipant}
              brseEnabled={meeting.brseEnabled}
              brseRoomMode={meeting.brseRoomMode}
              brseAudioExpected={meeting.brseAudioExpected}
              embedded
            />
          }
        />
      </div>

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        title="Settings"
      >
        <AiRelaySettingsPanel
          brseEnabled={meeting.brseEnabled}
          brseRoomMode={meeting.brseRoomMode}
          languageCount={roomMeetingLanguages.length}
          isTogglingBrse={meeting.isTogglingBrse}
          canToggleBrse={meeting.canToggleBrse && !isRoomExpired}
          onToggleBrse={(nextEnabled) => {
            void meeting.toggleBrseMode(nextEnabled);
          }}
          relayMode={meeting.relayMode}
          relayModes={meeting.selectableRelayModes}
          isUpdatingRelayMode={meeting.isUpdatingRelayMode}
          canChangeRelayMode={meeting.canChangeRelayMode && !isRoomExpired}
          onChangeRelayMode={(mode) => {
            void meeting.changeRelayMode(mode);
          }}
          relayModeError={meeting.relayModeError}
        />
        <AudioDevicePanel
          isMicMuted={meeting.isMicMuted}
          isTogglingMic={meeting.isTogglingMic}
          micToggleError={meeting.micToggleError}
          isMutedByHost={meeting.isMutedByHost}
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
          embedded
        />
        <MeetingViewPanel
          themeMode={themeMode}
          layoutMode={layoutMode}
          onThemeChange={handleThemeChange}
          onLayoutChange={handleLayoutChange}
        />
      </SettingsDrawer>

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
    </div>
  );
}

function formatRelayStatus(status?: string): string {
  if (!status) {
    return "Idle";
  }

  return status
    .split("_")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

function mapRoomSnapshotError(error: ApiError): string {
  if (error.code === "room_not_found") {
    return "Room not found.";
  }
  if (error.code === "room_expired") {
    return "This meeting has expired.";
  }
  return error.message;
}

function mapJoinError(error: ApiError, meetingLanguages: MeetingLanguage[]): string {
  if (error.code === "room_full") {
    return "Room is full.";
  }
  if (error.code === "room_not_found") {
    return "Room not found.";
  }
  if (error.code === "room_expired") {
    return "This meeting has expired and is no longer accepting participants.";
  }
  if (error.code === "livekit_unavailable") {
    return "LiveKit is unavailable right now.";
  }
  if (error.code === "room_password_rate_limited") {
    return "Too many incorrect password attempts. Please wait a few minutes and try again.";
  }
  if (error.code === "invalid_display_name") {
    return "Display name must be 1 to 40 characters.";
  }
  if (error.code === "invalid_language") {
    return meetingLanguages.length > 0
      ? `Your language must match the room languages: ${formatRoomLanguageList(meetingLanguages)}.`
      : "Your language must match one of the room languages.";
  }
  return error.message;
}

function isHumanParticipant(participant: ParticipantSnapshot): boolean {
  return participant.kind !== "virtual_brse" && !participant.is_virtual;
}
