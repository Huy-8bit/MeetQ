import type {
  LocalVideoTrack,
  RemoteAudioTrack,
  RemoteVideoTrack,
} from "livekit-client";
import type { AudioRouting, Language } from "./api";

export type GatewayConnectionState =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected";

export interface InterpreterTrackInfo {
  speakerId: string;
  listenerId: string;
  srcLang: Language;
  tgtLang: Language;
  rawName: string;
}

export interface VideoFeed {
  participantId: string;
  displayName: string;
  isLocal: boolean;
  language?: Language;
  track: LocalVideoTrack | RemoteVideoTrack | null;
}

export interface SameLanguagePassthroughAudioFeed {
  participantId: string;
  displayName: string;
  track: RemoteAudioTrack;
  language: Language;
  policy: AudioRouting["same_language_policy"];
}

export interface InterpreterAudioFeed {
  trackSid: string;
  track: RemoteAudioTrack;
  info: InterpreterTrackInfo;
}
