import {
  AudioPresets,
  ConnectionState,
  LocalTrackPublication,
  Room,
  RoomEvent,
  Track,
  VideoPreset,
  VideoQuality,
  createLocalTracks,
  LocalAudioTrack,
  LocalVideoTrack,
  type LocalTrack,
  type AudioCaptureOptions,
  type RemoteAudioTrack,
  type RemoteParticipant,
  type RemoteTrackPublication,
  type RemoteVideoTrack,
  type TrackPublishOptions,
} from "livekit-client";
import type {
  AudioRouting,
  ParticipantSnapshot,
  ParticipantKind,
} from "../types/api";
import { isMeetingLanguage } from "./languages";
import type {
  AudioDeviceOption,
  BrseAudioFeed,
  BrseTrackInfo,
  GatewayConnectionState,
  HumanAudioFeed,
  ScreenShareFeed,
  VideoFeed,
} from "../types/livekit";
import { resolveLiveKitUrl } from "./urls";

const BRSE_LIVEKIT_IDENTITY_PREFIX = "interp::brse_ai";
const DEFAULT_BRSE_PARTICIPANT_ID = "brse_ai";
/**
 * Screen-share profiles. Capture asks for 1080p at the profile's frame rate (never
 * more: `max` caps it, and smaller sources are not upscaled). Each profile has its own
 * encoding; viewers on weak links get the simulcast layer via adaptive stream/dynacast.
 *
 * | profile | capture         | top layer          | low layer        | content hint | degradation        |
 * | detail  | 1920×1080 ≤30fps | 5 Mbps, 30 fps     | 720p15 @ 1.5 Mbps | detail       | maintain-resolution |
 * | motion  | 1920×1080 ≤60fps | 8 Mbps, 60 fps     | 720p30 @ 2.5 Mbps | motion       | maintain-framerate  |
 */
export type ScreenShareQuality = "detail" | "motion";

interface ScreenShareProfile {
  width: number;
  height: number;
  frameRate: number;
  contentHint: "detail" | "motion";
  publish: TrackPublishOptions;
}

export const SCREEN_SHARE_PROFILES: Record<ScreenShareQuality, ScreenShareProfile> = {
  detail: {
    width: 1920,
    height: 1080,
    frameRate: 30,
    contentHint: "detail",
    publish: {
      source: Track.Source.ScreenShare,
      stream: "screen_share",
      simulcast: true,
      screenShareEncoding: { maxBitrate: 5_000_000, maxFramerate: 30, priority: "high" },
      screenShareSimulcastLayers: [new VideoPreset(1280, 720, 1_500_000, 15, "medium")],
      degradationPreference: "maintain-resolution",
    },
  },
  motion: {
    width: 1920,
    height: 1080,
    frameRate: 60,
    contentHint: "motion",
    publish: {
      source: Track.Source.ScreenShare,
      stream: "screen_share",
      simulcast: true,
      screenShareEncoding: { maxBitrate: 8_000_000, maxFramerate: 60, priority: "high" },
      screenShareSimulcastLayers: [new VideoPreset(1280, 720, 2_500_000, 30, "medium")],
      degradationPreference: "maintain-framerate",
    },
  },
};

const SCREEN_SHARE_AUDIO_PUBLISH_OPTIONS: TrackPublishOptions = {
  source: Track.Source.ScreenShareAudio,
  stream: "screen_share",
  audioPreset: AudioPresets.musicHighQuality,
  dtx: false,
  red: false,
};
const MICROPHONE_PUBLISH_OPTIONS: TrackPublishOptions = {
  source: Track.Source.Microphone,
  stream: "camera",
  audioPreset: AudioPresets.speech,
  dtx: true,
  red: true,
  forceStereo: false,
  stopMicTrackOnMute: false,
};

type SetSinkIdCapableElement = HTMLMediaElement & {
  setSinkId?: (sinkId: string) => Promise<void>;
};

interface SwitchMicrophoneTrackOptions {
  preserveMuted?: boolean;
}

export function createMeetingRoom(): Room {
  return new Room({
    adaptiveStream: true,
    dynacast: true,
  });
}

export async function connectLiveKit(room: Room, url: string, token: string) {
  await room.connect(resolveLiveKitUrl(url), token, {
    autoSubscribe: true,
  });
}

export async function publishLocalMedia(room: Room): Promise<LocalTrack[]> {
  assertMediaDevicesSupported();

  const tracks = await createLocalTracks({
    audio: buildMicrophoneCaptureOptions(),
    video: true,
  });

  await Promise.all(
    tracks.map((track) => publishLocalTrackWithRoomDefaults(room, track)),
  );

  return tracks;
}

export function buildMicrophoneCaptureOptions(deviceId?: string): AudioCaptureOptions {
  return {
    deviceId: deviceId ? { exact: deviceId } : { ideal: "default" },
    echoCancellation: { ideal: true },
    noiseSuppression: { ideal: true },
    autoGainControl: { ideal: true },
    voiceIsolation: { ideal: true },
    channelCount: { ideal: 1 },
    sampleRate: { ideal: 48000 },
    sampleSize: { ideal: 16 },
  };
}

async function publishLocalTrackWithRoomDefaults(
  room: Room,
  track: LocalTrack,
): Promise<LocalTrackPublication> {
  if (track.kind === Track.Kind.Audio) {
    configureMicrophoneTrackForSpeech(track);
    return room.localParticipant.publishTrack(track, MICROPHONE_PUBLISH_OPTIONS);
  }

  return room.localParticipant.publishTrack(track);
}

function configureMicrophoneTrackForSpeech(track: LocalTrack | null): void {
  const mediaTrack = getMediaStreamTrack(track);
  if (!mediaTrack || mediaTrack.kind !== "audio") {
    return;
  }

  mediaTrack.contentHint = "speech";
}

async function applyMicrophoneProcessingConstraints(
  track: LocalTrack,
  deviceId?: string,
): Promise<void> {
  const mediaTrack = getMediaStreamTrack(track);
  if (!mediaTrack || mediaTrack.kind !== "audio") {
    return;
  }

  try {
    await mediaTrack.applyConstraints(buildMicrophoneCaptureOptions(deviceId));
  } catch {
    await mediaTrack.applyConstraints(buildMicrophoneCaptureOptions()).catch(() => undefined);
  }
}

function getMediaStreamTrack(track: LocalTrack | null): MediaStreamTrack | null {
  return (track as { mediaStreamTrack?: MediaStreamTrack } | null)?.mediaStreamTrack ?? null;
}

export function getLocalMicrophoneTrack(room: Room): LocalTrack | null {
  for (const publication of room.localParticipant.trackPublications.values()) {
    if (publication.source === Track.Source.Microphone && publication.track) {
      return publication.track as LocalTrack;
    }
  }

  return null;
}

export function getLocalCameraTrack(room: Room): LocalVideoTrack | null {
  for (const publication of room.localParticipant.trackPublications.values()) {
    if (publication.source === Track.Source.Camera && publication.track) {
      return publication.track as LocalVideoTrack;
    }
  }

  return null;
}

export async function publishLocalCameraTrack(room: Room): Promise<LocalVideoTrack> {
  assertMediaDevicesSupported();

  const existingTrack = getLocalCameraTrack(room);
  if (existingTrack) {
    return existingTrack;
  }

  const tracks = await createLocalTracks({
    audio: false,
    video: true,
  });
  const videoTrack = tracks.find((track) => track.kind === Track.Kind.Video) as
    | LocalVideoTrack
    | undefined;
  if (!videoTrack) {
    tracks.forEach((track) => track.stop());
    throw new Error("Failed to create camera track.");
  }

  try {
    await room.localParticipant.publishTrack(videoTrack);
  } catch (error) {
    videoTrack.stop();
    throw error;
  }

  return videoTrack;
}

export function isMicrophoneMuted(track: LocalTrack | null): boolean {
  if (!track) {
    return false;
  }

  const muted = (track as { isMuted?: boolean }).isMuted;
  return muted === true;
}

export function isCameraMuted(track: LocalVideoTrack | null): boolean {
  if (!track) {
    return true;
  }

  const muted = (track as { isMuted?: boolean }).isMuted;
  return muted === true;
}

export async function setLocalMicrophoneMuted(
  track: LocalTrack | null,
  muted: boolean,
): Promise<void> {
  if (!track) {
    throw new Error("Local microphone track is not ready.");
  }

  if (muted) {
    await track.mute();
    return;
  }

  await track.unmute();
}

export async function setLocalCameraMuted(
  track: LocalVideoTrack | null,
  muted: boolean,
): Promise<void> {
  if (!track) {
    throw new Error("Local camera track is not ready.");
  }

  if (muted) {
    await track.mute();
    return;
  }

  await track.unmute();
}

export async function switchLocalMicrophoneTrack(
  room: Room,
  currentTrack: LocalTrack | null,
  deviceId: string,
  options: SwitchMicrophoneTrackOptions = {},
): Promise<LocalTrack> {
  if (currentTrack) {
    const restartable = currentTrack as {
      restartTrack?: (options?: AudioCaptureOptions) => Promise<unknown>;
    };
    if (typeof restartable.restartTrack === "function") {
      try {
        await restartable.restartTrack(buildMicrophoneCaptureOptions(deviceId));
        configureMicrophoneTrackForSpeech(currentTrack);
        if (options.preserveMuted && !isMicrophoneMuted(currentTrack)) {
          await currentTrack.mute();
        }
        return currentTrack;
      } catch {
        // Fall through to other switch strategies.
      }
    }

    const candidate = currentTrack as { setDeviceId?: (id: string) => Promise<unknown> };
    if (typeof candidate.setDeviceId === "function") {
      try {
        const switched = await candidate.setDeviceId(deviceId);
        if (switched !== false) {
          await applyMicrophoneProcessingConstraints(currentTrack, deviceId);
          configureMicrophoneTrackForSpeech(currentTrack);
          if (options.preserveMuted && !isMicrophoneMuted(currentTrack)) {
            await currentTrack.mute();
          }
          return currentTrack;
        }
      } catch {
        // Fall through to replace-track strategy.
      }
    }
  }

  const tracks = await createLocalTracks({
    audio: buildMicrophoneCaptureOptions(deviceId),
    video: false,
  });
  const nextTrack = tracks.find((track) => track.kind === Track.Kind.Audio);
  if (!nextTrack) {
    tracks.forEach((track) => track.stop());
    throw new Error("Failed to create replacement microphone track.");
  }

  try {
    configureMicrophoneTrackForSpeech(nextTrack);
    if (options.preserveMuted && !isMicrophoneMuted(nextTrack)) {
      await nextTrack.mute();
    }
    await publishLocalTrackWithRoomDefaults(room, nextTrack);
  } catch (error) {
    nextTrack.stop();
    throw error;
  }

  if (currentTrack) {
    room.localParticipant.unpublishTrack(currentTrack, true);
    currentTrack.stop();
  }

  return nextTrack;
}

export function supportsAudioOutputSelection(): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  return typeof (HTMLMediaElement.prototype as SetSinkIdCapableElement).setSinkId === "function";
}

export async function enumerateAudioDevices(): Promise<{
  audioInputs: AudioDeviceOption[];
  audioOutputs: AudioDeviceOption[];
}> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) {
    return {
      audioInputs: [],
      audioOutputs: [],
    };
  }

  const devices = await navigator.mediaDevices.enumerateDevices();
  const audioInputs = devices
    .filter((device) => device.kind === "audioinput")
    .map((device, index) => ({
      deviceId: device.deviceId,
      label: device.label || `Microphone ${index + 1}`,
      kind: "audioinput" as const,
    }));
  const audioOutputs = devices
    .filter((device) => device.kind === "audiooutput")
    .map((device, index) => ({
      deviceId: device.deviceId,
      label: device.label || `Speaker ${index + 1}`,
      kind: "audiooutput" as const,
    }));

  return {
    audioInputs,
    audioOutputs,
  };
}

export class ScreenShareUnsupportedError extends Error {
  constructor() {
    super("Screen sharing isn't supported on this device.");
    this.name = "ScreenShareUnsupportedError";
  }
}

/** The user closed the browser's picker without choosing anything (not an error). */
export class ScreenShareCancelledError extends Error {
  constructor() {
    super("Screen sharing was cancelled.");
    this.name = "ScreenShareCancelledError";
  }
}

/** Feature detection only (no user-agent sniffing). Phones/tablets lack getDisplayMedia. */
export function isScreenShareSupported(): boolean {
  return (
    typeof navigator !== "undefined"
    && !!navigator.mediaDevices
    && typeof navigator.mediaDevices.getDisplayMedia === "function"
  );
}

export interface ScreenShareCaptureSettings {
  width?: number;
  height?: number;
  frameRate?: number;
}

export interface PublishedScreenShare {
  track: LocalVideoTrack;
  publication: LocalTrackPublication;
  audioTrack: LocalAudioTrack | null;
  audioPublication: LocalTrackPublication | null;
  /** Shared audio was requested but the browser/source did not provide it. */
  audioUnavailable: boolean;
  quality: ScreenShareQuality;
  requested: ScreenShareCaptureSettings;
  actual: ScreenShareCaptureSettings;
  trackSid?: string;
  trackName?: string;
}

function buildDisplayMediaOptions(quality: ScreenShareQuality, includeAudio: boolean): DisplayMediaStreamOptions {
  const profile = SCREEN_SHARE_PROFILES[quality];
  return {
    video: {
      width: { ideal: profile.width, max: profile.width },
      height: { ideal: profile.height, max: profile.height },
      frameRate: { ideal: profile.frameRate, max: profile.frameRate },
    },
    // Shared (tab/system) audio is raw program audio: no voice processing.
    audio: includeAudio
      ? { echoCancellation: false, noiseSuppression: false, autoGainControl: false }
      : false,
    // Chromium-only hints; other browsers ignore unknown members.
    ...({
      selfBrowserSurface: "exclude",
      surfaceSwitching: "include",
      systemAudio: includeAudio ? "include" : "exclude",
    } as Record<string, string>),
  };
}

function isPickerCancel(error: unknown): boolean {
  if (!(error instanceof DOMException) && !(error instanceof Error)) {
    return false;
  }
  if (error.name === "AbortError") {
    return true;
  }
  // Chromium reports a closed picker as NotAllowedError "Permission denied"; an OS-level
  // block says "by system" — that one is a real error the user needs to see.
  return error.name === "NotAllowedError" && !/system/i.test(error.message);
}

async function captureDisplay(quality: ScreenShareQuality, includeAudio: boolean): Promise<MediaStream> {
  const options = buildDisplayMediaOptions(quality, includeAudio);
  try {
    return await navigator.mediaDevices.getDisplayMedia(options);
  } catch (error) {
    if (isPickerCancel(error)) {
      throw new ScreenShareCancelledError();
    }
    // Some engines reject constraint shapes they don't support (TypeError /
    // OverconstrainedError) before showing a picker: retry once with plain options.
    const name = (error as { name?: string })?.name;
    if (name === "TypeError" || name === "OverconstrainedError") {
      try {
        return await navigator.mediaDevices.getDisplayMedia({ video: true, audio: includeAudio });
      } catch (retryError) {
        if (isPickerCancel(retryError)) {
          throw new ScreenShareCancelledError();
        }
        throw retryError;
      }
    }
    throw error;
  }
}

function readCaptureSettings(track: MediaStreamTrack): ScreenShareCaptureSettings {
  const settings = typeof track.getSettings === "function" ? track.getSettings() : {};
  return {
    width: settings.width,
    height: settings.height,
    frameRate: typeof settings.frameRate === "number" ? Math.round(settings.frameRate) : undefined,
  };
}

/**
 * Ask the browser for a screen/window/tab and publish it: one screen video track and,
 * when requested and provided, one screen-audio track. Throws ScreenShareCancelledError
 * when the picker is closed and ScreenShareUnsupportedError without getDisplayMedia.
 */
export async function publishScreenShareTrack(
  room: Room,
  options: { quality?: ScreenShareQuality; includeAudio?: boolean } = {},
): Promise<PublishedScreenShare> {
  if (!isScreenShareSupported()) {
    throw new ScreenShareUnsupportedError();
  }
  const quality = options.quality ?? "detail";
  const includeAudio = options.includeAudio === true;
  const profile = SCREEN_SHARE_PROFILES[quality];

  const stream = await captureDisplay(quality, includeAudio);
  const videoStreamTrack = stream.getVideoTracks()[0];
  if (!videoStreamTrack) {
    stream.getTracks().forEach((track) => track.stop());
    throw new Error("No screen video track returned by browser.");
  }
  // Extra tracks beyond one video + one audio are never published.
  stream.getVideoTracks().slice(1).forEach((track) => track.stop());
  const audioStreamTrack = includeAudio ? stream.getAudioTracks()[0] ?? null : null;
  stream.getAudioTracks().filter((track) => track !== audioStreamTrack).forEach((track) => track.stop());

  try {
    videoStreamTrack.contentHint = profile.contentHint;
  } catch {
    // contentHint is advisory.
  }

  const videoTrack = new LocalVideoTrack(videoStreamTrack, undefined, false);
  videoTrack.source = Track.Source.ScreenShare;
  const requested = { width: profile.width, height: profile.height, frameRate: profile.frameRate };
  const actual = readCaptureSettings(videoStreamTrack);
  if (import.meta.env.DEV) {
    console.debug("[screen-share] capture", { quality, requested, actual, audio: !!audioStreamTrack });
  }

  let publication: LocalTrackPublication;
  try {
    publication = await room.localParticipant.publishTrack(videoTrack, profile.publish);
  } catch (error) {
    videoTrack.stop();
    audioStreamTrack?.stop();
    throw error;
  }

  let audioTrack: LocalAudioTrack | null = null;
  let audioPublication: LocalTrackPublication | null = null;
  if (audioStreamTrack) {
    audioTrack = new LocalAudioTrack(audioStreamTrack, undefined, false);
    audioTrack.source = Track.Source.ScreenShareAudio;
    try {
      audioPublication = await room.localParticipant.publishTrack(audioTrack, SCREEN_SHARE_AUDIO_PUBLISH_OPTIONS);
    } catch {
      // Keep sharing the screen; the caller shows the "audio isn't available" notice.
      audioTrack.stop();
      audioTrack = null;
    }
  }

  return {
    track: videoTrack,
    publication,
    audioTrack,
    audioPublication,
    audioUnavailable: includeAudio && !audioPublication,
    quality,
    requested,
    actual,
    trackSid: publication.trackSid,
    trackName: publication.trackName || getTrackRuntimeName(videoTrack),
  };
}

/** Unpublish and stop the screen video and screen audio tracks (idempotent). */
export function unpublishScreenShareTrack(
  room: Room,
  track: LocalVideoTrack | null,
  audioTrack: LocalAudioTrack | null = null,
): void {
  for (const item of [audioTrack, track]) {
    if (!item) {
      continue;
    }
    try {
      room.localParticipant.unpublishTrack(item, true);
    } finally {
      item.stop();
    }
  }
}

export function preferScreenShareHighQuality(feed: ScreenShareFeed | null): void {
  const publication = feed?.publication;
  if (!publication || !("setVideoQuality" in publication)) {
    return;
  }

  publication.setVideoQuality(VideoQuality.HIGH);
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
      "Microphone/camera is unavailable in an insecure context. Use HTTPS for this web app.",
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

export function parseBrseTrackName(trackName: string): BrseTrackInfo | null {
  const parts = trackName.split("::");
  if (parts.length !== 4 || parts[0] !== "brse") {
    return null;
  }

  const [, speakerId, srcLang, tgtLang] = parts;
  if (!isMeetingLanguage(srcLang) || !isMeetingLanguage(tgtLang)) {
    return null;
  }

  return {
    speakerId,
    srcLang,
    tgtLang,
    rawName: trackName,
  };
}

export function isBrseLiveKitIdentity(identity: string): boolean {
  return identity.startsWith(BRSE_LIVEKIT_IDENTITY_PREFIX);
}

export function buildMediaSnapshot(args: {
  room: Room;
  selfParticipantId: string;
  selfDisplayName: string;
  participantsById: Record<string, ParticipantSnapshot>;
  audioRouting?: AudioRouting;
}): {
  videos: VideoFeed[];
  humanAudio: HumanAudioFeed[];
  brseAudio: BrseAudioFeed[];
  screenShares: ScreenShareFeed[];
  localVideoTrack: LocalVideoTrack | null;
} {
  const {
    room,
    selfParticipantId,
    selfDisplayName,
    participantsById,
    audioRouting,
  } = args;
  const videos: VideoFeed[] = [];
  const humanAudio: HumanAudioFeed[] = [];
  const brseAudio: BrseAudioFeed[] = [];
  const screenShares: ScreenShareFeed[] = [];
  const participantsByLiveKitIdentity = new Map<string, ParticipantSnapshot>();
  const renderedParticipantIds = new Set<string>();
  const renderedRemoteIdentities = new Set<string>();
  const selfSnapshot = participantsById[selfParticipantId];

  let localVideoTrack: LocalVideoTrack | null = null;

  Object.values(participantsById).forEach((participant) => {
    const livekitIdentity = participant.livekit_identity || participant.participant_id;
    participantsByLiveKitIdentity.set(livekitIdentity, participant);
  });

  room.localParticipant.trackPublications.forEach((publication) => {
    if (publication.source === Track.Source.Camera && publication.track) {
      localVideoTrack = publication.track as LocalVideoTrack;
    }

    if (
      publication.source === Track.Source.ScreenShare
      && publication.track
      && publication.track.kind === Track.Kind.Video
    ) {
      screenShares.push({
        participantId: selfParticipantId,
        displayName: selfDisplayName,
        isLocal: true,
        kind: selfSnapshot?.kind ?? "human",
        source: "screen_share",
        trackSid: publication.trackSid,
        trackName: publication.trackName || getTrackRuntimeName(publication.track),
        track: publication.track as LocalVideoTrack,
        participant: null,
        publication,
      });
    }
  });

  videos.push({
    participantId: selfParticipantId,
    displayName: selfDisplayName,
    isLocal: true,
    language: selfSnapshot?.language,
    kind: "human",
    isVirtual: false,
    livekitIdentity: selfSnapshot?.livekit_identity ?? selfParticipantId,
    metadata: selfSnapshot?.metadata,
    isCameraOff: !localVideoTrack || isCameraMuted(localVideoTrack),
    track: localVideoTrack,
    isSpeaking: room.localParticipant.isSpeaking,
  });
  renderedParticipantIds.add(selfParticipantId);

  Object.values(participantsById).forEach((snapshot) => {
    if (snapshot.participant_id === selfParticipantId) {
      return;
    }

    const remoteIdentity = snapshot.livekit_identity || snapshot.participant_id;
    const remoteParticipant = room.remoteParticipants.get(remoteIdentity) || null;
    const kind = resolveParticipantKind(snapshot, remoteIdentity, audioRouting);
    const videoTrack = remoteParticipant ? getRemoteVideoTrack(remoteParticipant) : null;

    if (remoteParticipant) {
      renderedRemoteIdentities.add(remoteParticipant.identity);
      collectParticipantAudio(remoteParticipant, snapshot, kind, humanAudio, brseAudio);
      collectParticipantScreenShares(remoteParticipant, snapshot, kind, screenShares);
    }

    videos.push({
      participantId: snapshot.participant_id,
      displayName: snapshot.display_name,
      isLocal: false,
      language: snapshot.language,
      kind,
      isVirtual: snapshot.is_virtual === true || kind === "virtual_brse",
      livekitIdentity: snapshot.livekit_identity ?? remoteIdentity,
      metadata: snapshot.metadata,
      isCameraOff: !videoTrack || isTrackMuted(videoTrack),
      track: videoTrack,
      isSpeaking: remoteParticipant?.isSpeaking,
    });
    renderedParticipantIds.add(snapshot.participant_id);
  });

  room.remoteParticipants.forEach((participant) => {
    if (renderedRemoteIdentities.has(participant.identity)) {
      return;
    }

    const snapshot = participantsByLiveKitIdentity.get(participant.identity);
    if (snapshot && renderedParticipantIds.has(snapshot.participant_id)) {
      return;
    }
    const participantId = snapshot?.participant_id || participant.identity;
    const kind = resolveParticipantKind(snapshot, participant.identity, audioRouting);
    const videoTrack = getRemoteVideoTrack(participant);
    const displayName = snapshot?.display_name
      || participant.name
      || (kind === "virtual_brse" ? "AI Relay" : participantId);

    collectParticipantAudio(participant, snapshot, kind, humanAudio, brseAudio);
    collectParticipantScreenShares(participant, snapshot, kind, screenShares);

    videos.push({
      participantId,
      displayName,
      isLocal: false,
      language: snapshot?.language,
      kind,
      isVirtual: snapshot?.is_virtual === true || kind === "virtual_brse",
      livekitIdentity: snapshot?.livekit_identity ?? participant.identity,
      metadata: snapshot?.metadata,
      isCameraOff: !videoTrack || isTrackMuted(videoTrack),
      track: videoTrack,
      isSpeaking: participant.isSpeaking,
    });
  });

  return {
    videos: videos.sort(compareVideoFeeds),
    humanAudio,
    brseAudio,
    screenShares,
    localVideoTrack,
  };
}

function isTrackMuted(track: LocalTrack | RemoteVideoTrack | null): boolean {
  if (!track) {
    return true;
  }

  return (track as { isMuted?: boolean }).isMuted === true;
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
    RoomEvent.ActiveSpeakersChanged,
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

function collectParticipantAudio(
  participant: RemoteParticipant,
  snapshot: ParticipantSnapshot | undefined,
  kind: ParticipantKind,
  humanAudio: HumanAudioFeed[],
  brseAudio: BrseAudioFeed[],
): void {
  participant.trackPublications.forEach((publication) => {
    const audioTrack = getRemoteAudioTrack(publication);
    if (!audioTrack) {
      return;
    }

    if (kind === "virtual_brse") {
      brseAudio.push({
        participantId: snapshot?.participant_id ?? DEFAULT_BRSE_PARTICIPANT_ID,
        displayName: snapshot?.display_name || participant.name || "AI Relay",
        trackSid: publication.trackSid,
        track: audioTrack,
        language: snapshot?.language,
        livekitIdentity: snapshot?.livekit_identity ?? participant.identity,
        info: parseBrseTrackName(publication.trackName),
      });
      return;
    }

    // Microphone and shared screen audio both play for everyone. (Only the
    // microphone feeds the AI relay; that filter lives in the backend runtime.)
    humanAudio.push({
      participantId: snapshot?.participant_id ?? participant.identity,
      displayName:
        snapshot?.display_name || participant.name || participant.identity,
      track: audioTrack,
      trackSid: publication.trackSid,
      source: publication.source === Track.Source.ScreenShareAudio ? "screen_share_audio" : "microphone",
      language: snapshot?.language,
    });
  });
}

function getRemoteVideoTrack(participant: RemoteParticipant): RemoteVideoTrack | null {
  for (const publication of participant.trackPublications.values()) {
    if (
      publication.source === Track.Source.Camera &&
      publication.track &&
      publication.track.kind === Track.Kind.Video
    ) {
      return publication.track as RemoteVideoTrack;
    }
  }

  return null;
}

function resolveParticipantKind(
  snapshot: ParticipantSnapshot | undefined,
  identity: string,
  audioRouting?: AudioRouting,
): ParticipantKind {
  if (snapshot?.kind) {
    return snapshot.kind;
  }

  if (snapshot?.is_virtual) {
    return "virtual_brse";
  }

  if (audioRouting?.virtual_participant_id) {
    if (snapshot?.participant_id === audioRouting.virtual_participant_id) {
      return "virtual_brse";
    }
  }

  if (snapshot?.participant_id === DEFAULT_BRSE_PARTICIPANT_ID) {
    return "virtual_brse";
  }

  if (isBrseLiveKitIdentity(identity)) {
    return "virtual_brse";
  }

  return "human";
}

function getRemoteAudioTrack(
  publication: RemoteTrackPublication,
): RemoteAudioTrack | null {
  if (!publication.track || publication.track.kind !== Track.Kind.Audio) {
    return null;
  }

  return publication.track as RemoteAudioTrack;
}

function collectParticipantScreenShares(
  participant: RemoteParticipant,
  snapshot: ParticipantSnapshot | undefined,
  kind: ParticipantKind,
  screenShares: ScreenShareFeed[],
): void {
  participant.trackPublications.forEach((publication) => {
    if (
      publication.source !== Track.Source.ScreenShare
      || !publication.track
      || publication.track.kind !== Track.Kind.Video
    ) {
      return;
    }

    screenShares.push({
      participantId: snapshot?.participant_id ?? participant.identity,
      displayName:
        snapshot?.display_name || participant.name || participant.identity,
      isLocal: false,
      kind,
      source: "screen_share",
      trackSid: publication.trackSid,
      trackName: publication.trackName || getTrackRuntimeName(publication.track),
      track: publication.track as RemoteVideoTrack,
      participant,
      publication,
    });
  });
}

function getTrackRuntimeName(track: unknown): string | undefined {
  return (track as { name?: string }).name;
}

function compareVideoFeeds(left: VideoFeed, right: VideoFeed): number {
  const leftRank = left.isLocal ? 0 : left.kind === "virtual_brse" ? 2 : 1;
  const rightRank = right.isLocal ? 0 : right.kind === "virtual_brse" ? 2 : 1;
  if (leftRank !== rightRank) {
    return leftRank - rightRank;
  }

  return left.displayName.localeCompare(right.displayName);
}
