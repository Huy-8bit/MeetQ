import type {
  Language,
  ParticipantKind,
  ScreenShareSource,
} from "./api";
import type {
  LocalVideoTrack,
  RemoteParticipant,
  RemoteAudioTrack,
  RemoteVideoTrack,
} from "livekit-client";

export type GatewayConnectionState =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected";

export interface BrseTrackInfo {
  speakerId: string;
  srcLang: Language;
  tgtLang: Language;
  rawName: string;
}

export interface VideoFeed {
  participantId: string;
  displayName: string;
  isLocal: boolean;
  language?: Language;
  kind: ParticipantKind;
  isVirtual: boolean;
  livekitIdentity?: string | null;
  metadata?: Record<string, unknown>;
  track: LocalVideoTrack | RemoteVideoTrack | null;
}

export interface HumanAudioFeed {
  participantId: string;
  displayName: string;
  track: RemoteAudioTrack;
  language?: Language;
}

export interface BrseAudioFeed {
  participantId: string;
  displayName: string;
  trackSid: string;
  track: RemoteAudioTrack;
  language?: Language;
  livekitIdentity?: string | null;
  info: BrseTrackInfo | null;
}

export interface ScreenShareFeed {
  participantId: string;
  displayName: string;
  isLocal: boolean;
  kind: ParticipantKind;
  source: ScreenShareSource;
  trackSid?: string;
  trackName?: string;
  track: LocalVideoTrack | RemoteVideoTrack | null;
  participant: RemoteParticipant | null;
}

export interface AudioDeviceOption {
  deviceId: string;
  label: string;
  kind: "audioinput" | "audiooutput";
}
