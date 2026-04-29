import { startTransition, useEffect, useRef, useState } from "react";
import { api, buildApiUrl, ApiError } from "../../lib/api";
import {
  bindRoomRefresh,
  buildMediaSnapshot,
  connectLiveKit,
  createMeetingRoom,
  disconnectRoom,
  publishLocalMedia,
} from "../../lib/livekit";
import {
  GatewaySocket,
  GatewaySocketCancelledError,
  releaseGatewaySocket,
  retainGatewaySocket,
} from "../../lib/ws";
import type {
  Language,
  ParticipantSnapshot,
  RoomSnapshotResponse,
} from "../../types/api";
import type {
  GatewayConnectionState,
  InterpreterAudioFeed,
  RemoteAudioFeed,
  VideoFeed,
} from "../../types/livekit";
import type {
  ErrorEvent,
  ParticipantJoinedEvent,
  ParticipantLeftEvent,
  ParticipantUpdatedEvent,
  RoomSnapshotEvent,
  ServerEvent,
  TranscriptFinalEvent,
  TranscriptPartialEvent,
} from "../../types/ws";
import type { RoomSession } from "../../state/session";
import {
  hydrateTranscriptEntries,
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
  const [humanAudioFeeds, setHumanAudioFeeds] = useState<RemoteAudioFeed[]>([]);
  const [interpreterAudioFeeds, setInterpreterAudioFeeds] = useState<
    InterpreterAudioFeed[]
  >([]);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [isLeaving, setIsLeaving] = useState(false);

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
  const sessionInvalidatedRef = useRef(onSessionInvalidated);

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
    if (!initialRoom || session) {
      return;
    }

    setRoomMeta(initialRoom.room);
    setParticipantsById(mapParticipants(initialRoom.participants));
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
      setSelfState(null);
      setGatewayState("idle");
      setLivekitState("idle");
      setVideos([]);
      setHumanAudioFeeds([]);
      setInterpreterAudioFeeds([]);
      setInterpreterStatuses([]);
      setConnectionError(null);
      setMediaError(null);
      setIsLeaving(false);
      return;
    }

    hasLeftRef.current = false;
    setConnectionError(null);
    setMediaError(null);
    setGatewayState("connecting");
    setLivekitState("connecting");
    setRoomMeta((current) => ({
      room_id: current?.room_id || session.roomId,
      state: session.room.state,
      created_at: current?.created_at || session.room.created_at,
      expires_at: current?.expires_at || session.room.expires_at,
      participant_limit: session.room.participant_limit,
      supported_languages: session.room.supported_languages,
      participant_count: session.snapshot.participants.length,
    }));
    setSelfState({
      participant_id: session.participant.participant_id,
      session_id: session.participant.session_id,
      display_name: session.participant.display_name,
      language: session.participant.language,
    });
    setParticipantsById(mapParticipants(session.snapshot.participants));
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
        selfLanguage: currentSelf.language,
        participantsById: participantsRef.current,
      });

      setVideos(media.videos);
      setHumanAudioFeeds(media.humanAudio);
      setInterpreterAudioFeeds(
        media.interpreterAudio.filter(
          (feed) => feed.info.listenerId === currentSelf.participant_id,
        ),
      );
    };

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

        handleGatewayEvent(event);
      },
      onStateChange: (state) => {
        if (!disposed) {
          setGatewayState(state);
        }
      },
      onFatalClose: (code, reason) => {
        if (disposed) {
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
        } catch (error) {
          setMediaError(
            error instanceof Error
              ? error.message
              : "Microphone or camera permission was denied.",
          );
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
      unbindRoom();
      unsubscribeGateway();
      releaseGatewaySocket(session.sessionKey);
      gatewayRef.current = null;
      disconnectRoom(livekitRoom);
      livekitRoomRef.current = null;
    };
  }, [
    roomId,
    sessionKey,
    livekitUrl,
    livekitToken,
  ]);

  useEffect(() => {
    if (!session) {
      return;
    }

    const leaveUrl = buildApiUrl(`/api/rooms/${roomId}/leave`);
    const handlePageHide = () => {
      if (hasLeftRef.current) {
        return;
      }

      void fetch(leaveUrl, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${session.roomToken}`,
        },
        keepalive: true,
      }).catch(() => undefined);
    };

    window.addEventListener("pagehide", handlePageHide);
    return () => {
      window.removeEventListener("pagehide", handlePageHide);
    };
  }, [roomId, session]);

  async function leaveRoom(): Promise<void> {
    if (!session || isLeaving) {
      return;
    }

    setIsLeaving(true);
    hasLeftRef.current = true;

    try {
      await api.leaveRoom(roomId, session.roomToken);
    } catch (error) {
      if (!(error instanceof ApiError)) {
        console.error("Failed to leave room", error);
      }
    } finally {
      gatewayRef.current?.disconnect();
      disconnectRoom(livekitRoomRef.current);
      sessionInvalidatedRef.current();
      setIsLeaving(false);
    }
  }

  function changeLanguage(nextLanguage: Language): void {
    const currentSelf = selfRef.current;
    if (!currentSelf || currentSelf.language === nextLanguage) {
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
      case "transcript.partial":
      case "transcript.final":
        applyTranscriptEvent(event);
        return;
      case "interpreter.status":
        applyInterpreterStatus(event);
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
    setRoomMeta((current) => ({
      room_id: current?.room_id || roomId,
      state: event.payload.room.state,
      created_at: current?.created_at || new Date().toISOString(),
      expires_at: current?.expires_at || new Date().toISOString(),
      participant_limit: event.payload.room.participant_limit,
      supported_languages: event.payload.room.supported_languages,
      participant_count: event.payload.participants.length,
    }));

    startTransition(() => {
      setTranscripts((current) =>
        current.length > 0
          ? current
          : hydrateTranscriptEntries(
              event.payload.recent_transcripts,
              event.payload.self.language,
            ),
      );
    });
  }

  function applyParticipantJoined(event: ParticipantJoinedEvent): void {
    setParticipantsById((current) => ({
      ...current,
      [event.payload.participant_id]: {
        participant_id: event.payload.participant_id,
        display_name: event.payload.display_name,
        language: event.payload.language,
        status: event.payload.status,
        joined_at: event.payload.joined_at,
      },
    }));
    setRoomMeta((current) =>
      current
        ? {
            ...current,
            participant_count: current.participant_count + 1,
          }
        : current,
    );
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
          joined_at: existing?.joined_at,
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
    }
  }

  function applyParticipantLeft(event: ParticipantLeftEvent): void {
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
            participant_count: Math.max(0, current.participant_count - 1),
          }
        : current,
    );
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
    if (pendingLanguageRef.current) {
      rollbackLanguage();
    }

    setConnectionError(event.payload.message);
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
  const activeParticipants = Object.values(participantsById).sort((left, right) =>
    left.display_name.localeCompare(right.display_name),
  );
  const relevantInterpreterStatuses = interpreterStatuses.filter((item) =>
    selfState ? item.targetLanguage === selfState.language : true,
  );

  return {
    roomMeta,
    selfState,
    participants: activeParticipants,
    transcripts,
    interpreterStatuses: relevantInterpreterStatuses,
    gatewayState,
    livekitState,
    connectionState,
    videos,
    humanAudioFeeds,
    interpreterAudioFeeds,
    connectionError,
    mediaError,
    isLeaving,
    changeLanguage,
    leaveRoom,
  };
}

function mapParticipants(
  participants: ParticipantSnapshot[],
): Record<string, ParticipantSnapshot> {
  return participants.reduce<Record<string, ParticipantSnapshot>>((acc, item) => {
    acc[item.participant_id] = item;
    return acc;
  }, {});
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
