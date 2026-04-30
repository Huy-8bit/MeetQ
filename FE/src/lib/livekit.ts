import {
  ConnectionState,
  Room,
  RoomEvent,
  Track,
  createLocalTracks,
  type LocalTrack,
  type LocalTrackPublication,
  type LocalVideoTrack,
  type RemoteAudioTrack,
  type RemoteParticipant,
  type RemoteTrackPublication,
  type RemoteVideoTrack,
} from "livekit-client";
import type {
  AudioRouting,
  Language,
  ParticipantSnapshot,
} from "../types/api";
import type {
  GatewayConnectionState,
  InterpreterAudioFeed,
  InterpreterTrackInfo,
  SameLanguagePassthroughAudioFeed,
  VideoFeed,
} from "../types/livekit";

export function createMeetingRoom(): Room {
  return new Room({
    adaptiveStream: true,
    dynacast: true,
  });
}

export async function connectLiveKit(room: Room, url: string, token: string) {
  await room.connect(url, token, {
    autoSubscribe: true,
  });
}

export async function publishLocalMedia(room: Room): Promise<LocalTrack[]> {
  assertMediaDevicesSupported();

  const tracks = await createLocalTracks({
    audio: true,
    video: true,
  });

  await Promise.all(
    tracks.map((track) => room.localParticipant.publishTrack(track)),
  );

  return tracks;
}

function assertMediaDevicesSupported(): void {
  const hasMediaDevices =
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === "function";

  if (hasMediaDevices) {
    return;
  }

  const isSecureContextValue =
    typeof window !== "undefined" ? window.isSecureContext : false;

  if (!isSecureContextValue) {
    throw new Error(
      "Microphone/camera is unavailable in insecure context. Use HTTPS (or localhost) for this web app.",
    );
  }

  throw new Error(
    "This browser/environment does not support navigator.mediaDevices.getUserMedia.",
  );
}

export function disconnectRoom(room: Room | null): void {
  if (!room) {
    return;
  }

  room.localParticipant.trackPublications.forEach((publication) => {
    publication.track?.stop();
    if (publication.track) {
      room.localParticipant.unpublishTrack(publication.track as LocalTrack, true);
    }
  });

  room.disconnect();
}

export function parseInterpreterTrackName(
  trackName: string,
): InterpreterTrackInfo | null {
  const parts = trackName.split("::");
  if (parts.length !== 5 || parts[0] !== "interp") {
    return null;
  }

  const [, speakerId, listenerId, srcLang, tgtLang] = parts;
  if (!isLanguage(srcLang) || !isLanguage(tgtLang)) {
    return null;
  }

  return {
    speakerId,
    listenerId,
    srcLang,
    tgtLang,
    rawName: trackName,
  };
}

export function isInterpreterParticipant(identity: string): boolean {
  return identity.startsWith("interp::");
}

export function buildMediaSnapshot(args: {
  room: Room;
  selfParticipantId: string;
  selfDisplayName: string;
  selfLanguage: Language;
  audioRouting?: AudioRouting;
  participantsById: Record<string, ParticipantSnapshot>;
}): {
  videos: VideoFeed[];
  sameLanguagePassthroughAudio: SameLanguagePassthroughAudioFeed[];
  interpreterAudio: InterpreterAudioFeed[];
  localVideoTrack: LocalVideoTrack | null;
} {
  const {
    room,
    selfParticipantId,
    selfDisplayName,
    selfLanguage,
    audioRouting,
    participantsById,
  } = args;
  const videos: VideoFeed[] = [];
  const sameLanguagePassthroughAudio: SameLanguagePassthroughAudioFeed[] = [];
  const interpreterAudio: InterpreterAudioFeed[] = [];
  const sameLanguagePolicy =
    audioRouting?.same_language_policy ?? "human_passthrough";

  let localVideoTrack: LocalVideoTrack | null = null;

  room.localParticipant.trackPublications.forEach((publication) => {
    if (publication.source === Track.Source.Camera && publication.track) {
      localVideoTrack = publication.track as LocalVideoTrack;
    }
  });

  videos.push({
    participantId: selfParticipantId,
    displayName: selfDisplayName,
    isLocal: true,
    language: participantsById[selfParticipantId]?.language,
    track: localVideoTrack,
  });

  room.remoteParticipants.forEach((participant) => {
    if (isInterpreterParticipant(participant.identity)) {
      collectInterpreterTracks(participant, interpreterAudio);
      return;
    }

    const participantId = participant.identity;
    const snapshot = participantsById[participantId];
    let videoTrack: RemoteVideoTrack | null = null;

    participant.trackPublications.forEach((publication) => {
      if (
        publication.source === Track.Source.Camera &&
        publication.track &&
        publication.track.kind === Track.Kind.Video
      ) {
        videoTrack = publication.track as RemoteVideoTrack;
      }

      if (
        publication.source === Track.Source.Microphone &&
        publication.track &&
        publication.track.kind === Track.Kind.Audio
      ) {
        const speakerLanguage = snapshot?.language;
        if (
          speakerLanguage &&
          speakerLanguage === selfLanguage &&
          sameLanguagePolicy === "human_passthrough"
        ) {
          sameLanguagePassthroughAudio.push({
            participantId,
            displayName:
              snapshot?.display_name || participant.name || participantId,
            language: speakerLanguage,
            policy: sameLanguagePolicy,
            track: publication.track as RemoteAudioTrack,
          });
        }
      }
    });

    videos.push({
      participantId,
      displayName: snapshot?.display_name || participant.name || participantId,
      isLocal: false,
      language: snapshot?.language,
      track: videoTrack,
    });
  });

  return {
    videos,
    sameLanguagePassthroughAudio,
    interpreterAudio,
    localVideoTrack,
  };
}

export function mapLiveKitConnectionState(
  connectionState: ConnectionState,
): GatewayConnectionState {
  switch (connectionState) {
    case ConnectionState.Connected:
      return "connected";
    case ConnectionState.Connecting:
      return "connecting";
    case ConnectionState.Reconnecting:
      return "reconnecting";
    case ConnectionState.Disconnected:
    default:
      return "disconnected";
  }
}

export function bindRoomRefresh(
  room: Room,
  refresh: () => void,
  onConnectionState: (state: GatewayConnectionState) => void,
): () => void {
  const refreshEvents = [
    RoomEvent.TrackSubscribed,
    RoomEvent.TrackUnsubscribed,
    RoomEvent.TrackPublished,
    RoomEvent.TrackUnpublished,
    RoomEvent.ParticipantConnected,
    RoomEvent.ParticipantDisconnected,
    RoomEvent.LocalTrackPublished,
    RoomEvent.LocalTrackUnpublished,
  ] as const;

  refreshEvents.forEach((eventName) => {
    room.on(eventName, refresh);
  });

  room.on(RoomEvent.ConnectionStateChanged, (state) => {
    onConnectionState(mapLiveKitConnectionState(state));
    refresh();
  });

  return () => {
    refreshEvents.forEach((eventName) => {
      room.off(eventName, refresh);
    });
    room.removeAllListeners();
  };
}

function collectInterpreterTracks(
  participant: RemoteParticipant,
  output: InterpreterAudioFeed[],
): void {
  participant.trackPublications.forEach((publication) => {
    const audioTrack = getRemoteAudioTrack(publication);
    if (!audioTrack) {
      return;
    }

    const trackName = publication.trackName;
    const info = parseInterpreterTrackName(trackName);
    if (!info) {
      return;
    }

    output.push({
      trackSid: publication.trackSid,
      track: audioTrack,
      info,
    });
  });
}

function getRemoteAudioTrack(
  publication: RemoteTrackPublication,
): RemoteAudioTrack | null {
  if (!publication.track || publication.track.kind !== Track.Kind.Audio) {
    return null;
  }

  return publication.track as RemoteAudioTrack;
}

function isLanguage(input: string): input is Language {
  return input === "vi" || input === "en" || input === "ja";
}
