import { useEffect, useRef } from "react";
import type {
  LocalVideoTrack,
  RemoteAudioTrack,
  RemoteVideoTrack,
} from "livekit-client";

interface VideoTrackViewProps {
  track: LocalVideoTrack | RemoteVideoTrack | null;
  mirrored?: boolean;
}

export function VideoTrackView({
  track,
  mirrored = false,
}: VideoTrackViewProps) {
  const ref = useRef<HTMLVideoElement | null>(null);

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
      className={mirrored ? "media-video media-video-mirrored" : "media-video"}
    />
  );
}

interface AudioTrackSinkProps {
  track: RemoteAudioTrack;
}

export function AudioTrackSink({ track }: AudioTrackSinkProps) {
  const ref = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) {
      return;
    }

    track.attach(element);
    void element.play().catch(() => undefined);

    return () => {
      track.detach(element);
      element.srcObject = null;
    };
  }, [track]);

  return <audio ref={ref} autoPlay playsInline />;
}
