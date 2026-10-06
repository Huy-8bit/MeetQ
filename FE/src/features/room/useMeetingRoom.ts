import { startTransition, useCallback, useEffect, useRef, useState } from "react";
import { api, leaveRoomBestEffort, ApiError } from "../../lib/api";
import { setRoomAudioOutputDevice } from "../../lib/audioOutput";
import {
  formatRoomLanguageList,
  normalizeRoomLanguages,
} from "../../lib/languages";
import {
  bindRoomRefresh,
  buildMediaSnapshot,
  connectLiveKit,
  createMeetingRoom,
  disconnectRoom,
  enumerateAudioDevices,
  getLocalCameraTrack,
  getLocalMicrophoneTrack,
  isCameraMuted,
  isMicrophoneMuted,
  isScreenShareSupported,
  publishLocalCameraTrack,
  publishScreenShareTrack,
  publishLocalMedia,
  ScreenShareCancelledError,
  ScreenShareUnsupportedError,
  setLocalCameraMuted,
  setLocalMicrophoneMuted,
  supportsAudioOutputSelection,
  switchLocalMicrophoneTrack,
  unpublishScreenShareTrack,
  type PublishedScreenShare,
  type ScreenShareQuality,
} from "../../lib/livekit";
import {
  applyRelayModeToRoom,
  getSelectableRelayModes,
  isBrseAudioExpected,
  isBrseAudioPossible,
  relayModeErrorMessage,
  resolveBrseEnabled,
  resolveBrseOutputMode,
  resolveBrseRoomMode,
  type RelayModeState,
} from "../../lib/brseModes";
import {
  GatewaySocket,
  GatewaySocketCancelledError,
  releaseGatewaySocket,
  retainGatewaySocket,
} from "../../lib/ws";
import type {
  BrseOutputMode,
  ChatMessage,
  ChatTranslation,
  ChatTranslationMode,
  RoomChatMessage,
  Language,
  MeetingLanguage,
  MeetingSummaryActionItem,
  MeetingSummaryParticipantItem,
  MeetingSummaryResponse,
  MeetingSummaryStatus,
  MeetingSummaryType,
  ParticipantSnapshot,
  RoomRole,
  RoomSnapshotResponse,
  ScreenShareTrackInfo,
} from "../../types/api";
import { normalizeRole, permissionsFor, PERMISSION_DENIED_MESSAGE } from "../../lib/roomRoles";
import type {
  AudioDeviceOption,
  BrseAudioFeed,
  GatewayConnectionState,
  HumanAudioFeed,
  ScreenShareFeed,
  VideoFeed,
} from "../../types/livekit";
import type {
  ChatMessageEvent,
  ErrorEvent,
  ModerationForceMutedEvent,
  ModerationParticipantMutedEvent,
  ParticipantJoinedEvent,
  ParticipantLeftEvent,
  ParticipantRemovedEvent,
  ParticipantRoleChangedEvent,
  ParticipantUpdatedEvent,
  RoomAccessUpdatedEvent,
  RoomLockChangedEvent,
  RoomBrseUpdatedEvent,
  RoomExpiredEvent,
  RoomRelayModeUpdatedEvent,
  RoomHostChangedEvent,
  RoomSnapshotEvent,
  ScreenShareStartedEvent,
  ScreenShareStoppedEvent,
  ServerEvent,
  TranscriptFinalEvent,
  TranscriptPartialEvent,
} from "../../types/ws";
import type { RoomSession } from "../../state/session";
import type { RecordingEvent } from "../../types/ws";
import { type LocalAudioTrack, type LocalTrack, type LocalVideoTrack } from "livekit-client";
import {
  hydrateTranscriptEntries,
  mergeTranscriptCollections,
  upsertTranscriptEntry,
  type TranscriptEntry,
} from "./transcripts";
import {
  upsertInterpreterStatus,
  type InterpreterStatusEntry,
} from "./interpreter";

const FINAL_SUMMARY_POLL_INTERVAL_MS = 3000;
const FINAL_SUMMARY_MAX_POLLS = 8;

export interface StartScreenShareOptions {
  quality: ScreenShareQuality;
  includeAudio: boolean;
}

interface UseMeetingRoomArgs {
  roomId: string;
  initialRoom: RoomSnapshotResponse | null;
  session: RoomSession | null;
  onSessionInvalidated: () => void;
  onRoomExpired?: (details: RoomExpiredDetails) => void;
}

interface SelfState {
  participant_id: string;
  session_id: string;
  display_name: string;
  language: Language;
}

type RoomExpiredSource =
  | "local_timer"
  | "initial_state"
  | "snapshot"
  | "gateway_event"
  | "gateway_error"
  | "gateway_close";
type SummaryErrorSource = "fetch" | "generate";

export interface RoomExpiredDetails {
  source: RoomExpiredSource;
  expiredAt?: string | null;
  message?: string;
}

export function useMeetingRoom({
  roomId,
  initialRoom,
  session,
  onSessionInvalidated,
  onRoomExpired,
}: UseMeetingRoomArgs) {
  const [roomMeta, setRoomMeta] = useState<RoomSnapshotResponse["room"] | null>(
    initialRoom?.room ?? null,
  );
  const [participantsById, setParticipantsById] = useState<
    Record<string, ParticipantSnapshot>
  >(() => mapParticipants(initialRoom?.participants ?? session?.snapshot.participants ?? []));
  const [selfState, setSelfState] = useState<SelfState | null>(
    session
      ? {
          participant_id: session.participant.participant_id,
          session_id: session.participant.session_id,
          display_name: session.participant.display_name,
          language: session.participant.language,
        }
      : null,
  );
  const [transcripts, setTranscripts] = useState<TranscriptEntry[]>(() =>
    hydrateTranscriptEntries(
      session?.snapshot.recent_transcripts ??
        initialRoom?.recent_transcripts ??
        [],
      session?.participant.language ?? null,
    ).filter((entry) => resolveBrseEnabled(initialRoom?.room ?? session?.room ?? null) || entry.kind !== "relay"),
  );
  const [interpreterStatuses, setInterpreterStatuses] = useState<
    InterpreterStatusEntry[]
  >([]);
  const [gatewayState, setGatewayState] =
    useState<GatewayConnectionState>("idle");
  const [livekitState, setLivekitState] =
    useState<GatewayConnectionState>("idle");
  const [videos, setVideos] = useState<VideoFeed[]>([]);
  const [humanAudioFeeds, setHumanAudioFeeds] = useState<HumanAudioFeed[]>([]);
  const [brseAudioFeeds, setBrseAudioFeeds] = useState<BrseAudioFeed[]>([]);
  const [screenShares, setScreenShares] = useState<ScreenShareFeed[]>([]);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [screenShareError, setScreenShareError] = useState<string | null>(null);
  const [isScreenSharing, setIsScreenSharing] = useState(false);
  const [isStartingScreenShare, setIsStartingScreenShare] = useState(false);
  const [isStoppingScreenShare, setIsStoppingScreenShare] = useState(false);
  // Non-error info about the running share (no shared audio, lower frame rate than asked).
  const [screenShareNotice, setScreenShareNotice] = useState<string | null>(null);
  const [canShareScreen] = useState(isScreenShareSupported);
  const [isMicMuted, setIsMicMuted] = useState(false);
  const [isTogglingMic, setIsTogglingMic] = useState(false);
  const [micToggleError, setMicToggleError] = useState<string | null>(null);
  const [isCameraOff, setIsCameraOff] = useState(true);
  const [isTogglingCamera, setIsTogglingCamera] = useState(false);
  const [cameraToggleError, setCameraToggleError] = useState<string | null>(null);
  const [audioInputDevices, setAudioInputDevices] = useState<AudioDeviceOption[]>([]);
  const [selectedAudioInputDeviceId, setSelectedAudioInputDeviceId] = useState("");
  const [isSwitchingAudioInput, setIsSwitchingAudioInput] = useState(false);
  const [audioInputError, setAudioInputError] = useState<string | null>(null);
  const [audioOutputDevices, setAudioOutputDevices] = useState<AudioDeviceOption[]>([]);
  const [selectedAudioOutputDeviceId, setSelectedAudioOutputDeviceId] = useState("default");
  const [isSwitchingAudioOutput, setIsSwitchingAudioOutput] = useState(false);
  const [audioOutputSupported, setAudioOutputSupported] = useState(false);
  const [audioOutputError, setAudioOutputError] = useState<string | null>(null);
  const [isLeaving, setIsLeaving] = useState(false);
  const [isTogglingBrse, setIsTogglingBrse] = useState(false);
  const [brseToggleError, setBrseToggleError] = useState<string | null>(null);
  // AI relay mode (Voice + Text / Text Only) is room state owned by the server.
  // No optimistic update: the selector shows "Updating…" until the server answers.
  const [isUpdatingRelayMode, setIsUpdatingRelayMode] = useState(false);
  const [relayModeError, setRelayModeError] = useState<string | null>(null);
  // Bumped on every room.relay_mode_updated event so a slower REST response can't
  // overwrite a newer change made by another participant.
  const relayModeEventSeqRef = useRef(0);
  // useRoomRecording subscribes here; recording state is not kept in this hook.
  const recordingListenersRef = useRef(new Set<(event: RecordingEvent) => void>());
  const subscribeRecordingEvents = useCallback((listener: (event: RecordingEvent) => void) => {
    recordingListenersRef.current.add(listener);
    return () => {
      recordingListenersRef.current.delete(listener);
    };
  }, []);

  // ─── Chat state ──────────────────────────────────────────────────────────────
  const [chatMessages, setChatMessages] = useState<RoomChatMessage[]>(() =>
    normalizeChatMessages(session?.snapshot.recent_messages ?? initialRoom?.recent_messages ?? []),
  );
  const [chatError, setChatError] = useState<string | null>(null);
  const [isSendingChat, setIsSendingChat] = useState(false);

  // ─── Meeting summary state ────────────────────────────────────────────────
  const [meetingSummary, setMeetingSummary] = useState<MeetingSummaryResponse | null>(null);
  const [summaryIntent, setSummaryIntent] = useState<MeetingSummaryType>("interim");
  const [isLoadingSummary, setIsLoadingSummary] = useState(false);
  const [isGeneratingSummary, setIsGeneratingSummary] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryErrorSource, setSummaryErrorSource] = useState<SummaryErrorSource | null>(null);

  // ─── Host state ─────────────────────────────────────────────────────────────
  const [hostParticipantId, setHostParticipantId] = useState<string | null>(() => {
    const snapshotHost = (initialRoom?.room as { host_participant_id?: string | null })?.host_participant_id ?? null;
    if (snapshotHost) return snapshotHost;
    const hostFromParticipants = (initialRoom?.participants ?? session?.snapshot.participants ?? []).find(
      (p) => p.is_host,
    );
    return hostFromParticipants?.participant_id ?? null;
  });

  // ─── Moderation state ───────────────────────────────────────────────────────
  const [isMutedByHost, setIsMutedByHost] = useState(false);
  const [isMutingParticipant, setIsMutingParticipant] = useState<string | null>(null);
  const [moderationError, setModerationError] = useState<string | null>(null);

  // ─── Role & room management ─────────────────────────────────────────────────
  // The role comes from the server (join response, snapshot, role events); it only
  // decides what to render. Every action is authorized again on the server.
  const [selfRole, setSelfRole] = useState<RoomRole>(() => normalizeRole(session?.participant.role));
  const [permissionsEnforced, setPermissionsEnforced] = useState(true);
  const [roleNotice, setRoleNotice] = useState<string | null>(null);
  const [pendingManagementAction, setPendingManagementAction] = useState<string | null>(null);
  const [removedFromMeeting, setRemovedFromMeeting] = useState<{ by: string | null } | null>(null);

  // ─── Room expiry state ──────────────────────────────────────────────────────
  const [isRoomExpired, setIsRoomExpired] = useState(false);

  const gatewayRef = useRef<GatewaySocket | null>(null);
  const livekitRoomRef = useRef<ReturnType<typeof createMeetingRoom> | null>(
    null,
  );
  const participantsRef = useRef(participantsById);
  const selfRef = useRef(selfState);
  const pendingLanguageRef = useRef<{
    previous: Language;
    requested: Language;
  } | null>(null);
  const hasLeftRef = useRef(false);
  const hasSentLeaveRef = useRef(false);
  const manualShutdownRef = useRef(false);
  const expiredShutdownRef = useRef(false);
  const sessionInvalidatedRef = useRef(onSessionInvalidated);
  const roomExpiredCallbackRef = useRef(onRoomExpired);
  const refreshMediaRef = useRef<(() => void) | null>(null);
  const audioRoutingRef = useRef(session?.room.audio_routing ?? roomMeta?.audio_routing);
  const roomMetaRef = useRef(roomMeta);
  const localAudioTrackRef = useRef<LocalTrack | null>(null);
  const localVideoTrackRef = useRef<LocalVideoTrack | null>(null);
  const localScreenTrackRef = useRef<LocalVideoTrack | null>(null);
  const localScreenAudioTrackRef = useRef<LocalAudioTrack | null>(null);
  const localScreenTrackCleanupRef = useRef<(() => void) | null>(null);
  const stoppingScreenShareRef = useRef(false);
  const isScreenSharingRef = useRef(false);
  const selectedAudioInputDeviceIdRef = useRef(selectedAudioInputDeviceId);
  const selectedAudioOutputDeviceIdRef = useRef(selectedAudioOutputDeviceId);
  const isSwitchingAudioInputRef = useRef(isSwitchingAudioInput);
  const isMutedByHostRef = useRef(false);
  const removedFromMeetingRef = useRef(false);
  const pendingChatEventIdsRef = useRef<Set<string>>(new Set());
  const brseEnabledRef = useRef(resolveBrseEnabled(initialRoom?.room ?? session?.room ?? null));
  const meetingSummaryRef = useRef<MeetingSummaryResponse | null>(null);
  const summaryRequestSeqRef = useRef(0);
  const finalSummaryPollTimerRef = useRef<number | null>(null);
  const finalSummaryPollCountRef = useRef(0);
  const sessionKey = session?.sessionKey ?? null;
  const livekitUrl = session?.livekit.url ?? null;
  const livekitToken = session?.livekit.token ?? null;

  useEffect(() => {
    sessionInvalidatedRef.current = onSessionInvalidated;
  }, [onSessionInvalidated]);

  useEffect(() => {
    roomExpiredCallbackRef.current = onRoomExpired;
  }, [onRoomExpired]);

  useEffect(() => {
    participantsRef.current = participantsById;
  }, [participantsById]);

  useEffect(() => {
    selfRef.current = selfState;
  }, [selfState]);

  useEffect(() => {
    audioRoutingRef.current = roomMeta?.audio_routing ?? session?.room.audio_routing;
  }, [roomMeta?.audio_routing, session?.room.audio_routing]);

  useEffect(() => {
    roomMetaRef.current = roomMeta;
    brseEnabledRef.current = resolveBrseEnabled(roomMeta ?? session?.room ?? null);
  }, [roomMeta, session?.room]);

  useEffect(() => {
    isScreenSharingRef.current = isScreenSharing;
  }, [isScreenSharing]);

  useEffect(() => {
    selectedAudioInputDeviceIdRef.current = selectedAudioInputDeviceId;
  }, [selectedAudioInputDeviceId]);

  useEffect(() => {
    selectedAudioOutputDeviceIdRef.current = selectedAudioOutputDeviceId;
  }, [selectedAudioOutputDeviceId]);

  useEffect(() => {
    isSwitchingAudioInputRef.current = isSwitchingAudioInput;
  }, [isSwitchingAudioInput]);

  useEffect(() => {
    isMutedByHostRef.current = isMutedByHost;
  }, [isMutedByHost]);

  useEffect(() => {
    meetingSummaryRef.current = meetingSummary;
  }, [meetingSummary]);

  useEffect(() => {
    clearFinalSummaryPollTimer();
    summaryRequestSeqRef.current += 1;
    finalSummaryPollCountRef.current = 0;
    setMeetingSummary(null);
    setSummaryIntent("interim");
    setIsLoadingSummary(false);
    setIsGeneratingSummary(false);
    setSummaryError(null);
    setSummaryErrorSource(null);

    return () => {
      clearFinalSummaryPollTimer();
    };
  }, [roomId]);

  useEffect(() => {
    if (!session || isRoomExpired) {
      return;
    }

    void fetchMeetingSummary("interim", {
      silent: true,
      suppressNotFound: true,
    });
  }, [roomId, sessionKey, isRoomExpired]);

  useEffect(() => {
    if (!initialRoom || session) {
      return;
    }

    setRoomMeta(initialRoom.room);
    setParticipantsById(mapParticipants(initialRoom.participants));
    setChatMessages(normalizeChatMessages(initialRoom.recent_messages ?? []));
    setChatError(null);
    setIsSendingChat(false);
    startTransition(() => {
      setTranscripts(
        hydrateTranscriptEntries(initialRoom.recent_transcripts, null).filter(
          (entry) => resolveBrseEnabled(initialRoom.room) || entry.kind !== "relay",
        ),
      );
    });
  }, [initialRoom, session]);

  useEffect(() => {
    if (!session) {
      hasSentLeaveRef.current = false;
      manualShutdownRef.current = false;
      expiredShutdownRef.current = false;
      localAudioTrackRef.current = null;
      localVideoTrackRef.current = null;
      setSelfState(null);
      setGatewayState("idle");
      setLivekitState("idle");
      setVideos([]);
      setHumanAudioFeeds([]);
      setBrseAudioFeeds([]);
      setScreenShares([]);
      setInterpreterStatuses([]);
      setConnectionError(null);
      setMediaError(null);
      setScreenShareError(null);
      setScreenShareNotice(null);
      setIsScreenSharing(false);
      setIsStartingScreenShare(false);
      setIsStoppingScreenShare(false);
      setIsMicMuted(false);
      setIsTogglingMic(false);
      setMicToggleError(null);
      setIsCameraOff(true);
      setIsTogglingCamera(false);
      setCameraToggleError(null);
      setAudioInputDevices([]);
      setSelectedAudioInputDeviceId("");
      setIsSwitchingAudioInput(false);
      setAudioInputError(null);
      setAudioOutputDevices([]);
      setSelectedAudioOutputDeviceId("default");
      setIsSwitchingAudioOutput(false);
      setAudioOutputSupported(false);
      setAudioOutputError(null);
      setIsLeaving(false);
      setIsTogglingBrse(false);
      setBrseToggleError(null);
      setChatMessages([]);
      setChatError(null);
      setIsSendingChat(false);
      pendingChatEventIdsRef.current.clear();
      setHostParticipantId(null);
      setIsMutedByHost(false);
      setIsMutingParticipant(null);
      setModerationError(null);
      setIsRoomExpired(false);
      void setRoomAudioOutputDevice("").catch(() => undefined);
      refreshMediaRef.current = null;
      return;
    }

    hasLeftRef.current = false;
    hasSentLeaveRef.current = false;
    manualShutdownRef.current = false;
    expiredShutdownRef.current = false;
    setSelfRole(normalizeRole(session.participant.role));
    setRoleNotice(null);
    setRemovedFromMeeting(null);
    removedFromMeetingRef.current = false;
    setConnectionError(null);
    setMediaError(null);
    setCameraToggleError(null);
    setBrseToggleError(null);
    setIsTogglingBrse(false);
    setChatError(null);
    setIsSendingChat(false);
    pendingChatEventIdsRef.current.clear();
    setAudioOutputSupported(supportsAudioOutputSelection());
    setGatewayState("connecting");
    setLivekitState("connecting");

    const initialExpiresAt =
      initialRoom?.room.room_id === session.roomId ? initialRoom.room.expires_at : null;
    const sessionExpiresAt = initialExpiresAt ?? session.room.expires_at;
    if (isExpiredAt(sessionExpiresAt)) {
      shutdownExpiredRoomSession({
        source: "initial_state",
        expiredAt: sessionExpiresAt,
      });
      return;
    }

    const sessionRoomLanguages = normalizeRoomLanguages(session.room);
    setRoomMeta((current) => ({
      room_id: current?.room_id || session.roomId,
      state: session.room.state,
      created_at: current?.created_at || session.room.created_at,
      expires_at: current?.expires_at || session.room.expires_at,
      brse_enabled: session.room.brse_enabled ?? current?.brse_enabled,
      brse_mode: session.room.brse_mode ?? current?.brse_mode,
      brse_output_mode:
        session.room.brse_output_mode ?? current?.brse_output_mode,
      participant_limit: session.room.participant_limit,
      supported_languages: session.room.supported_languages,
      room_languages: sessionRoomLanguages,
      meeting_languages: session.room.meeting_languages ?? sessionRoomLanguages,
      language_a: session.room.language_a ?? sessionRoomLanguages[0],
      language_b: session.room.language_b ?? sessionRoomLanguages[1],
      meeting_mode: session.room.meeting_mode ?? current?.meeting_mode,
      interpreter_mode: session.room.interpreter_mode ?? current?.interpreter_mode,
      audio_routing: session.room.audio_routing ?? current?.audio_routing,
      participant_count: countHumanParticipants(session.snapshot.participants),
    }));
    setSelfState({
      participant_id: session.participant.participant_id,
      session_id: session.participant.session_id,
      display_name: session.participant.display_name,
      language: session.participant.language,
    });
    setParticipantsById(mapParticipants(session.snapshot.participants));
    setChatMessages(
      normalizeChatMessages(session.snapshot.recent_messages ?? initialRoom?.recent_messages ?? []),
    );
    startTransition(() => {
      setTranscripts(
        hydrateTranscriptEntries(
          session.snapshot.recent_transcripts,
          session.participant.language,
        ).filter((entry) => resolveBrseEnabled(session.room) || entry.kind !== "relay"),
      );
    });

    let disposed = false;
    const refreshMedia = () => {
      if (disposed) {
        return;
      }

      const livekitRoom = livekitRoomRef.current;
      const currentSelf = selfRef.current;
      if (!livekitRoom || !currentSelf) {
        return;
      }

      const media = buildMediaSnapshot({
        room: livekitRoom,
        selfParticipantId: currentSelf.participant_id,
        selfDisplayName: currentSelf.display_name,
        participantsById: participantsRef.current,
        audioRouting: audioRoutingRef.current ?? session.room.audio_routing,
      });

      setVideos(media.videos);
      setHumanAudioFeeds(media.humanAudio);
      setBrseAudioFeeds(
        isBrseAudioPossible(roomMetaRef.current ?? session.room)
          ? media.brseAudio
          : [],
      );
      setScreenShares(media.screenShares);
      const currentMicTrack = getLocalMicrophoneTrack(livekitRoom);
      const currentCameraTrack = getLocalCameraTrack(livekitRoom);
      localAudioTrackRef.current = currentMicTrack;
      localVideoTrackRef.current = currentCameraTrack;
      setIsMicMuted(isMicrophoneMuted(currentMicTrack));
      setIsCameraOff(isCameraMuted(currentCameraTrack));
    };
    refreshMediaRef.current = refreshMedia;

    const gateway = retainGatewaySocket({
      roomId,
      sessionKey: session.sessionKey,
      websocketUrl: session.websocketUrl,
    });
    gatewayRef.current = gateway;
    const unsubscribeGateway = gateway.subscribe({
      onEvent: (event) => {
        if (disposed) {
          return;
        }

        if (manualShutdownRef.current || expiredShutdownRef.current) {
          return;
        }

        handleGatewayEvent(event);
      },
      onStateChange: (state) => {
        if (!disposed && !expiredShutdownRef.current) {
          setGatewayState(state);
        }
      },
      onFatalClose: (code, reason) => {
        if (disposed || manualShutdownRef.current) {
          return;
        }

        if (code === 4409) {
          handleRemovedFromMeeting(null);
          return;
        }

        if (code === 4410) {
          const currentRoomMeta = roomMetaRef.current;
          shutdownExpiredRoomSession({
            source: "gateway_close",
            expiredAt:
              currentRoomMeta?.room_id === session.roomId
                ? currentRoomMeta.expires_at
                : session.room.expires_at,
            message: reason || "This meeting has ended.",
          });
          return;
        }

        setConnectionError(
          formatFatalCloseMessage(code, reason || "Gateway session is no longer valid."),
        );
        sessionInvalidatedRef.current();
      },
    });

    const livekitRoom = createMeetingRoom();
    livekitRoomRef.current = livekitRoom;
    const unbindRoom = bindRoomRefresh(livekitRoom, refreshMedia, (state) => {
      if (!disposed && !expiredShutdownRef.current) {
        setLivekitState(state);
      }
    });
    void (async () => {
      try {
        await gateway.connect();
        if (disposed || manualShutdownRef.current || expiredShutdownRef.current) {
          return;
        }

        await connectLiveKit(livekitRoom, session.livekit.url, session.livekit.token);
        if (disposed || manualShutdownRef.current || expiredShutdownRef.current) {
          return;
        }

        refreshMedia();

        try {
          const localTracks = await publishLocalMedia(livekitRoom);
          if (disposed || manualShutdownRef.current || expiredShutdownRef.current) {
            localTracks.forEach((track) => track.stop());
            disconnectRoom(livekitRoom);
            return;
          }

          localAudioTrackRef.current = getLocalMicrophoneTrack(livekitRoom);
          localVideoTrackRef.current = getLocalCameraTrack(livekitRoom);
          setIsMicMuted(isMicrophoneMuted(localAudioTrackRef.current));
          setIsCameraOff(isCameraMuted(localVideoTrackRef.current));
          await refreshAudioDevices();
          if (disposed || manualShutdownRef.current || expiredShutdownRef.current) {
            return;
          }
        } catch (error) {
          if (disposed || manualShutdownRef.current || expiredShutdownRef.current) {
            return;
          }

          setMediaError(
            error instanceof Error
              ? error.message
              : "Microphone or camera permission was denied.",
          );
          await refreshAudioDevices();
          if (disposed || manualShutdownRef.current || expiredShutdownRef.current) {
            return;
          }
        }

        refreshMedia();
      } catch (error) {
        if (
          disposed
          || manualShutdownRef.current
          || expiredShutdownRef.current
          || error instanceof GatewaySocketCancelledError
        ) {
          return;
        }

        setConnectionError(
          error instanceof Error ? error.message : "Failed to connect to room runtime.",
        );
      }
    })();

    return () => {
      disposed = true;
      manualShutdownRef.current = true;
      if (localScreenTrackRef.current) {
        try {
          gatewayRef.current?.sendScreenShareStop();
        } catch {
          // best effort during teardown
        }

        void api.stopScreenShare(roomId, session.roomToken).catch(() => undefined);
      }
      unbindRoom();
      unsubscribeGateway();
      releaseGatewaySocket(session.sessionKey);
      gatewayRef.current = null;
      localAudioTrackRef.current = null;
      localVideoTrackRef.current = null;
      clearLocalScreenTrack(livekitRoomRef.current);
      disconnectRoom(livekitRoomRef.current);
      livekitRoomRef.current = null;
      refreshMediaRef.current = null;
    };
  }, [
    roomId,
    sessionKey,
    livekitUrl,
    livekitToken,
  ]);

  useEffect(() => {
    if (!session || typeof window === "undefined") {
      return;
    }

    const roomMetaExpiresAt =
      roomMeta?.room_id === session.roomId ? roomMeta.expires_at : null;
    const expiresAt = roomMetaExpiresAt ?? session.room.expires_at;
    const expiresAtMs = parseExpiresAtMs(expiresAt);
    if (expiresAtMs === null) {
      return;
    }

    const enforceExpiry = () => {
      if (expiredShutdownRef.current || manualShutdownRef.current) {
        return;
      }

      if (Date.now() >= expiresAtMs) {
        shutdownExpiredRoomSession({
          source: "local_timer",
          expiredAt: expiresAt,
        });
      }
    };

    enforceExpiry();
    if (expiredShutdownRef.current) {
      return;
    }

    const delayMs = Math.max(0, expiresAtMs - Date.now());
    const expiryTimer = window.setTimeout(
      enforceExpiry,
      Math.min(delayMs, 2_147_483_647),
    );

    window.addEventListener("focus", enforceExpiry);
    window.addEventListener("pageshow", enforceExpiry);
    document.addEventListener("visibilitychange", enforceExpiry);

    return () => {
      window.clearTimeout(expiryTimer);
      window.removeEventListener("focus", enforceExpiry);
      window.removeEventListener("pageshow", enforceExpiry);
      document.removeEventListener("visibilitychange", enforceExpiry);
    };
  }, [session, sessionKey, roomMeta?.expires_at]);

  useEffect(() => {
    refreshMediaRef.current?.();
  }, [
    participantsById,
    selfState?.participant_id,
    selfState?.language,
    roomMeta?.brse_enabled,
    roomMeta?.brse_mode,
    roomMeta?.brse_output_mode,
    roomMeta?.meeting_mode,
    roomMeta?.interpreter_mode,
    roomMeta?.audio_routing?.model,
    roomMeta?.audio_routing?.brse_mode,
    roomMeta?.audio_routing?.brse_output_mode,
    roomMeta?.audio_routing?.ai_audio_output_enabled,
    roomMeta?.audio_routing?.same_language_policy,
  ]);

  useEffect(() => {
    if (!session) {
      return;
    }

    const tryCleanupUnload = () => {
      if (hasLeftRef.current || hasSentLeaveRef.current) {
        return;
      }

      hasSentLeaveRef.current = true;
      hasLeftRef.current = true;
      manualShutdownRef.current = true;
      if (isScreenSharingRef.current) {
        try {
          gatewayRef.current?.sendScreenShareStop();
        } catch {
          // best effort for unload path
        }
      }
      const gateway = gatewayRef.current;
      gatewayRef.current = null;
      gateway?.disconnectForUnload("Page lifecycle cleanup");
      localAudioTrackRef.current = null;
      localVideoTrackRef.current = null;
      const lkRoom = livekitRoomRef.current;
      livekitRoomRef.current = null;
      clearLocalScreenTrack(lkRoom);
      disconnectRoom(lkRoom);
      leaveRoomBestEffort(roomId, session.roomToken);
      sessionInvalidatedRef.current();
    };

    const handleBeforeUnload = () => {
      tryCleanupUnload();
    };

    const handlePageHide = () => {
      tryCleanupUnload();
    };

    const handleUnload = () => {
      tryCleanupUnload();
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("unload", handleUnload);

    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("unload", handleUnload);
    };
  }, [roomId, session]);

  useEffect(() => {
    if (!session || typeof navigator === "undefined" || !navigator.mediaDevices) {
      return;
    }

    void refreshAudioDevices();

    const handleDeviceChange = () => {
      void refreshAudioDevices();
    };

    navigator.mediaDevices.addEventListener("devicechange", handleDeviceChange);
    return () => {
      navigator.mediaDevices.removeEventListener("devicechange", handleDeviceChange);
    };
  }, [session]);

  async function leaveRoom(): Promise<void> {
    if (!session || isLeaving) {
      return;
    }

    if (expiredShutdownRef.current) {
      return;
    }

    setIsLeaving(true);
    manualShutdownRef.current = true;

    try {
      if (!hasLeftRef.current) {
        hasLeftRef.current = true;
        if (isScreenSharing) {
          await stopScreenShare({
            reason: "leave_room",
            notifyBackend: true,
            signalWsFallback: false,
          });
        }
        if (!hasSentLeaveRef.current) {
          hasSentLeaveRef.current = true;
          try {
            await api.leaveRoom(roomId, session.roomToken);
          } catch (error) {
            if (!(error instanceof ApiError)) {
              console.error("Failed to leave room", error);
            }
          }
        }
      }
    } finally {
      const gateway = gatewayRef.current;
      gatewayRef.current = null;
      gateway?.disconnect();
      localAudioTrackRef.current = null;
      localVideoTrackRef.current = null;
      const lkRoom = livekitRoomRef.current;
      livekitRoomRef.current = null;
      clearLocalScreenTrack(lkRoom);
      disconnectRoom(lkRoom);
      sessionInvalidatedRef.current();
      setIsLeaving(false);
    }
  }

  /**
   * Must be called straight from a click handler: getDisplayMedia is invoked
   * synchronously inside so the browser keeps the user activation.
   */
  async function startScreenShare(
    options: StartScreenShareOptions = { quality: "detail", includeAudio: false },
  ): Promise<void> {
    if (
      !session
      || expiredShutdownRef.current
      || isRoomExpired
      || isStartingScreenShare
      || isStoppingScreenShare
      || isScreenSharing
    ) {
      return;
    }

    const livekitRoom = livekitRoomRef.current;
    if (!livekitRoom) {
      setScreenShareError("LiveKit room is not ready for screen sharing.");
      return;
    }

    setIsStartingScreenShare(true);
    setScreenShareError(null);
    setScreenShareNotice(null);

    try {
      const published = await publishScreenShareTrack(livekitRoom, options);
      localScreenTrackRef.current = published.track;
      localScreenAudioTrackRef.current = published.audioTrack;

      // Stopping from the browser's native "Stop sharing" ends the video track:
      // take the whole share down (video + audio). This is not an error.
      const handleVideoEnded = () => {
        void stopScreenShare({
          reason: "track_ended",
          notifyBackend: true,
          signalWsFallback: false,
        });
      };
      // Shared audio can end on its own (e.g. the tab's audio source goes away):
      // drop only the audio and keep the screen up.
      const audioTrack = published.audioTrack;
      const handleAudioEnded = () => {
        if (localScreenAudioTrackRef.current !== audioTrack) {
          return;
        }
        const room = livekitRoomRef.current;
        try {
          if (room && audioTrack) {
            unpublishScreenShareTrack(room, null, audioTrack);
          }
        } catch {
          audioTrack?.stop();
        }
        localScreenAudioTrackRef.current = null;
        refreshMediaRef.current?.();
      };

      published.track.mediaStreamTrack.addEventListener("ended", handleVideoEnded);
      audioTrack?.mediaStreamTrack.addEventListener("ended", handleAudioEnded);
      localScreenTrackCleanupRef.current = () => {
        published.track.mediaStreamTrack.removeEventListener("ended", handleVideoEnded);
        audioTrack?.mediaStreamTrack.removeEventListener("ended", handleAudioEnded);
      };

      const response = await api.startScreenShare(roomId, session.roomToken, {
        track_sid: published.trackSid,
        track_name: published.trackName,
        source: "screen_share",
      });

      setIsScreenSharing(response.active);
      setScreenShareNotice(buildScreenShareNotice(published));
      patchSelfScreenShareState({
        active: true,
        track_sid: response.track_sid ?? published.trackSid,
        track_name: response.track_name ?? published.trackName,
        timestamp: response.timestamp,
      });
      refreshMediaRef.current?.();
    } catch (error) {
      clearLocalScreenTrack(livekitRoom);
      refreshMediaRef.current?.();
      setScreenShareError(screenShareStartErrorMessage(error));
    } finally {
      setIsStartingScreenShare(false);
    }
  }

  async function stopScreenShare(options?: {
    reason?: string;
    notifyBackend?: boolean;
    signalWsFallback?: boolean;
  }): Promise<void> {
    if (expiredShutdownRef.current) {
      return;
    }

    if (stoppingScreenShareRef.current) {
      return;
    }

    const notifyBackend = options?.notifyBackend ?? true;
    const signalWsFallback = options?.signalWsFallback ?? false;
    const hasLocalScreenTrack = !!localScreenTrackRef.current;
    const canStop = hasLocalScreenTrack || isScreenSharing;
    if (!canStop) {
      return;
    }

    stoppingScreenShareRef.current = true;
    setIsStoppingScreenShare(true);
    setScreenShareError(null);
    setScreenShareNotice(null);

    try {
      if (session && notifyBackend) {
        try {
          await api.stopScreenShare(roomId, session.roomToken);
        } catch (error) {
          if (signalWsFallback) {
            try {
              gatewayRef.current?.sendScreenShareStop();
            } catch {
              // ignore fallback send failure
            }
          }

          setScreenShareError(
            error instanceof Error ? error.message : "Failed to sync screen share stop with backend.",
          );
        }
      }
    } finally {
      clearLocalScreenTrack(livekitRoomRef.current);
      setIsScreenSharing(false);
      patchSelfScreenShareState({
        active: false,
        timestamp: new Date().toISOString(),
      });
      refreshMediaRef.current?.();
      setIsStoppingScreenShare(false);
      stoppingScreenShareRef.current = false;
    }
  }

  async function toggleMicrophoneMuted(): Promise<void> {
    if (isTogglingMic || expiredShutdownRef.current || isRoomExpired) {
      return;
    }

    const localTrack = localAudioTrackRef.current;
    if (!localTrack) {
      setMicToggleError("Microphone track is not ready.");
      return;
    }

    setIsTogglingMic(true);
    setMicToggleError(null);
    try {
      const nextMuted = !isMicrophoneMuted(localTrack);
      await setLocalMicrophoneMuted(localTrack, nextMuted);
      setIsMicMuted(nextMuted);
      if (!nextMuted && isMutedByHostRef.current) {
        // A host can mute you; turning your own mic back on is up to you.
        setIsMutedByHost(false);
        gatewayRef.current?.sendSelfUnmuted();
      }
    } catch (error) {
      setMicToggleError(
        error instanceof Error ? error.message : "Failed to update microphone mute state.",
      );
    } finally {
      setIsTogglingMic(false);
    }
  }

  async function toggleCameraEnabled(): Promise<void> {
    if (isTogglingCamera || expiredShutdownRef.current || isRoomExpired) {
      return;
    }

    const livekitRoom = livekitRoomRef.current;
    if (!livekitRoom) {
      setCameraToggleError("LiveKit room is not ready for camera control.");
      return;
    }

    setIsTogglingCamera(true);
    setCameraToggleError(null);
    try {
      let localTrack = localVideoTrackRef.current ?? getLocalCameraTrack(livekitRoom);
      if (!localTrack) {
        localTrack = await publishLocalCameraTrack(livekitRoom);
        localVideoTrackRef.current = localTrack;
        setIsCameraOff(false);
        refreshMediaRef.current?.();
        return;
      }

      const nextMuted = !isCameraMuted(localTrack);
      await setLocalCameraMuted(localTrack, nextMuted);
      setIsCameraOff(nextMuted);
      refreshMediaRef.current?.();
    } catch (error) {
      setCameraToggleError(
        error instanceof Error ? error.message : "Failed to update camera state.",
      );
    } finally {
      setIsTogglingCamera(false);
    }
  }

  async function switchAudioInput(deviceId: string): Promise<void> {
    if (isSwitchingAudioInput || !deviceId || expiredShutdownRef.current || isRoomExpired) {
      return;
    }

    const livekitRoom = livekitRoomRef.current;
    if (!livekitRoom) {
      setAudioInputError("LiveKit room is not ready for switching microphone.");
      return;
    }

    setIsSwitchingAudioInput(true);
    setAudioInputError(null);
    try {
      const previousTrack = localAudioTrackRef.current;
      const shouldRemainMuted = isMicrophoneMuted(previousTrack);
      const nextTrack = await switchLocalMicrophoneTrack(
        livekitRoom,
        previousTrack,
        deviceId,
        { preserveMuted: shouldRemainMuted },
      );
      localAudioTrackRef.current = nextTrack;
      if (shouldRemainMuted && !isMicrophoneMuted(nextTrack)) {
        await setLocalMicrophoneMuted(nextTrack, true);
      }

      setSelectedAudioInputDeviceId(deviceId);
      setIsMicMuted(isMicrophoneMuted(nextTrack));
      refreshMediaRef.current?.();
      await refreshAudioDevices();
    } catch (error) {
      setAudioInputError(
        error instanceof Error ? error.message : "Failed to switch microphone input device.",
      );
    } finally {
      setIsSwitchingAudioInput(false);
    }
  }

  async function switchAudioOutput(deviceId: string): Promise<void> {
    if (isSwitchingAudioOutput || !deviceId || expiredShutdownRef.current || isRoomExpired) {
      return;
    }

    if (!audioOutputSupported) {
      setAudioOutputError("This browser does not support output device selection.");
      return;
    }

    setIsSwitchingAudioOutput(true);
    setAudioOutputError(null);
    try {
      await setRoomAudioOutputDevice(deviceId);
      setSelectedAudioOutputDeviceId(deviceId);
    } catch (error) {
      setAudioOutputError(
        error instanceof Error ? error.message : "Failed to switch output device.",
      );
    } finally {
      setIsSwitchingAudioOutput(false);
    }
  }

  async function toggleBrseMode(nextEnabled = !brseEnabledRef.current): Promise<void> {
    if (
      !session
      || expiredShutdownRef.current
      || isRoomExpired
      || isTogglingBrse
      || isUpdatingRelayMode
      || isLeaving
    ) {
      return;
    }

    if (nextEnabled === brseEnabledRef.current) {
      return;
    }

    setIsTogglingBrse(true);
    setBrseToggleError(null);

    try {
      const nextRoom = nextEnabled
        ? await api.enableBrse(roomId, session.roomToken)
        : await api.disableBrse(roomId, session.roomToken);
      const currentRoom = roomMetaRef.current;
      const mergedRoom = {
        ...(currentRoom ?? {}),
        ...nextRoom,
        room_id: nextRoom.room_id || currentRoom?.room_id || roomId,
        created_at:
          nextRoom.created_at || currentRoom?.created_at || session.room.created_at,
        expires_at:
          nextRoom.expires_at || currentRoom?.expires_at || session.room.expires_at,
        brse_enabled: nextRoom.brse_enabled ?? nextEnabled,
        brse_mode:
          nextRoom.brse_mode ?? currentRoom?.brse_mode ?? session.room.brse_mode,
        brse_output_mode:
          nextRoom.brse_output_mode ??
          currentRoom?.brse_output_mode ??
          session.room.brse_output_mode,
        audio_routing:
          nextRoom.audio_routing ?? currentRoom?.audio_routing ?? session.room.audio_routing,
        participant_count:
          currentRoom?.participant_count ?? countHumanParticipants(session.snapshot.participants),
      };

      setRoomMeta(mergedRoom);
      brseEnabledRef.current = resolveBrseEnabled(mergedRoom);

      if (!brseEnabledRef.current) {
        clearBrseRuntimeSurfaces();
      } else if (!isBrseAudioPossible(mergedRoom)) {
        setBrseAudioFeeds([]);
      }
    } catch (error) {
      setBrseToggleError(
        error instanceof Error ? error.message : "Failed to update BRSE mode.",
      );
    } finally {
      setIsTogglingBrse(false);
    }
  }

  function reportAudioOutputApplyError(message: string): void {
    setAudioOutputError(message);
  }

  async function refreshAudioDevices(): Promise<void> {
    try {
      const outputSupported = supportsAudioOutputSelection();
      setAudioOutputSupported(outputSupported);
      const deviceSet = await enumerateAudioDevices();
      setAudioInputDevices(deviceSet.audioInputs);
      setAudioOutputDevices(deviceSet.audioOutputs);
      setAudioInputError(null);

      const currentTrackDeviceId = getLocalTrackDeviceId(localAudioTrackRef.current);
      const selectedInputDeviceId = selectedAudioInputDeviceIdRef.current;
      const hasSelectedInput = deviceSet.audioInputs.some(
        (device) => device.deviceId === selectedInputDeviceId,
      );
      const nextInputDeviceId = hasSelectedInput
        ? selectedInputDeviceId
        : deviceSet.audioInputs.find((device) => device.deviceId === currentTrackDeviceId)?.deviceId
          || deviceSet.audioInputs[0]?.deviceId
          || "";
      setSelectedAudioInputDeviceId(nextInputDeviceId);

      if (selectedInputDeviceId && !hasSelectedInput && deviceSet.audioInputs.length > 0) {
        setAudioInputError("Selected microphone is unavailable. Switched to another device.");
        if (nextInputDeviceId && !isSwitchingAudioInputRef.current) {
          void switchAudioInput(nextInputDeviceId);
        }
      }

      if (!outputSupported) {
        setSelectedAudioOutputDeviceId("");
        setAudioOutputError("This browser does not support output device selection.");
        void setRoomAudioOutputDevice("").catch(() => undefined);
        return;
      }

      const selectedOutputDeviceId = selectedAudioOutputDeviceIdRef.current;
      const hasSelectedOutput = deviceSet.audioOutputs.some(
        (device) => device.deviceId === selectedOutputDeviceId,
      );
      const nextOutputDeviceId = hasSelectedOutput
        ? selectedOutputDeviceId
        : deviceSet.audioOutputs[0]?.deviceId || "default";
      setSelectedAudioOutputDeviceId(nextOutputDeviceId);
      await setRoomAudioOutputDevice(nextOutputDeviceId);

      if (selectedOutputDeviceId && !hasSelectedOutput && deviceSet.audioOutputs.length > 0) {
        setAudioOutputError("Selected output device is unavailable. Switched to another device.");
      } else {
        setAudioOutputError(null);
      }
    } catch (error) {
      setAudioInputError(
        error instanceof Error ? error.message : "Failed to enumerate audio input devices.",
      );
      setAudioOutputError(
        error instanceof Error ? error.message : "Failed to enumerate audio output devices.",
      );
    }
  }

  function changeLanguage(nextLanguage: Language): void {
    if (expiredShutdownRef.current || isRoomExpired) {
      return;
    }

    const currentSelf = selfRef.current;
    if (!currentSelf || currentSelf.language === nextLanguage) {
      return;
    }

    const meetingLanguages = normalizeRoomLanguages(roomMeta);
    if (!meetingLanguages.includes(nextLanguage as MeetingLanguage)) {
      setConnectionError(
        meetingLanguages.length > 0
          ? `Language must match the room languages: ${formatRoomLanguageList(meetingLanguages)}.`
          : "Room languages are unavailable. Reload room snapshot or ask the host to recreate the room.",
      );
      return;
    }

    pendingLanguageRef.current = {
      previous: currentSelf.language,
      requested: nextLanguage,
    };

    setSelfState({
      ...currentSelf,
      language: nextLanguage,
    });
    setParticipantsById((current) => ({
      ...current,
      [currentSelf.participant_id]: {
        ...current[currentSelf.participant_id],
        participant_id: currentSelf.participant_id,
        display_name: currentSelf.display_name,
        joined_at: current[currentSelf.participant_id]?.joined_at,
        status: current[currentSelf.participant_id]?.status || "connected",
        language: nextLanguage,
      },
    }));

    try {
      gatewayRef.current?.setLanguage(nextLanguage);
    } catch (error) {
      rollbackLanguage();
      setConnectionError(
        error instanceof Error
          ? error.message
          : "Gateway is not ready for language change.",
      );
    }
  }

  function handleGatewayEvent(event: ServerEvent): void {
    switch (event.type) {
      case "room.snapshot":
        applyRoomSnapshot(event);
        return;
      case "participant.joined":
        applyParticipantJoined(event);
        return;
      case "participant.updated":
        applyParticipantUpdated(event);
        return;
      case "participant.left":
        applyParticipantLeft(event);
        return;
      case "screen_share.started":
        applyScreenShareStarted(event);
        return;
      case "screen_share.stopped":
        applyScreenShareStopped(event);
        return;
      case "room.brse_updated":
        applyBrseUpdated(event);
        return;
      case "room.relay_mode_updated":
        applyRelayModeUpdated(event);
        return;
      case "recording.starting":
      case "recording.started":
      case "recording.stopping":
      case "recording.stopped":
      case "recording.processing":
      case "recording.ready":
      case "recording.failed":
        // Recording state lives in useRoomRecording; forward the event.
        recordingListenersRef.current.forEach((listener) => listener(event));
        return;
      case "room.expired":
        applyRoomExpired(event);
        return;
      case "transcript.partial":
      case "transcript.final":
        applyTranscriptEvent(event);
        return;
      case "interpreter.status":
        applyInterpreterStatus(event);
        return;
      case "chat.message":
        applyChatMessage(event);
        return;
      case "room.host_changed":
        applyHostChanged(event);
        return;
      case "moderation.force_muted":
        applyForceMuted(event);
        return;
      case "participant.role_changed":
        applyRoleChanged(event);
        return;
      case "participant.removed":
        applyParticipantRemoved(event);
        return;
      case "room.lock_changed":
        applyRoomLockChanged(event);
        return;
      case "room.access_updated":
        applyRoomAccessUpdated(event);
        return;
      case "moderation.participant_muted":
        applyParticipantMuted(event);
        return;
      case "error":
        applyGatewayError(event);
        return;
      case "pong":
      default:
        return;
    }
  }

  function shutdownExpiredRoomSession(details: RoomExpiredDetails): void {
    if (expiredShutdownRef.current) {
      return;
    }

    expiredShutdownRef.current = true;
    manualShutdownRef.current = true;
    hasLeftRef.current = true;
    hasSentLeaveRef.current = true;
    pendingLanguageRef.current = null;
    pendingChatEventIdsRef.current.clear();

    setIsRoomExpired(true);
    setConnectionError(details.message ?? "This meeting has ended.");
    setRoomMeta((current) =>
      current
        ? {
            ...current,
            state: "empty",
            expires_at: details.expiredAt ?? current.expires_at,
            participant_count: 0,
          }
        : current,
    );
    void fetchMeetingSummary("final", {
      suppressNotFound: true,
    });

    if (isScreenSharingRef.current || localScreenTrackRef.current) {
      try {
        gatewayRef.current?.sendScreenShareStop();
      } catch {
        // Gateway may already be closing on expiry.
      }

      if (session) {
        void api.stopScreenShare(roomId, session.roomToken).catch(() => undefined);
      }
    }

    const gateway = gatewayRef.current;
    gatewayRef.current = null;
    gateway?.disconnect("Room expired");

    const livekitRoom = livekitRoomRef.current;
    livekitRoomRef.current = null;
    clearLocalScreenTrack(livekitRoom);
    disconnectRoom(livekitRoom);

    localAudioTrackRef.current = null;
    localVideoTrackRef.current = null;
    refreshMediaRef.current = null;
    localScreenTrackCleanupRef.current = null;
    stoppingScreenShareRef.current = false;

    setGatewayState("disconnected");
    setLivekitState("disconnected");
    setVideos([]);
    setHumanAudioFeeds([]);
    setBrseAudioFeeds([]);
    setScreenShares([]);
    setInterpreterStatuses([]);
    setSelfState(null);
    setParticipantsById({});
    setTranscripts([]);
    setChatMessages([]);
    setChatError(null);
    setIsSendingChat(false);
    setMediaError(null);
    setScreenShareError(null);
    setScreenShareNotice(null);
    setIsScreenSharing(false);
    setIsStartingScreenShare(false);
    setIsStoppingScreenShare(false);
    setIsMicMuted(false);
    setIsTogglingMic(false);
    setMicToggleError(null);
    setIsCameraOff(true);
    setIsTogglingCamera(false);
    setCameraToggleError(null);
    setAudioInputDevices([]);
    setSelectedAudioInputDeviceId("");
    setIsSwitchingAudioInput(false);
    setAudioInputError(null);
    setAudioOutputDevices([]);
    setSelectedAudioOutputDeviceId("default");
    setAudioOutputSupported(false);
    setIsSwitchingAudioOutput(false);
    setAudioOutputError(null);
    setIsLeaving(false);
    setIsTogglingBrse(false);
    setBrseToggleError(null);
    setHostParticipantId(null);
    setIsMutedByHost(false);
    setIsMutingParticipant(null);
    setModerationError(null);
    void setRoomAudioOutputDevice("").catch(() => undefined);

    sessionInvalidatedRef.current();
    roomExpiredCallbackRef.current?.(details);
  }

  function applyRoomSnapshot(event: RoomSnapshotEvent): void {
    const snapshotExpiresAt = event.payload.room.expires_at ?? roomMetaRef.current?.expires_at ?? null;
    if (isExpiredAt(snapshotExpiresAt)) {
      shutdownExpiredRoomSession({
        source: "snapshot",
        expiredAt: snapshotExpiresAt,
      });
      return;
    }

    const snapshotRoomForMode = {
      ...(roomMetaRef.current ?? {}),
      ...event.payload.room,
    };
    const snapshotBrseEnabled = resolveBrseEnabled(snapshotRoomForMode);
    const snapshotBrseAudioPossible = isBrseAudioPossible(snapshotRoomForMode);
    brseEnabledRef.current = snapshotBrseEnabled;

    const snapshotRoomLanguages = normalizeRoomLanguages(event.payload.room);
    setSelfState(event.payload.self);
    setSelfRole(normalizeRole(event.payload.self.role));
    setPermissionsEnforced(event.payload.self.permissions_enforced ?? true);
    setParticipantsById(mapParticipants(event.payload.participants));
    syncLocalScreenShareState(event.payload.participants, event.payload.self.participant_id);
    setRoomMeta((current) => ({
      room_id: current?.room_id || roomId,
      state: event.payload.room.state,
      created_at: current?.created_at || new Date().toISOString(),
      expires_at: event.payload.room.expires_at ?? current?.expires_at ?? new Date().toISOString(),
      brse_enabled: event.payload.room.brse_enabled ?? current?.brse_enabled,
      brse_mode: event.payload.room.brse_mode ?? current?.brse_mode,
      brse_output_mode:
        event.payload.room.brse_output_mode ?? current?.brse_output_mode,
      participant_limit: event.payload.room.participant_limit,
      supported_languages: event.payload.room.supported_languages,
      room_languages: snapshotRoomLanguages,
      meeting_languages: event.payload.room.meeting_languages ?? snapshotRoomLanguages,
      language_a: event.payload.room.language_a ?? snapshotRoomLanguages[0],
      language_b: event.payload.room.language_b ?? snapshotRoomLanguages[1],
      meeting_mode: event.payload.room.meeting_mode ?? current?.meeting_mode,
      interpreter_mode:
        event.payload.room.interpreter_mode ?? current?.interpreter_mode,
      audio_routing:
        event.payload.room.audio_routing ?? current?.audio_routing,
      password_required: event.payload.room.password_required ?? current?.password_required,
      title: event.payload.room.title ?? current?.title ?? null,
      locked: event.payload.room.locked ?? current?.locked ?? false,
      participant_count: countHumanParticipants(event.payload.participants),
    }));

    if (!snapshotBrseEnabled) {
      clearBrseRuntimeSurfaces();
    } else if (!snapshotBrseAudioPossible) {
      setBrseAudioFeeds([]);
    }

    startTransition(() => {
      setTranscripts((current) =>
        mergeTranscriptCollections(
          current,
          hydrateTranscriptEntries(
            event.payload.recent_transcripts,
            event.payload.self.language,
          ).filter((entry) => snapshotBrseEnabled || entry.kind !== "relay"),
        ),
      );
    });

    // Host state from snapshot
    const snapshotHostId = event.payload.host_participant_id ?? null;
    const hostFromParticipant = event.payload.participants.find((p) => p.role === "host" || p.is_host);
    setHostParticipantId(snapshotHostId || hostFromParticipant?.participant_id || null);

    // Chat messages from snapshot
    const snapshotMessages = event.payload.recent_messages ?? [];
    if (snapshotMessages.length > 0) {
      setChatMessages((current) =>
        mergeRoomChatMessages(current, normalizeChatMessages(snapshotMessages)),
      );
    }

    // Self muted-by-host state from snapshot
    const selfFromSnapshot = event.payload.participants.find(
      (p) => p.participant_id === event.payload.self.participant_id,
    );
    if (selfFromSnapshot?.muted_by_host) {
      handleForceMuteLocal();
    }
  }

  function applyParticipantJoined(event: ParticipantJoinedEvent): void {
    const isVirtual = event.payload.kind === "virtual_brse" || event.payload.is_virtual;
    setParticipantsById((current) => ({
      ...current,
      [event.payload.participant_id]: {
        participant_id: event.payload.participant_id,
        display_name: event.payload.display_name,
        language: event.payload.language,
        status: event.payload.status,
        joined_at: event.payload.joined_at,
        kind: event.payload.kind,
        is_virtual: event.payload.is_virtual,
        livekit_identity: event.payload.livekit_identity,
        metadata: event.payload.metadata,
        is_screen_sharing: event.payload.is_screen_sharing ?? false,
        screen_share: event.payload.screen_share ?? null,
        role: event.payload.role,
        muted_by_host: event.payload.muted_by_host ?? false,
      },
    }));
    setRoomMeta((current) =>
      current
        ? {
            ...current,
            participant_count: isVirtual
              ? current.participant_count
              : current.participant_count + 1,
          }
        : current,
    );

    // Track host from joined event
    if (event.payload.role === "host" || event.payload.is_host) {
      setHostParticipantId(event.payload.participant_id);
    }
  }

  function applyParticipantUpdated(event: ParticipantUpdatedEvent): void {
    setParticipantsById((current) => {
      const existing = current[event.payload.participant_id];
      return {
        ...current,
        [event.payload.participant_id]: {
          participant_id: event.payload.participant_id,
          display_name: event.payload.display_name,
          language: event.payload.language,
          status: event.payload.status,
          joined_at: event.payload.joined_at ?? existing?.joined_at,
          kind: event.payload.kind ?? existing?.kind,
          is_virtual: event.payload.is_virtual ?? existing?.is_virtual,
          livekit_identity:
            event.payload.livekit_identity ?? existing?.livekit_identity,
          metadata: event.payload.metadata ?? existing?.metadata,
          is_screen_sharing:
            event.payload.is_screen_sharing ?? existing?.is_screen_sharing ?? false,
          screen_share: event.payload.screen_share ?? existing?.screen_share ?? null,
          is_host: event.payload.is_host ?? existing?.is_host,
          role: event.payload.role ?? existing?.role,
          muted_by_host: event.payload.muted_by_host ?? existing?.muted_by_host,
        },
      };
    });

    if (selfRef.current?.participant_id === event.payload.participant_id) {
      setSelfState((current) =>
        current
          ? {
              ...current,
              display_name: event.payload.display_name,
              language: event.payload.language,
            }
          : current,
      );

      if (pendingLanguageRef.current?.requested === event.payload.language) {
        pendingLanguageRef.current = null;
      }

      const backendSaysSharing = !!event.payload.is_screen_sharing;
      setIsScreenSharing(backendSaysSharing);
      if (!backendSaysSharing) {
        clearLocalScreenTrack(livekitRoomRef.current);
      }
    }
  }

  function applyParticipantLeft(event: ParticipantLeftEvent): void {
    const leftParticipant = participantsRef.current[event.payload.participant_id];
    const isVirtual =
      leftParticipant?.kind === "virtual_brse" || leftParticipant?.is_virtual;
    setParticipantsById((current) => {
      if (!(event.payload.participant_id in current)) {
        return current;
      }

      const next = { ...current };
      delete next[event.payload.participant_id];
      return next;
    });
    setRoomMeta((current) =>
      current
        ? {
            ...current,
            participant_count: isVirtual
              ? current.participant_count
              : Math.max(0, current.participant_count - 1),
          }
        : current,
    );

    if (event.payload.participant_id === selfRef.current?.participant_id) {
      setIsScreenSharing(false);
      clearLocalScreenTrack(livekitRoomRef.current);
    }
  }

  function applyScreenShareStarted(event: ScreenShareStartedEvent): void {
    setParticipantsById((current) => {
      const existing = current[event.payload.participant_id];
      if (!existing) {
        return current;
      }

      return {
        ...current,
        [event.payload.participant_id]: {
          ...existing,
          is_screen_sharing: true,
          screen_share: {
            active: true,
            source: event.payload.source,
            track_sid: event.payload.track_sid,
            track_name: event.payload.track_name,
            started_at: event.payload.timestamp,
          },
        },
      };
    });

    if (event.payload.participant_id === selfRef.current?.participant_id) {
      setIsScreenSharing(true);
    }
  }

  function applyScreenShareStopped(event: ScreenShareStoppedEvent): void {
    setParticipantsById((current) => {
      const existing = current[event.payload.participant_id];
      if (!existing) {
        return current;
      }

      return {
        ...current,
        [event.payload.participant_id]: {
          ...existing,
          is_screen_sharing: false,
          screen_share: null,
        },
      };
    });

    if (event.payload.participant_id === selfRef.current?.participant_id) {
      setIsScreenSharing(false);
      clearLocalScreenTrack(livekitRoomRef.current);
    }
  }

  function applyBrseUpdated(event: RoomBrseUpdatedEvent): void {
    const nextEnabled = event.payload.brse_enabled;
    const currentRoom = roomMetaRef.current;
    const nextBrseMode = event.payload.brse_mode ?? currentRoom?.brse_mode;
    const nextMeetingMode: RoomSnapshotResponse["room"]["meeting_mode"] =
      nextEnabled
        ? nextBrseMode === "silent_summary"
          ? "brse_silent_summary"
          : "brse_relay"
        : "direct_translation";
    const nextRoomForMode = {
      ...(currentRoom ?? {}),
      brse_enabled: nextEnabled,
      brse_mode: nextBrseMode,
      brse_output_mode:
        event.payload.brse_output_mode ?? currentRoom?.brse_output_mode,
      audio_routing: event.payload.audio_routing ?? currentRoom?.audio_routing,
      meeting_mode: nextMeetingMode,
    };

    setRoomMeta((current) =>
      current
        ? {
            ...current,
            brse_enabled: nextEnabled,
            brse_mode: nextBrseMode ?? current.brse_mode,
            brse_output_mode:
              event.payload.brse_output_mode ?? current.brse_output_mode,
            audio_routing: event.payload.audio_routing ?? current.audio_routing,
            meeting_mode: nextMeetingMode,
            interpreter_mode: nextEnabled
              ? "brse_participant"
              : current.interpreter_mode,
          }
        : current,
    );
    brseEnabledRef.current = nextEnabled;
    setIsTogglingBrse(false);
    setBrseToggleError(null);

    if (!nextEnabled) {
      clearBrseRuntimeSurfaces();
    } else if (!isBrseAudioPossible(nextRoomForMode)) {
      setBrseAudioFeeds([]);
    }
  }

  function applyRelayModeState(next: RelayModeState): void {
    setRoomMeta((current) => (current ? applyRelayModeToRoom(current, next) : current));
  }

  function applyRelayModeUpdated(event: RoomRelayModeUpdatedEvent): void {
    relayModeEventSeqRef.current += 1;
    applyRelayModeState(event.payload);
    setRelayModeError(null);
  }

  async function changeRelayMode(nextMode: BrseOutputMode): Promise<void> {
    if (
      !session
      || expiredShutdownRef.current
      || isRoomExpired
      || isUpdatingRelayMode
      || isTogglingBrse
      || isLeaving
    ) {
      return;
    }
    const currentRoom = roomMetaRef.current ?? session.room;
    if (
      !getSelectableRelayModes(currentRoom).includes(nextMode)
      || resolveBrseOutputMode(currentRoom) === nextMode
    ) {
      return;
    }

    const eventSeqAtStart = relayModeEventSeqRef.current;
    setIsUpdatingRelayMode(true);
    setRelayModeError(null);
    try {
      const nextRoom = await api.updateRelayMode(roomId, session.roomToken, nextMode);
      // If another participant's change was broadcast meanwhile, that event is newer.
      if (relayModeEventSeqRef.current === eventSeqAtStart) {
        applyRelayModeState(nextRoom);
      }
    } catch (error) {
      setRelayModeError(relayModeErrorMessage(error instanceof ApiError ? error.code : null));
    } finally {
      setIsUpdatingRelayMode(false);
    }
  }

  function applyRoomExpired(event: RoomExpiredEvent): void {
    shutdownExpiredRoomSession({
      source: "gateway_event",
      expiredAt: event.payload.expired_at,
      message: "This meeting has ended.",
    });
  }

  function applyTranscriptEvent(
    event: TranscriptPartialEvent | TranscriptFinalEvent,
  ): void {
    if (!brseEnabledRef.current && event.payload.kind === "relay") {
      return;
    }

    startTransition(() => {
      setTranscripts((current) =>
        upsertTranscriptEntry(current, event.payload, event.sent_at),
      );
    });
  }

  function applyInterpreterStatus(event: ServerEvent & { type: "interpreter.status" }): void {
    if (!brseEnabledRef.current) {
      return;
    }

    setInterpreterStatuses((current) =>
      upsertInterpreterStatus(
        current,
        event.payload,
        event.sent_at,
        participantsRef.current,
      ),
    );
  }

  function applyGatewayError(event: ErrorEvent): void {
    if (event.event_id && pendingChatEventIdsRef.current.has(event.event_id)) {
      pendingChatEventIdsRef.current.delete(event.event_id);
      setChatMessages((current) =>
        markRoomChatDeliveryStatus(current, event.event_id, "failed"),
      );
      setChatError(event.payload.message || "Failed to send chat message.");
      setIsSendingChat(false);
      return;
    }

    if (pendingLanguageRef.current) {
      rollbackLanguage();
    }

    if (event.payload.code === "room_expired") {
      const currentRoomMeta = roomMetaRef.current;
      shutdownExpiredRoomSession({
        source: "gateway_error",
        expiredAt:
          currentRoomMeta?.room_id === (session?.roomId ?? roomId)
            ? currentRoomMeta.expires_at
            : session?.room.expires_at ?? event.sent_at,
        message: event.payload.message || "This meeting has ended.",
      });
      return;
    }

    if (event.payload.code === "invalid_language") {
      const meetingLanguages = normalizeRoomLanguages(roomMetaRef.current);
      setConnectionError(
        meetingLanguages.length > 0
          ? `Language must match the room languages: ${formatRoomLanguageList(meetingLanguages)}.`
          : "Language must match the room languages for this room.",
      );
      return;
    }

    setConnectionError(event.payload.message);
  }

  // ─── Chat handlers ────────────────────────────────────────────────────────

  function applyChatMessage(event: ChatMessageEvent): void {
    const messages = normalizeChatMessages([event.payload]);
    for (const message of messages) {
      if (message.client_event_id) {
        pendingChatEventIdsRef.current.delete(message.client_event_id);
      }
    }

    setChatMessages((current) =>
      mergeRoomChatMessages(current, messages),
    );
    setChatError(null);
  }

  async function sendChatMessage(
    text: string,
    translationMode: ChatTranslationMode = "original_only",
  ): Promise<boolean> {
    const trimmed = text.trim();
    if (!trimmed || isSendingChat || expiredShutdownRef.current || isRoomExpired) {
      return false;
    }

    const currentSelf = selfRef.current;
    const gateway = gatewayRef.current;
    if (!currentSelf || !gateway || gateway.getState() !== "connected") {
      setChatError("Chat is unavailable until the room websocket is connected.");
      return false;
    }

    setIsSendingChat(true);
    setChatError(null);

    try {
      const clientEventId = gateway.sendChatMessage(trimmed, translationMode);
      pendingChatEventIdsRef.current.add(clientEventId);
      const optimisticMessage = createOptimisticChatMessage(
        currentSelf,
        trimmed,
        clientEventId,
        translationMode,
      );
      setChatMessages((current) => mergeRoomChatMessages(current, [optimisticMessage]));
      return true;
    } catch (error) {
      setChatError(
        error instanceof Error ? error.message : "Failed to send chat message.",
      );
      return false;
    } finally {
      setIsSendingChat(false);
    }
  }

  // ─── Meeting summary handlers ────────────────────────────────────────────

  function resolveCurrentSummaryLanguage(): MeetingLanguage | null {
    const currentLanguage = selfRef.current?.language ?? session?.participant.language ?? null;
    if (!currentLanguage || currentLanguage === "auto") {
      return null;
    }
    return currentLanguage as MeetingLanguage;
  }

  async function fetchMeetingSummary(
    type: MeetingSummaryType,
    options: {
      silent?: boolean;
      suppressNotFound?: boolean;
    } = {},
  ): Promise<MeetingSummaryResponse | null> {
    if (!roomId) {
      return null;
    }

    const requestId = ++summaryRequestSeqRef.current;
    setSummaryIntent(type);
    if (!options.silent) {
      setMeetingSummary((current) => current?.summary_type === type ? current : null);
      setIsLoadingSummary(true);
      setSummaryError(null);
      setSummaryErrorSource(null);
    }

    try {
      const response = await api.getRoomSummary(roomId, type, session?.roomToken ?? null);
      if (requestId !== summaryRequestSeqRef.current) {
        return null;
      }

      const normalized = normalizeMeetingSummaryResponse(response, type);
      setMeetingSummary(normalized);
      setSummaryError(null);
      setSummaryErrorSource(null);
      if (type === "final") {
        if (normalized.status === "pending") {
          scheduleFinalSummaryPoll();
        } else {
          clearFinalSummaryPollTimer();
        }
      }
      return normalized;
    } catch (error) {
      if (requestId !== summaryRequestSeqRef.current) {
        return null;
      }

      if (
        error instanceof ApiError
        && error.code === "meeting_summary_not_found"
        && options.suppressNotFound
      ) {
        if (!options.silent) {
          setMeetingSummary(null);
          setSummaryError(null);
          setSummaryErrorSource(null);
        }
        return null;
      }

      setSummaryError(mapMeetingSummaryFetchError(error, type));
      setSummaryErrorSource("fetch");
      return null;
    } finally {
      if (requestId === summaryRequestSeqRef.current && !options.silent) {
        setIsLoadingSummary(false);
      }
    }
  }

  async function generateMeetingSummary(
    type: MeetingSummaryType,
  ): Promise<MeetingSummaryResponse | null> {
    if (!roomId) {
      return null;
    }

    const currentSummary = meetingSummaryRef.current;
    if (
      type === "final"
      && currentSummary?.summary_type === "final"
      && (currentSummary.status === "completed" || currentSummary.status === "pending")
    ) {
      return currentSummary;
    }

    if (type === "final") {
      clearFinalSummaryPollTimer();
    }

    const requestId = ++summaryRequestSeqRef.current;
    setSummaryIntent(type);
    setMeetingSummary((current) => current?.summary_type === type ? current : null);
    setIsGeneratingSummary(true);
    setSummaryError(null);
    setSummaryErrorSource(null);

    try {
      const response = await api.generateRoomSummary(roomId, type, {
        language: resolveCurrentSummaryLanguage(),
        token: session?.roomToken ?? null,
      });
      if (requestId !== summaryRequestSeqRef.current) {
        return null;
      }

      const normalized = normalizeMeetingSummaryResponse(response, type);
      setMeetingSummary(normalized);
      setSummaryError(null);
      setSummaryErrorSource(null);
      if (type === "final") {
        if (normalized.status === "pending") {
          scheduleFinalSummaryPoll();
        } else {
          clearFinalSummaryPollTimer();
        }
      }
      return normalized;
    } catch (error) {
      if (requestId !== summaryRequestSeqRef.current) {
        return null;
      }

      if (
        type === "final"
        && error instanceof ApiError
        && (
          error.code === "meeting_summary_not_ready"
          || error.code === "meeting_summary_not_found"
        )
      ) {
        const pending = createPendingMeetingSummary(
          roomId,
          "final",
          resolveCurrentSummaryLanguage(),
        );
        setMeetingSummary(pending);
        setSummaryError(null);
        setSummaryErrorSource(null);
        scheduleFinalSummaryPoll();
        return pending;
      }

      setSummaryError(mapMeetingSummaryGenerateError(error, type));
      setSummaryErrorSource("generate");
      return null;
    } finally {
      if (requestId === summaryRequestSeqRef.current) {
        setIsGeneratingSummary(false);
      }
    }
  }

  async function refreshInterimSummary(): Promise<MeetingSummaryResponse | null> {
    if (expiredShutdownRef.current || isRoomExpired) {
      return null;
    }
    return generateMeetingSummary("interim");
  }

  async function prepareFinalSummary(): Promise<MeetingSummaryResponse | null> {
    finalSummaryPollCountRef.current = 0;
    return generateMeetingSummary("final");
  }

  function scheduleFinalSummaryPoll(): void {
    if (typeof window === "undefined") {
      return;
    }

    clearFinalSummaryPollTimer();
    if (finalSummaryPollCountRef.current >= FINAL_SUMMARY_MAX_POLLS) {
      return;
    }

    finalSummaryPollTimerRef.current = window.setTimeout(() => {
      finalSummaryPollTimerRef.current = null;
      finalSummaryPollCountRef.current += 1;
      void fetchMeetingSummary("final", {
        silent: true,
        suppressNotFound: true,
      }).then((summary) => {
        if (!summary || summary.status === "pending") {
          scheduleFinalSummaryPoll();
        }
      });
    }, FINAL_SUMMARY_POLL_INTERVAL_MS);
  }

  function clearFinalSummaryPollTimer(): void {
    if (typeof window === "undefined" || finalSummaryPollTimerRef.current === null) {
      finalSummaryPollTimerRef.current = null;
      return;
    }

    window.clearTimeout(finalSummaryPollTimerRef.current);
    finalSummaryPollTimerRef.current = null;
  }

  // ─── Host handlers ────────────────────────────────────────────────────────

  function applyHostChanged(event: RoomHostChangedEvent): void {
    setHostParticipantId(event.payload.new_host_id);

    // Update is_host flags on all participants
    setParticipantsById((current) => {
      const next: Record<string, ParticipantSnapshot> = {};
      for (const [id, p] of Object.entries(current)) {
        next[id] = {
          ...p,
          is_host: id === event.payload.new_host_id,
        };
      }
      return next;
    });
  }

  function applyRoleChanged(event: ParticipantRoleChangedEvent): void {
    const ids = new Set([event.payload.participant_id, ...(event.payload.participant_ids ?? [])]);
    setParticipantsById((current) => {
      const next = { ...current };
      for (const id of ids) {
        if (next[id]) next[id] = { ...next[id], role: event.payload.new_role };
      }
      return next;
    });
    const selfId = selfRef.current?.participant_id;
    if (selfId && ids.has(selfId)) {
      setSelfRole(event.payload.new_role);
      const by = event.payload.changed_by_name ?? "The host";
      setRoleNotice(
        event.payload.new_role === "co_host"
          ? `${by} made you a co-host. You can now manage AI relay, recording and participants.`
          : "You're no longer a co-host.",
      );
    }
  }

  function applyParticipantRemoved(event: ParticipantRemovedEvent): void {
    if (event.payload.participant_id === selfRef.current?.participant_id) {
      handleRemovedFromMeeting(event.payload.removed_by ?? null);
      return;
    }
    setParticipantsById((current) => {
      if (!(event.payload.participant_id in current)) return current;
      const next = { ...current };
      delete next[event.payload.participant_id];
      return next;
    });
  }

  function applyRoomLockChanged(event: RoomLockChangedEvent): void {
    setRoomMeta((current) => (current ? { ...current, locked: event.payload.locked } : current));
  }

  function applyRoomAccessUpdated(event: RoomAccessUpdatedEvent): void {
    setRoomMeta((current) =>
      current ? { ...current, password_required: event.payload.password_required } : current,
    );
  }

  /** Removed by the host: leave every connection; the server already refuses a rejoin. */
  function handleRemovedFromMeeting(by: string | null): void {
    if (manualShutdownRef.current && removedFromMeetingRef.current) return;
    removedFromMeetingRef.current = true;
    manualShutdownRef.current = true;
    hasLeftRef.current = true;
    hasSentLeaveRef.current = true;
    setRemovedFromMeeting({ by });
    const gateway = gatewayRef.current;
    gatewayRef.current = null;
    gateway?.disconnect("Removed from meeting");
    const lkRoom = livekitRoomRef.current;
    livekitRoomRef.current = null;
    localAudioTrackRef.current = null;
    localVideoTrackRef.current = null;
    clearLocalScreenTrack(lkRoom);
    disconnectRoom(lkRoom);
    sessionInvalidatedRef.current();
  }

  async function runManagementAction<T>(name: string, action: (token: string) => Promise<T>): Promise<T | null> {
    if (!session || expiredShutdownRef.current || isRoomExpired) return null;
    setPendingManagementAction(name);
    setModerationError(null);
    try {
      return await action(session.roomToken);
    } catch (error) {
      setModerationError(managementErrorMessage(error));
      return null;
    } finally {
      setPendingManagementAction(null);
    }
  }

  async function removeParticipant(participantId: string): Promise<void> {
    await runManagementAction(`remove:${participantId}`, (token) => api.removeParticipant(roomId, token, participantId));
  }

  async function setParticipantRole(participantId: string, role: Exclude<RoomRole, "host">): Promise<void> {
    await runManagementAction(`role:${participantId}`, (token) => api.setParticipantRole(roomId, token, participantId, role));
  }

  async function setRoomLocked(locked: boolean): Promise<void> {
    const room = await runManagementAction("lock", (token) => api.setRoomLocked(roomId, token, locked));
    if (room) setRoomMeta((current) => (current ? { ...current, locked: !!room.locked } : current));
  }

  /** Throws so the password dialog can show the error next to the field. */
  async function changeRoomPassword(password: string): Promise<void> {
    if (!session) return;
    setPendingManagementAction("password");
    try {
      const room = await api.changeRoomPassword(roomId, session.roomToken, password);
      setRoomMeta((current) => (current ? { ...current, password_required: !!room.password_required } : current));
    } finally {
      setPendingManagementAction(null);
    }
  }

  async function removeRoomPassword(): Promise<void> {
    const room = await runManagementAction("password", (token) => api.removeRoomPassword(roomId, token));
    if (room) setRoomMeta((current) => (current ? { ...current, password_required: !!room.password_required } : current));
  }

  // ─── Moderation handlers ──────────────────────────────────────────────────

  function applyForceMuted(event: ModerationForceMutedEvent): void {
    if (event.payload.participant_id === selfRef.current?.participant_id) {
      handleForceMuteLocal();
    }

    // Update participant state
    setParticipantsById((current) => {
      const existing = current[event.payload.participant_id];
      if (!existing) return current;
      return {
        ...current,
        [event.payload.participant_id]: {
          ...existing,
          muted_by_host: true,
        },
      };
    });
  }

  function applyParticipantMuted(event: ModerationParticipantMutedEvent): void {
    setParticipantsById((current) => {
      const existing = current[event.payload.participant_id];
      if (!existing) return current;
      return {
        ...current,
        [event.payload.participant_id]: {
          ...existing,
          muted_by_host: event.payload.muted_by_host,
        },
      };
    });

    if (event.payload.participant_id === selfRef.current?.participant_id && event.payload.muted_by_host) {
      handleForceMuteLocal();
    }
  }

  function handleForceMuteLocal(): void {
    setIsMutedByHost(true);
    const localTrack = localAudioTrackRef.current;
    if (localTrack) {
      void setLocalMicrophoneMuted(localTrack, true)
        .then(() => {
          setIsMicMuted(true);
        })
        .catch(() => {
          setIsMicMuted(true);
        });
    } else {
      setIsMicMuted(true);
    }
  }

  async function muteParticipant(targetParticipantId: string): Promise<void> {
    if (isMutingParticipant) return;
    if (!session) return;
    if (expiredShutdownRef.current || isRoomExpired) return;

    setIsMutingParticipant(targetParticipantId);
    setModerationError(null);

    try {
      await api.muteParticipant(roomId, session.roomToken, {
        target_participant_id: targetParticipantId,
      });
    } catch (error) {
      setModerationError(managementErrorMessage(error));
    } finally {
      setIsMutingParticipant(null);
    }
  }

  function rollbackLanguage(): void {
    const currentSelf = selfRef.current;
    const pending = pendingLanguageRef.current;
    if (!currentSelf || !pending) {
      return;
    }

    setSelfState({
      ...currentSelf,
      language: pending.previous,
    });
    setParticipantsById((current) => ({
      ...current,
      [currentSelf.participant_id]: {
        ...current[currentSelf.participant_id],
        participant_id: currentSelf.participant_id,
        display_name: currentSelf.display_name,
        joined_at: current[currentSelf.participant_id]?.joined_at,
        status: current[currentSelf.participant_id]?.status || "connected",
        language: pending.previous,
      },
    }));
    pendingLanguageRef.current = null;
  }

  const connectionState = deriveConnectionState(gatewayState, livekitState);
  const roomForBrseMode = roomMeta ?? session?.room ?? null;
  const brseEnabled = resolveBrseEnabled(roomForBrseMode);
  const brseOutputMode = resolveBrseOutputMode(roomForBrseMode);
  const brseRoomMode = resolveBrseRoomMode(roomForBrseMode);
  const brseAudioExpected = isBrseAudioExpected(roomForBrseMode);
  const activeParticipants = Object.values(participantsById)
    .filter((participant) =>
      brseEnabled || (participant.kind !== "virtual_brse" && !participant.is_virtual),
    )
    .map((p) => ({
      ...p,
      is_host: p.role === "host" || p.participant_id === hostParticipantId || p.is_host,
    }))
    .sort((left, right) =>
      compareParticipants(left, right, selfState?.participant_id),
    );
  const relayStatuses = [...interpreterStatuses].sort((left, right) =>
    right.updatedAt.localeCompare(left.updatedAt),
  );
  const meetingLanguages = normalizeRoomLanguages(roomMeta ?? session?.room);
  const effectiveExpiresAt =
    roomMeta?.room_id === (session?.roomId ?? roomId)
      ? roomMeta.expires_at
      : session?.room.expires_at ?? null;
  const isCurrentUserHost = !!(selfState && hostParticipantId && selfState.participant_id === hostParticipantId);
  const visibleVideos = brseEnabled
    ? videos
    : videos.filter((feed) => feed.kind !== "virtual_brse" && !feed.isVirtual);
  const visibleTranscripts = brseEnabled
    ? transcripts
    : transcripts.filter((entry) => entry.kind !== "relay");
  const visibleInterpreterStatuses = brseEnabled ? relayStatuses : [];
  const visibleBrseAudioFeeds = isBrseAudioPossible(roomForBrseMode) ? brseAudioFeeds : [];

  return {
    roomMeta,
    brseEnabled,
    brseOutputMode,
    brseRoomMode,
    brseAudioExpected,
    meetingMode:
      roomMeta?.meeting_mode ?? session?.room.meeting_mode ?? null,
    interpreterMode:
      roomMeta?.interpreter_mode ?? session?.room.interpreter_mode ?? null,
    meetingLanguages,
    expiresAt: effectiveExpiresAt,
    isRoomExpired,
    selfState,
    participants: activeParticipants,
    transcripts: visibleTranscripts,
    interpreterStatuses: visibleInterpreterStatuses,
    gatewayState,
    livekitState,
    connectionState,
    videos: visibleVideos,
    humanAudioFeeds,
    brseAudioFeeds: visibleBrseAudioFeeds,
    screenShares,
    connectionError,
    mediaError,
    screenShareError,
    screenShareNotice,
    canShareScreen,
    isScreenSharing,
    isStartingScreenShare,
    isStoppingScreenShare,
    isMicMuted,
    isTogglingMic,
    micToggleError,
    isCameraOff,
    isTogglingCamera,
    cameraToggleError,
    audioInputDevices,
    selectedAudioInputDeviceId,
    isSwitchingAudioInput,
    audioInputError,
    audioOutputDevices,
    selectedAudioOutputDeviceId,
    isSwitchingAudioOutput,
    audioOutputSupported,
    audioOutputError,
    isLeaving,
    isTogglingBrse,
    brseToggleError,
    canToggleBrse:
      !!session
      && !!selfState
      && !isLeaving
      && !isTogglingBrse
      && !isUpdatingRelayMode
      && !isRoomExpired
      && !expiredShutdownRef.current,
    // AI relay mode: room-level, independent of brseEnabled.
    relayMode: brseOutputMode,
    selectableRelayModes: getSelectableRelayModes(roomForBrseMode),
    isUpdatingRelayMode,
    relayModeError,
    canChangeRelayMode:
      !!session
      && !!selfState
      && !isLeaving
      && !isTogglingBrse
      && !isUpdatingRelayMode
      && !isRoomExpired
      && !expiredShutdownRef.current,
    changeRelayMode,
    subscribeRecordingEvents,
    changeLanguage,
    toggleBrseMode,
    toggleMicrophoneMuted,
    toggleCameraEnabled,
    switchAudioInput,
    switchAudioOutput,
    reportAudioOutputApplyError,
    startScreenShare,
    stopScreenShare,
    leaveRoom,
    // Chat
    chatMessages,
    chatError,
    isSendingChat,
    canSendChat:
      !!selfState
      && gatewayState === "connected"
      && !isLeaving
      && !isRoomExpired
      && !expiredShutdownRef.current,
    sendChatMessage,
    // Meeting summary
    meetingSummary,
    summaryIntent,
    isLoadingSummary,
    isGeneratingSummary,
    summaryError,
    summaryErrorSource,
    canRefreshInterimSummary:
      !!session
      && !!selfState
      && !isLeaving
      && !isRoomExpired
      && !expiredShutdownRef.current,
    fetchMeetingSummary,
    refreshInterimSummary,
    prepareFinalSummary,
    // Host
    hostParticipantId,
    isCurrentUserHost: selfRole === "host" || isCurrentUserHost,
    // Roles & room management
    selfRole,
    permissions: permissionsFor(selfRole, permissionsEnforced),
    roomLocked: !!roomMeta?.locked,
    passwordRequired: !!(roomMeta?.password_required ?? session?.room.password_required),
    roomTitle: roomMeta?.title ?? session?.room.title ?? null,
    roleNotice,
    dismissRoleNotice: () => setRoleNotice(null),
    pendingManagementAction,
    removedFromMeeting,
    removeParticipant,
    setParticipantRole,
    setRoomLocked,
    changeRoomPassword,
    removeRoomPassword,
    // Moderation
    isMutedByHost,
    isMutingParticipant,
    moderationError,
    muteParticipant,
  };

  function clearLocalScreenTrack(livekitRoom: ReturnType<typeof createMeetingRoom> | null): void {
    const localTrack = localScreenTrackRef.current;
    const localAudioTrack = localScreenAudioTrackRef.current;
    localScreenTrackCleanupRef.current?.();
    localScreenTrackCleanupRef.current = null;

    if (livekitRoom) {
      try {
        unpublishScreenShareTrack(livekitRoom, localTrack, localAudioTrack);
      } catch {
        localAudioTrack?.stop();
        localTrack?.stop();
      }
    } else {
      localAudioTrack?.stop();
      localTrack?.stop();
    }

    localScreenTrackRef.current = null;
    localScreenAudioTrackRef.current = null;
  }

  function patchSelfScreenShareState(next: {
    active: boolean;
    track_sid?: string | null;
    track_name?: string | null;
    timestamp: string;
  }): void {
    const currentSelf = selfRef.current;
    if (!currentSelf) {
      return;
    }

    setParticipantsById((current) => {
      const existing = current[currentSelf.participant_id];
      if (!existing) {
        return current;
      }

      const screenShare: ScreenShareTrackInfo | null = next.active
        ? {
            active: true,
            source: "screen_share",
            track_sid: next.track_sid ?? undefined,
            track_name: next.track_name ?? undefined,
            started_at: next.timestamp,
          }
        : null;

      return {
        ...current,
        [currentSelf.participant_id]: {
          ...existing,
          is_screen_sharing: next.active,
          screen_share: screenShare,
        },
      };
    });
  }

  function syncLocalScreenShareState(
    participants: ParticipantSnapshot[],
    selfParticipantId: string,
  ): void {
    const selfParticipant = participants.find(
      (participant) => participant.participant_id === selfParticipantId,
    );
    const backendSaysSharing = !!selfParticipant?.is_screen_sharing;
    setIsScreenSharing(backendSaysSharing);
    if (!backendSaysSharing) {
      clearLocalScreenTrack(livekitRoomRef.current);
    }
  }

  function clearBrseRuntimeSurfaces(): void {
    setInterpreterStatuses([]);
    setBrseAudioFeeds([]);
    setVideos((current) =>
      current.filter((feed) => feed.kind !== "virtual_brse" && !feed.isVirtual),
    );
    setParticipantsById((current) => {
      let changed = false;
      const next: Record<string, ParticipantSnapshot> = {};
      for (const [participantId, participant] of Object.entries(current)) {
        if (participant.kind === "virtual_brse" || participant.is_virtual) {
          changed = true;
          continue;
        }
        next[participantId] = participant;
      }
      return changed ? next : current;
    });
    setTranscripts((current) =>
      current.filter((entry) => entry.kind !== "relay"),
    );
  }
}

/** Info shown while sharing: never claims more than the browser actually captures. */
export function buildScreenShareNotice(
  published: Pick<PublishedScreenShare, "audioUnavailable" | "requested" | "actual">,
): string | null {
  const notices: string[] = [];
  if (published.audioUnavailable) {
    notices.push("Screen sharing started, but shared audio isn't available for this source or browser.");
  }
  const requestedFps = published.requested.frameRate;
  const actualFps = published.actual.frameRate;
  if (requestedFps && actualFps && actualFps < requestedFps * 0.9) {
    notices.push(
      `Your browser is capturing at up to ${actualFps} FPS (${requestedFps} FPS requested).`,
    );
  }
  return notices.length > 0 ? notices.join(" ") : null;
}

/** Closing the picker is not an error (null); other failures get a short, generic message. */
export function screenShareStartErrorMessage(error: unknown): string | null {
  if (error instanceof ScreenShareCancelledError) {
    return null;
  }
  if (error instanceof ScreenShareUnsupportedError) {
    return "Screen sharing isn't supported on this device.";
  }
  return "Could not start screen sharing.";
}

function normalizeChatMessages(messages: ChatMessage[]): RoomChatMessage[] {
  return messages
    .map((message) => normalizeChatMessage(message))
    .filter((message): message is RoomChatMessage => message !== null)
    .sort(sortRoomChatMessages);
}

function normalizeMeetingSummaryResponse(
  summary: MeetingSummaryResponse,
  requestedType: MeetingSummaryType,
): MeetingSummaryResponse {
  const summaryType =
    summary.summary_type === "interim" || summary.summary_type === "final"
      ? summary.summary_type
      : requestedType;
  const status = normalizeMeetingSummaryStatus(summary.status, summary.summary_text);
  const keyPoints = preferredStringArray(summary.key_points, summary.highlights);

  return {
    ...summary,
    summary_type: summaryType,
    status,
    summary_text: typeof summary.summary_text === "string" ? summary.summary_text : null,
    key_points: keyPoints,
    highlights: keyPoints,
    decisions: safeStringArray(summary.decisions),
    action_items: normalizeMeetingSummaryActionItems(
      summary.action_items,
      summary.action_item_details,
    ),
    action_item_details: normalizeMeetingSummaryActionItems(
      summary.action_item_details,
      summary.action_items,
    ),
    participant_highlights: normalizeMeetingSummaryParticipants(
      summary.participant_highlights,
      summary.participant_summary,
    ),
    participant_summary: normalizeMeetingSummaryParticipants(
      summary.participant_summary,
      summary.participant_highlights,
    ),
    source_window: isRecord(summary.source_window) ? summary.source_window : {},
    source_stats: isRecord(summary.source_stats) ? summary.source_stats : {},
    error: typeof summary.error === "string" ? summary.error : null,
  };
}

function normalizeMeetingSummaryStatus(
  status: MeetingSummaryResponse["status"],
  summaryText: MeetingSummaryResponse["summary_text"],
): MeetingSummaryStatus {
  if (
    status === "pending"
    || status === "completed"
    || status === "skipped"
    || status === "failed"
  ) {
    return status;
  }

  return typeof summaryText === "string" && summaryText.trim() ? "completed" : "pending";
}

function normalizeMeetingSummaryActionItems(
  items: MeetingSummaryResponse["action_items"],
  fallbackItems?: MeetingSummaryResponse["action_items"],
): MeetingSummaryActionItem[] {
  const sourceItems = Array.isArray(items) && items.length > 0 ? items : fallbackItems;
  if (!Array.isArray(sourceItems)) {
    return [];
  }

  const normalized: MeetingSummaryActionItem[] = [];
  for (const item of sourceItems) {
    if (typeof item === "string") {
      const text = item.trim();
      if (text) {
        normalized.push({ text, owner: null, due: null });
      }
      continue;
    }

    if (!item || typeof item.text !== "string" || !item.text.trim()) {
      continue;
    }

    normalized.push({
      text: item.text.trim(),
      owner: typeof item.owner === "string" ? item.owner : null,
      due: typeof item.due === "string" ? item.due : null,
    });
  }

  return normalized;
}

function normalizeMeetingSummaryParticipants(
  items: MeetingSummaryResponse["participant_summary"],
  fallbackItems?: MeetingSummaryResponse["participant_summary"],
): MeetingSummaryParticipantItem[] {
  const sourceItems = Array.isArray(items) && items.length > 0 ? items : fallbackItems;
  if (!Array.isArray(sourceItems)) {
    return [];
  }

  const normalized: MeetingSummaryParticipantItem[] = [];
  for (const item of sourceItems) {
    if (!item || typeof item.summary !== "string" || !item.summary.trim()) {
      continue;
    }

    normalized.push({
      participant_id: typeof item.participant_id === "string" ? item.participant_id : null,
      display_name: typeof item.display_name === "string" ? item.display_name : null,
      summary: item.summary,
    });
  }

  return normalized;
}

function safeStringArray(items: string[] | null | undefined): string[] {
  if (!Array.isArray(items)) {
    return [];
  }

  return items.filter((item): item is string => typeof item === "string" && !!item.trim());
}

function preferredStringArray(
  preferred: string[] | null | undefined,
  fallback: string[] | null | undefined,
): string[] {
  const preferredItems = safeStringArray(preferred);
  if (preferredItems.length > 0) {
    return preferredItems;
  }
  return safeStringArray(fallback);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function createPendingMeetingSummary(
  roomId: string,
  type: MeetingSummaryType,
  language: MeetingLanguage | null = null,
): MeetingSummaryResponse {
  return {
    room_id: roomId,
    summary_type: type,
    status: "pending",
    created_at: new Date().toISOString(),
    generated_at: null,
    summary_language: language,
    summary_text: null,
    key_points: [],
    highlights: [],
    decisions: [],
    action_items: [],
    action_item_details: [],
    participant_highlights: [],
    participant_summary: [],
    source_window: {},
    source_stats: {},
    error: null,
  };
}

function mapMeetingSummaryFetchError(error: unknown, type: MeetingSummaryType): string {
  if (error instanceof ApiError) {
    if (error.code === "meeting_summary_not_found") {
      return type === "final"
        ? "Final summary is not available yet."
        : "No live summary has been generated yet.";
    }
    if (error.code === "meeting_summary_not_ready") {
      return "Final summary is still being prepared.";
    }
    if (error.code === "meeting_summary_unavailable") {
      return "Meeting summary storage is unavailable right now.";
    }
    if (error.code === "invalid_summary_type") {
      return "Summary type is not supported by this backend.";
    }
    return type === "final"
      ? "Could not load final summary."
      : "Could not load meeting summary.";
  }

  return type === "final"
    ? "Could not load final summary."
    : "Could not load meeting summary.";
}

function mapMeetingSummaryGenerateError(error: unknown, type: MeetingSummaryType): string {
  if (error instanceof ApiError) {
    if (error.code === "meeting_summary_not_ready") {
      return "Final summary is still being prepared.";
    }
    if (error.code === "meeting_summary_unavailable") {
      return "Meeting summary storage is unavailable right now.";
    }
    if (error.code === "invalid_summary_type") {
      return "Summary type is not supported by this backend.";
    }
    return type === "final"
      ? "Could not generate final summary."
      : "Could not generate meeting summary.";
  }

  return type === "final"
    ? "Could not generate final summary."
    : "Could not generate meeting summary.";
}

function normalizeChatMessage(message: ChatMessage): RoomChatMessage | null {
  const participantId = message.participant_id ?? message.sender_id;
  const displayName = message.display_name ?? message.sender_display_name;
  const createdAt = message.created_at ?? message.sent_at;

  if (!message.message_id || !participantId || !displayName || !createdAt) {
    return null;
  }

  return {
    message_id: message.message_id,
    client_event_id: message.client_event_id ?? null,
    participant_id: participantId,
    display_name: displayName,
    text: message.text,
    created_at: createdAt,
    sender_language: message.sender_language ?? message.language ?? null,
    delivery_status: "sent",
    translation_mode: message.translation_mode ?? "original_only",
    translations: message.translations ?? [],
  };
}

function mergeRoomChatMessages(
  current: RoomChatMessage[],
  incoming: RoomChatMessage[],
): RoomChatMessage[] {
  if (incoming.length === 0) {
    return current;
  }

  const merged = new Map<string, RoomChatMessage>();
  const upsert = (message: RoomChatMessage) => {
    let existingKey: string | null = merged.has(message.message_id)
      ? message.message_id
      : null;

    if (!existingKey && message.client_event_id) {
      for (const [key, existing] of merged.entries()) {
        if (existing.client_event_id === message.client_event_id) {
          existingKey = key;
          break;
        }
      }
    }

    if (!existingKey) {
      merged.set(message.message_id, message);
      return;
    }

    const existing = merged.get(existingKey);
    if (!existing) {
      merged.set(message.message_id, message);
      return;
    }

    const next = {
      ...existing,
      ...message,
      delivery_status:
        message.delivery_status
        ?? existing.delivery_status
        ?? "sent",
    };
    if (existingKey !== next.message_id) {
      merged.delete(existingKey);
    }
    merged.set(next.message_id, next);
  };

  for (const message of current) {
    upsert(message);
  }

  for (const message of incoming) {
    upsert(message);
  }

  return Array.from(merged.values()).sort(sortRoomChatMessages);
}

function markRoomChatDeliveryStatus(
  current: RoomChatMessage[],
  messageIdOrClientEventId: string,
  deliveryStatus: RoomChatMessage["delivery_status"],
): RoomChatMessage[] {
  return current.map((message) =>
    message.message_id === messageIdOrClientEventId
      || message.client_event_id === messageIdOrClientEventId
      ? {
          ...message,
          delivery_status: deliveryStatus,
        }
      : message,
  );
}

function createOptimisticChatMessage(
  selfState: SelfState,
  text: string,
  clientEventId: string,
  translationMode: ChatTranslationMode = "original_only",
): RoomChatMessage {
  return {
    message_id: `pending_${clientEventId}`,
    client_event_id: clientEventId,
    participant_id: selfState.participant_id,
    display_name: selfState.display_name,
    text,
    created_at: new Date().toISOString(),
    sender_language: selfState.language,
    delivery_status: "sending",
    translation_mode: translationMode,
    translations: [],
  };
}

function sortRoomChatMessages(left: RoomChatMessage, right: RoomChatMessage): number {
  const byTime = left.created_at.localeCompare(right.created_at);
  if (byTime !== 0) {
    return byTime;
  }

  return left.message_id.localeCompare(right.message_id);
}

function compareParticipants(
  left: ParticipantSnapshot,
  right: ParticipantSnapshot,
  selfParticipantId?: string,
): number {
  if (left.participant_id === selfParticipantId) {
    return -1;
  }
  if (right.participant_id === selfParticipantId) {
    return 1;
  }

  const leftRank = left.kind === "virtual_brse" || left.is_virtual ? 1 : 0;
  const rightRank = right.kind === "virtual_brse" || right.is_virtual ? 1 : 0;
  if (leftRank !== rightRank) {
    return leftRank - rightRank;
  }

  return left.display_name.localeCompare(right.display_name);
}

function countHumanParticipants(participants: ParticipantSnapshot[]): number {
  return participants.filter((participant) => participant.kind !== "virtual_brse" && !participant.is_virtual).length;
}

function parseExpiresAtMs(expiresAt: string | null | undefined): number | null {
  if (!expiresAt) {
    return null;
  }

  const parsed = new Date(expiresAt).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}

function isExpiredAt(expiresAt: string | null | undefined): boolean {
  const expiresAtMs = parseExpiresAtMs(expiresAt);
  return expiresAtMs !== null && Date.now() >= expiresAtMs;
}

function mapParticipants(
  participants: ParticipantSnapshot[],
): Record<string, ParticipantSnapshot> {
  return participants.reduce<Record<string, ParticipantSnapshot>>((acc, item) => {
    acc[item.participant_id] = item;
    return acc;
  }, {});
}

function getLocalTrackDeviceId(track: LocalTrack | null): string | null {
  if (!track || !("mediaStreamTrack" in track)) {
    return null;
  }

  const mediaStreamTrack = (track as { mediaStreamTrack?: MediaStreamTrack }).mediaStreamTrack;
  const deviceId = mediaStreamTrack?.getSettings().deviceId;
  return deviceId ?? null;
}

function deriveConnectionState(
  gatewayState: GatewayConnectionState,
  livekitState: GatewayConnectionState,
): GatewayConnectionState {
  if (gatewayState === "reconnecting" || livekitState === "reconnecting") {
    return "reconnecting";
  }

  if (gatewayState === "connected" && livekitState === "connected") {
    return "connected";
  }

  if (gatewayState === "disconnected" || livekitState === "disconnected") {
    return "disconnected";
  }

  if (gatewayState === "idle" && livekitState === "idle") {
    return "idle";
  }

  return "connecting";
}

function formatFatalCloseMessage(code: number, reason: string): string {
  if (code === 4410) {
    return "This meeting has ended.";
  }
  if (code === 4404) {
    return "Room no longer exists.";
  }
  if (code === 4401) {
    return "Session expired. Rejoin the room to continue.";
  }
  if (code === 4403) {
    return "Session is no longer valid for this room.";
  }
  return reason;
}

function managementErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return PERMISSION_DENIED_MESSAGE;
    if (error.code === "participant_not_found") return "That person is no longer in the meeting.";
    if (error.code === "room_expired") return "This meeting has ended.";
    return error.message || "Couldn't complete that action. Try again.";
  }
  return "Couldn't complete that action. Try again.";
}
