import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import {
  formatMeetingLanguagePair,
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
import { ParticipantList } from "../components/ParticipantList";
import { BrseRelayPanel } from "../components/BrseRelayPanel";
import { MeetingSummaryPanel } from "../components/MeetingSummaryPanel";
import { MeetingStage, type PinnedStageTarget } from "../components/MeetingStage";
import { MeetingViewPanel } from "../components/MeetingViewPanel";
import { RoomControlBar } from "../components/RoomControlBar";
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

const APP_VERSION = "0.1.0";

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
  const [activePanel, setActivePanel] = useState<RoomPanelTab>("relay");
  const [sidePanelOpen, setSidePanelOpen] = useState(true);
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
  const brseModeDescription = getBrseModeDescription(meeting.brseRoomMode);
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

    if (roomMeetingLanguages.length !== 2) {
      setJoinError(
        "Room meeting language pair is unavailable. Reload room snapshot or ask the host to recreate the room.",
      );
      return;
    }

    if (!roomMeetingLanguages.includes(payload.language)) {
      setJoinError(
        `Choose one of the room meeting languages: ${formatMeetingLanguagePair(roomMeetingLanguages)}.`,
      );
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
      if (error instanceof ApiError && error.code === "room_expired") {
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

  if (loadingSnapshot && !roomSnapshot && !session) {
    return (
      <main className="room-boot">
        <div className="empty-state room-boot-loading">
          <span className="loading-spinner loading-spinner-lg" aria-hidden="true" />
          <strong>Loading room</strong>
          <p>Fetching room snapshot from the gateway.</p>
        </div>
      </main>
    );
  }

  // Expired room with no session: show dedicated expired page (not generic error)
  if ((snapshotExpired || showEndedSummary) && !session) {
    return (
      <main className="room-boot">
        <div className="room-ended-summary-page">
          <div className="room-ended-copy">
            <span className="room-ended-kicker">Meeting ended</span>
            <h1>Final summary</h1>
            <p>
              This room is closed. The final summary stays available here when the backend
              finishes preparing it.
            </p>
            <button type="button" className="button-secondary" onClick={() => navigate("/")}>
              Back Home
            </button>
          </div>
          <div className="room-ended-summary-card">
            {renderSummaryPanel(true)}
          </div>
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
          <button type="button" className="button-secondary" onClick={() => navigate("/")}>
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
          meetingLanguages={roomMeetingLanguages}
          isExpired={isRoomExpired}
          onJoin={handleJoin}
          isSubmitting={joining}
          error={joinError}
        />
      </main>
    );
  }

  return (
    <main className={[
      "room-page",
      `theme-${themeMode}`,
      `layout-${layoutMode}`,
      meeting.brseEnabled ? "brse-on" : "brse-off",
      sidePanelOpen ? "panel-open" : "panel-closed",
    ].join(" ")}>
      <RoomTopBar
        roomId={roomId}
        displayName={meeting.selfState?.display_name || session.participant.display_name}
        meetingLanguages={roomMeetingLanguages}
        currentLanguage={meeting.selfState?.language || session.participant.language}
        participantCount={meeting.participants.length}
        expiresAt={expiresAt}
        connectionState={meeting.connectionState}
        brseEnabled={meeting.brseEnabled}
        brseRoomMode={meeting.brseRoomMode}
        isTogglingBrse={meeting.isTogglingBrse}
        brseToggleError={meeting.brseToggleError}
        canToggleBrse={meeting.canToggleBrse && !isRoomExpired}
        onChangeLanguage={(language) => meeting.changeLanguage(language)}
        onToggleBrse={(nextEnabled) => {
          void meeting.toggleBrseMode(nextEnabled);
        }}
      />

      <div className="room-alert-stack">
        {isRoomExpired ? (
          <div className="banner banner-danger banner-room-expired">
            This meeting has ended. The room time limit has been reached.
          </div>
        ) : null}
        {meeting.connectionError ? (
          <div className="banner banner-danger">{meeting.connectionError}</div>
        ) : null}
        {meeting.mediaError ? (
          <div className="banner banner-warning">{meeting.mediaError}</div>
        ) : null}
        {meeting.screenShareError ? (
          <div className="banner banner-warning">{meeting.screenShareError}</div>
        ) : null}
        {meeting.micToggleError ? (
          <div className="banner banner-warning">{meeting.micToggleError}</div>
        ) : null}
        {meeting.cameraToggleError ? (
          <div className="banner banner-warning">{meeting.cameraToggleError}</div>
        ) : null}
        {meeting.moderationError ? (
          <div className="banner banner-warning">{meeting.moderationError}</div>
        ) : null}
        {meeting.isMutedByHost ? (
          <div className="banner banner-danger banner-force-muted">
            Your microphone has been muted by the host.
          </div>
        ) : null}
      </div>

      <div className="room-shell">
        <section className="room-main-column" aria-label="Meeting stage and controls">
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
        </section>

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
        title="Room settings"
      >
        <MeetingViewPanel
          themeMode={themeMode}
          layoutMode={layoutMode}
          onThemeChange={handleThemeChange}
          onLayoutChange={handleLayoutChange}
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
    </main>
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
  if (error.code === "invalid_display_name") {
    return "Display name must be 1 to 40 characters.";
  }
  if (error.code === "invalid_language") {
    return meetingLanguages.length === 2
      ? `Your language must match the room meeting languages: ${formatMeetingLanguagePair(meetingLanguages)}.`
      : "Your language must match one of the room meeting languages.";
  }
  return error.message;
}

function isHumanParticipant(participant: ParticipantSnapshot): boolean {
  return participant.kind !== "virtual_brse" && !participant.is_virtual;
}
