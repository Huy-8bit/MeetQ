import { startTransition, useEffect, useRef, useState } from "react";
import { api, leaveRoomBestEffort, ApiError } from "../../lib/api";
import { setRoomAudioOutputDevice } from "../../lib/audioOutput";
import {
  formatMeetingLanguagePair,
  resolveMeetingLanguages,
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
  publishLocalCameraTrack,
  publishScreenShareTrack,
  publishLocalMedia,
  setLocalCameraMuted,
  setLocalMicrophoneMuted,
  supportsAudioOutputSelection,
  switchLocalMicrophoneTrack,
  unpublishScreenShareTrack,
} from "../../lib/livekit";
import {
  GatewaySocket,
  GatewaySocketCancelledError,
  releaseGatewaySocket,
  retainGatewaySocket,
} from "../../lib/ws";
import type {
  ChatMessage,
  RoomChatMessage,
  Language,
  MeetingLanguage,
  ParticipantSnapshot,
  RoomSnapshotResponse,
  ScreenShareTrackInfo,
} from "../../types/api";
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
  ParticipantUpdatedEvent,
  RoomBrseUpdatedEvent,
  RoomExpiredEvent,
  RoomHostChangedEvent,
  RoomSnapshotEvent,
  ScreenShareStartedEvent,
  ScreenShareStoppedEvent,
  ServerEvent,
  TranscriptFinalEvent,
  TranscriptPartialEvent,
} from "../../types/ws";
import type { RoomSession } from "../../state/session";
import { type LocalTrack, type LocalVideoTrack } from "livekit-client";
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

  // ─── Chat state ──────────────────────────────────────────────────────────────
  const [chatMessages, setChatMessages] = useState<RoomChatMessage[]>(() =>
    normalizeChatMessages(session?.snapshot.recent_messages ?? initialRoom?.recent_messages ?? []),
  );
  const [chatError, setChatError] = useState<string | null>(null);
  const [isSendingChat, setIsSendingChat] = useState(false);

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
  const localScreenTrackCleanupRef = useRef<(() => void) | null>(null);
  const stoppingScreenShareRef = useRef(false);
  const isScreenSharingRef = useRef(false);
  const selectedAudioInputDeviceIdRef = useRef(selectedAudioInputDeviceId);
  const selectedAudioOutputDeviceIdRef = useRef(selectedAudioOutputDeviceId);
  const isSwitchingAudioInputRef = useRef(isSwitchingAudioInput);
  const isMutedByHostRef = useRef(false);
  const pendingChatEventIdsRef = useRef<Set<string>>(new Set());
  const brseEnabledRef = useRef(resolveBrseEnabled(initialRoom?.room ?? session?.room ?? null));

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
          (entry) => initialRoom.room.brse_enabled !== false || entry.kind !== "relay",
        ),
      );
    });
  }, [initialRoom, session]);

  const sessionKey = session?.sessionKey ?? null;
  const livekitUrl = session?.livekit.url ?? null;
  const livekitToken = session?.livekit.token ?? null;

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

    setRoomMeta((current) => ({
      room_id: current?.room_id || session.roomId,
      state: session.room.state,
      created_at: current?.created_at || session.room.created_at,
      expires_at: current?.expires_at || session.room.expires_at,
      brse_enabled: session.room.brse_enabled ?? current?.brse_enabled,
      participant_limit: session.room.participant_limit,
      supported_languages: session.room.supported_languages,
      meeting_languages:
        resolveMeetingLanguages(session.room.meeting_languages, session.room.supported_languages),
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
        ).filter((entry) => session.room.brse_enabled !== false || entry.kind !== "relay"),
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
      setBrseAudioFeeds(media.brseAudio);
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
    roomMeta?.meeting_mode,
    roomMeta?.interpreter_mode,
    roomMeta?.audio_routing?.model,
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

  async function startScreenShare(): Promise<void> {
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

    try {
      const published = await publishScreenShareTrack(livekitRoom);
      localScreenTrackRef.current = published.track;

      const handleTrackEnded = () => {
        void stopScreenShare({
          reason: "track_ended",
          notifyBackend: true,
          signalWsFallback: false,
        });
      };

      published.track.mediaStreamTrack.addEventListener("ended", handleTrackEnded);
      localScreenTrackCleanupRef.current = () => {
        published.track.mediaStreamTrack.removeEventListener("ended", handleTrackEnded);
      };

      const response = await api.startScreenShare(roomId, session.roomToken, {
        track_sid: published.trackSid,
        track_name: published.trackName,
        source: "screen_share",
      });

      setIsScreenSharing(response.active);
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
      setScreenShareError(
        error instanceof Error ? error.message : "Failed to start screen sharing.",
      );
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

    const reason = options?.reason ?? "manual_stop";
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

    if (reason === "track_ended") {
      setScreenShareError("Screen sharing ended from browser controls.");
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
    if (!session || expiredShutdownRef.current || isRoomExpired || isTogglingBrse || isLeaving) {
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

      setRoomMeta((current) => ({
        ...(current ?? {}),
        ...nextRoom,
        room_id: nextRoom.room_id || current?.room_id || roomId,
        created_at: nextRoom.created_at || current?.created_at || session.room.created_at,
        expires_at: nextRoom.expires_at || current?.expires_at || session.room.expires_at,
        participant_count:
          current?.participant_count ?? countHumanParticipants(session.snapshot.participants),
      }));
      brseEnabledRef.current = nextRoom.brse_enabled ?? nextEnabled;

      if (!brseEnabledRef.current) {
        clearBrseRuntimeSurfaces();
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

    const meetingLanguages = resolveMeetingLanguages(
      roomMeta?.meeting_languages,
      roomMeta?.supported_languages,
    );
    if (!meetingLanguages.includes(nextLanguage as MeetingLanguage)) {
      setConnectionError(
        meetingLanguages.length === 2
          ? `Language must match the room meeting languages: ${formatMeetingLanguagePair(meetingLanguages)}.`
          : "Room meeting language pair is unavailable. Reload room snapshot or ask the host to recreate the room.",
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

    setSelfState(event.payload.self);
    setParticipantsById(mapParticipants(event.payload.participants));
    syncLocalScreenShareState(event.payload.participants, event.payload.self.participant_id);
    setRoomMeta((current) => ({
      room_id: current?.room_id || roomId,
      state: event.payload.room.state,
      created_at: current?.created_at || new Date().toISOString(),
      expires_at: event.payload.room.expires_at ?? current?.expires_at ?? new Date().toISOString(),
      brse_enabled: event.payload.room.brse_enabled ?? current?.brse_enabled,
      participant_limit: event.payload.room.participant_limit,
      supported_languages: event.payload.room.supported_languages,
      meeting_languages: resolveMeetingLanguages(
        event.payload.room.meeting_languages,
        event.payload.room.supported_languages,
      ),
      meeting_mode: event.payload.room.meeting_mode ?? current?.meeting_mode,
      interpreter_mode:
        event.payload.room.interpreter_mode ?? current?.interpreter_mode,
      audio_routing:
        event.payload.room.audio_routing ?? current?.audio_routing,
      participant_count: countHumanParticipants(event.payload.participants),
    }));

    if (event.payload.room.brse_enabled === false) {
      clearBrseRuntimeSurfaces();
    }

    startTransition(() => {
      setTranscripts((current) =>
        mergeTranscriptCollections(
          current,
          hydrateTranscriptEntries(
            event.payload.recent_transcripts,
            event.payload.self.language,
          ).filter((entry) => event.payload.room.brse_enabled !== false || entry.kind !== "relay"),
        ),
      );
    });

    // Host state from snapshot
    const snapshotHostId = event.payload.host_participant_id ?? null;
    const hostFromParticipant = event.payload.participants.find((p) => p.is_host);
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
    if (event.payload.is_host) {
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
    setRoomMeta((current) =>
      current
        ? {
            ...current,
            brse_enabled: nextEnabled,
            meeting_mode: nextEnabled ? "brse_relay" : "direct_translation",
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
      const meetingLanguages = resolveMeetingLanguages(
        roomMetaRef.current?.meeting_languages,
        roomMetaRef.current?.supported_languages,
      );
      setConnectionError(
        meetingLanguages.length === 2
          ? `Language must match the room meeting languages: ${formatMeetingLanguagePair(meetingLanguages)}.`
          : "Language must match the room meeting languages for this room.",
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

  async function sendChatMessage(text: string): Promise<boolean> {
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
      const clientEventId = gateway.sendChatMessage(trimmed);
      pendingChatEventIdsRef.current.add(clientEventId);
      const optimisticMessage = createOptimisticChatMessage(
        currentSelf,
        trimmed,
        clientEventId,
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
      // Try REST first
      try {
        await api.muteParticipant(roomId, session.roomToken, {
          target_participant_id: targetParticipantId,
        });
      } catch {
        // Fallback to WS
        gatewayRef.current?.sendMuteParticipant(targetParticipantId);
      }
    } catch (error) {
      setModerationError(
        error instanceof Error ? error.message : "Failed to mute participant.",
      );
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
  const brseEnabled = resolveBrseEnabled(roomMeta ?? session?.room ?? null);
  const activeParticipants = Object.values(participantsById)
    .filter((participant) =>
      brseEnabled || (participant.kind !== "virtual_brse" && !participant.is_virtual),
    )
    .map((p) => ({
      ...p,
      is_host: p.participant_id === hostParticipantId || p.is_host,
    }))
    .sort((left, right) =>
      compareParticipants(left, right, selfState?.participant_id),
    );
  const relayStatuses = [...interpreterStatuses].sort((left, right) =>
    right.updatedAt.localeCompare(left.updatedAt),
  );
  const meetingLanguages = resolveMeetingLanguages(
    roomMeta?.meeting_languages,
    roomMeta?.supported_languages,
  );
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
  const visibleBrseAudioFeeds = brseEnabled ? brseAudioFeeds : [];

  return {
    roomMeta,
    brseEnabled,
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
      && !isRoomExpired
      && !expiredShutdownRef.current,
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
    // Host
    hostParticipantId,
    isCurrentUserHost,
    // Moderation
    isMutedByHost,
    isMutingParticipant,
    moderationError,
    muteParticipant,
  };

  function clearLocalScreenTrack(livekitRoom: ReturnType<typeof createMeetingRoom> | null): void {
    const localTrack = localScreenTrackRef.current;
    localScreenTrackCleanupRef.current?.();
    localScreenTrackCleanupRef.current = null;

    if (livekitRoom) {
      try {
        unpublishScreenShareTrack(livekitRoom, localTrack);
      } catch {
        localTrack?.stop();
      }
    } else if (localTrack) {
      localTrack.stop();
    }

    localScreenTrackRef.current = null;
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

function normalizeChatMessages(messages: ChatMessage[]): RoomChatMessage[] {
  return messages
    .map((message) => normalizeChatMessage(message))
    .filter((message): message is RoomChatMessage => message !== null)
    .sort(sortRoomChatMessages);
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

function resolveBrseEnabled(
  room: Pick<RoomSnapshotResponse["room"], "brse_enabled" | "meeting_mode"> | null,
): boolean {
  if (typeof room?.brse_enabled === "boolean") {
    return room.brse_enabled;
  }

  return room?.meeting_mode === "brse_relay";
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
