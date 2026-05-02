import { useEffect, useRef } from "react";
import type {
  LocalVideoTrack,
  RemoteAudioTrack,
  RemoteVideoTrack,
} from "livekit-client";
import {
  getRoomAudioOutputDevice,
  registerAudioSink,
  setRoomAudioOutputDevice,
  unregisterAudioSink,
} from "../lib/audioOutput";

interface VideoTrackViewProps {
  track: LocalVideoTrack | RemoteVideoTrack | null;
  mirrored?: boolean;
  fit?: "cover" | "contain";
  className?: string;
}

export function VideoTrackView({
  track,
  mirrored = false,
  fit = "cover",
  className,
}: VideoTrackViewProps) {
  const ref = useRef<HTMLVideoElement | null>(null);
  const videoClassName = [
    "media-video",
    mirrored ? "media-video-mirrored" : "",
    fit === "contain" ? "media-video-contain" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  useEffect(() => {
    const element = ref.current;
    if (!track || !element) {
      return;
    }

    track.attach(element);
    void element.play().catch(() => undefined);

    return () => {
      track.detach(element);
      element.srcObject = null;
    };
  }, [track]);

  return (
    <video
      ref={ref}
      autoPlay
      playsInline
      muted
      className={videoClassName}
    />
  );
}

interface AudioTrackSinkProps {
  track: RemoteAudioTrack;
  onOutputDeviceError?: (message: string) => void;
}

export function AudioTrackSink({
  track,
  onOutputDeviceError,
}: AudioTrackSinkProps) {
  const ref = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) {
      return;
    }

    registerAudioSink(element);
    track.attach(element);
    void element.play().catch(() => undefined);

    const outputDeviceId = getRoomAudioOutputDevice();
    if (outputDeviceId) {
      void setRoomAudioOutputDevice(outputDeviceId).catch((error) => {
        onOutputDeviceError?.(
          error instanceof Error
            ? error.message
            : "Failed to apply selected output device.",
        );
      });
    }

    return () => {
      track.detach(element);
      element.srcObject = null;
      unregisterAudioSink(element);
    };
  }, [track, onOutputDeviceError]);

  return <audio ref={ref} autoPlay playsInline />;
}
