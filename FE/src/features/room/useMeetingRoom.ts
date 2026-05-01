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
  getLocalMicrophoneTrack,
  isMicrophoneMuted,
  publishScreenShareTrack,
  publishLocalMedia,
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
}

interface SelfState {
  participant_id: string;
  session_id: string;
  display_name: string;
  language: Language;
}

export function useMeetingRoom({
  roomId,
  initialRoom,
  session,
  onSessionInvalidated,
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
    ),
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
  const sessionInvalidatedRef = useRef(onSessionInvalidated);
  const refreshMediaRef = useRef<(() => void) | null>(null);
  const audioRoutingRef = useRef(session?.room.audio_routing ?? roomMeta?.audio_routing);
  const roomMetaRef = useRef(roomMeta);
  const localAudioTrackRef = useRef<LocalTrack | null>(null);
  const localScreenTrackRef = useRef<LocalVideoTrack | null>(null);
  const localScreenTrackCleanupRef = useRef<(() => void) | null>(null);
  const stoppingScreenShareRef = useRef(false);
  const isScreenSharingRef = useRef(false);
  const selectedAudioInputDeviceIdRef = useRef(selectedAudioInputDeviceId);
  const selectedAudioOutputDeviceIdRef = useRef(selectedAudioOutputDeviceId);
  const isSwitchingAudioInputRef = useRef(isSwitchingAudioInput);
  const isMutedByHostRef = useRef(false);
  const pendingChatEventIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    sessionInvalidatedRef.current = onSessionInvalidated;
  }, [onSessionInvalidated]);

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
  }, [roomMeta]);

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
        hydrateTranscriptEntries(initialRoom.recent_transcripts, null),
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
      localAudioTrackRef.current = null;
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
      setChatMessages([]);
      setChatError(null);
      setIsSendingChat(false);
      pendingChatEventIdsRef.current.clear();
      setHostParticipantId(null);
      setIsMutedByHost(false);
      setIsMutingParticipant(null);
      setModerationError(null);
      void setRoomAudioOutputDevice("").catch(() => undefined);
      refreshMediaRef.current = null;
      return;
    }

    hasLeftRef.current = false;
    hasSentLeaveRef.current = false;
    manualShutdownRef.current = false;
    setConnectionError(null);
    setMediaError(null);
    setChatError(null);
    setIsSendingChat(false);
    pendingChatEventIdsRef.current.clear();
    setAudioOutputSupported(supportsAudioOutputSelection());
    setGatewayState("connecting");
    setLivekitState("connecting");
    setRoomMeta((current) => ({
      room_id: current?.room_id || session.roomId,
      state: session.room.state,
      created_at: current?.created_at || session.room.created_at,
      expires_at: current?.expires_at || session.room.expires_at,
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
        ),
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
      localAudioTrackRef.current = currentMicTrack;
      setIsMicMuted(isMicrophoneMuted(currentMicTrack));
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

        if (manualShutdownRef.current) {
          return;
        }

        handleGatewayEvent(event);
      },
      onStateChange: (state) => {
        if (!disposed) {
          setGatewayState(state);
        }
      },
      onFatalClose: (code, reason) => {
        if (disposed || manualShutdownRef.current) {
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
      if (!disposed) {
        setLivekitState(state);
      }
    });
    void (async () => {
      try {
        await gateway.connect();
        if (disposed) {
          return;
        }

        await connectLiveKit(livekitRoom, session.livekit.url, session.livekit.token);
        if (disposed) {
          return;
        }

        refreshMedia();

        try {
          await publishLocalMedia(livekitRoom);
          localAudioTrackRef.current = getLocalMicrophoneTrack(livekitRoom);
          setIsMicMuted(isMicrophoneMuted(localAudioTrackRef.current));
          await refreshAudioDevices();
        } catch (error) {
          setMediaError(
            error instanceof Error
              ? error.message
              : "Microphone or camera permission was denied.",
          );
          await refreshAudioDevices();
        }

        refreshMedia();
      } catch (error) {
        if (disposed || error instanceof GatewaySocketCancelledError) {
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
    refreshMediaRef.current?.();
  }, [
    participantsById,
    selfState?.participant_id,
    selfState?.language,
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
      const lkRoom = livekitRoomRef.current;
      livekitRoomRef.current = null;
      clearLocalScreenTrack(lkRoom);
      disconnectRoom(lkRoom);
      sessionInvalidatedRef.current();
      setIsLeaving(false);
    }
  }

  async function startScreenShare(): Promise<void> {
    if (!session || isStartingScreenShare || isStoppingScreenShare || isScreenSharing) {
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
    if (isTogglingMic) {
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

  async function switchAudioInput(deviceId: string): Promise<void> {
    if (isSwitchingAudioInput || !deviceId) {
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
    if (isSwitchingAudioOutput || !deviceId) {
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

  function applyRoomSnapshot(event: RoomSnapshotEvent): void {
    setSelfState(event.payload.self);
    setParticipantsById(mapParticipants(event.payload.participants));
    syncLocalScreenShareState(event.payload.participants, event.payload.self.participant_id);
    setRoomMeta((current) => ({
      room_id: current?.room_id || roomId,
      state: event.payload.room.state,
      created_at: current?.created_at || new Date().toISOString(),
      expires_at: current?.expires_at || new Date().toISOString(),
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

    startTransition(() => {
      setTranscripts((current) =>
        mergeTranscriptCollections(
          current,
          hydrateTranscriptEntries(
            event.payload.recent_transcripts,
            event.payload.self.language,
          ),
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

  function applyTranscriptEvent(
    event: TranscriptPartialEvent | TranscriptFinalEvent,
  ): void {
    startTransition(() => {
      setTranscripts((current) =>
        upsertTranscriptEntry(current, event.payload, event.sent_at),
      );
    });
  }

  function applyInterpreterStatus(event: ServerEvent & { type: "interpreter.status" }): void {
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
    if (!trimmed || isSendingChat) {
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
  const activeParticipants = Object.values(participantsById)
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
  const isCurrentUserHost = !!(selfState && hostParticipantId && selfState.participant_id === hostParticipantId);

  return {
    roomMeta,
    meetingMode:
      roomMeta?.meeting_mode ?? session?.room.meeting_mode ?? null,
    interpreterMode:
      roomMeta?.interpreter_mode ?? session?.room.interpreter_mode ?? null,
    meetingLanguages,
    selfState,
    participants: activeParticipants,
    transcripts,
    interpreterStatuses: relayStatuses,
    gatewayState,
    livekitState,
    connectionState,
    videos,
    humanAudioFeeds,
    brseAudioFeeds,
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
    changeLanguage,
    toggleMicrophoneMuted,
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
    canSendChat: !!selfState && gatewayState === "connected" && !isLeaving,
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
