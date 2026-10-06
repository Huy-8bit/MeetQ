import { MicOff, MonitorUp, Pin, PinOff, Sparkles } from "lucide-react";
import type { VideoFeed } from "../types/livekit";
import type { BrseRoomMode } from "../lib/brseModes";
import { getLanguageLabel } from "../lib/languages";
import { VideoTrackView } from "./MediaElements";

interface ParticipantTileProps {
  feed: VideoFeed;
  label?: string;
  isScreenSharing?: boolean;
  isHost?: boolean;
  isCoHost?: boolean;
  isMutedByHost?: boolean;
  isBrseEnabled?: boolean;
  brseRoomMode?: BrseRoomMode;
  brseAudioExpected?: boolean;
  relayStatusLabel?: string;
  isPinned?: boolean;
  onPin?: () => void;
  onUnpin?: () => void;
}

export function ParticipantTile({
  feed,
  label,
  isScreenSharing = false,
  isHost = false,
  isCoHost = false,
  isMutedByHost = false,
  isBrseEnabled = true,
  brseRoomMode = "voice_text",
  brseAudioExpected = true,
  relayStatusLabel = "Relay idle",
  isPinned = false,
  onPin,
  onUnpin,
}: ParticipantTileProps) {
  const isBrse = feed.kind === "virtual_brse" || feed.isVirtual;
  const brseCaption =
    !isBrseEnabled
      ? "Relay off"
      : brseRoomMode === "text_only" || !brseAudioExpected
        ? "Text relay"
        : brseRoomMode === "silent_summary"
          ? "Summary capture"
          : "Voice + text relay";
  const initials = feed.displayName
    .split(" ")
    .map((part) => part[0]?.toUpperCase())
    .filter(Boolean)
    .slice(0, 2)
    .join("");
  const hasVideo = !!feed.track && !feed.isCameraOff;
  // `label` carries the participant status; only surface it when it's unusual.
  const statusNote =
    label && !feed.isLocal && !isBrse && !["connected", "Participant", "You"].includes(label)
      ? label.charAt(0).toUpperCase() + label.slice(1)
      : null;
  const subtitle = isBrse
    ? brseCaption
    : [
        feed.isLocal ? "You" : null,
        isHost ? "Host" : isCoHost ? "Co-host" : null,
        feed.language ? getLanguageLabel(feed.language) : null,
        statusNote,
      ]
        .filter(Boolean)
        .join(" · ");

  return (
    <article
      className={[
        "tile",
        isBrse ? "tile--ai" : "",
        feed.isSpeaking ? "is-speaking" : "",
        isPinned ? "is-pinned" : "",
      ].filter(Boolean).join(" ")}
      aria-label={`${feed.displayName}${feed.isLocal ? " (you)" : ""}`}
    >
      <div className="tile-media">
        {hasVideo ? (
          <VideoTrackView track={feed.track} mirrored={feed.isLocal} />
        ) : isBrse ? (
          <div className="tile-fallback">
            <span className="tile-avatar tile-avatar--ai" aria-hidden="true">
              <Sparkles size={22} />
            </span>
            <p className="tile-fallback-text">{isBrseEnabled ? relayStatusLabel : "Relay off"}</p>
          </div>
        ) : (
          <div className="tile-fallback">
            <span className="tile-avatar" aria-hidden="true">{initials || "?"}</span>
            {feed.isLocal && feed.isCameraOff ? <p className="tile-fallback-text">Camera off</p> : null}
          </div>
        )}
      </div>

      {onPin || onUnpin ? (
        <div className="tile-actions">
          <button
            className="tile-action"
            type="button"
            aria-label={isPinned ? `Unpin ${feed.displayName}` : `Pin ${feed.displayName}`}
            aria-pressed={isPinned}
            title={isPinned ? "Unpin" : "Pin to stage"}
            onClick={isPinned ? onUnpin : onPin}
          >
            {isPinned ? <PinOff size={14} aria-hidden="true" /> : <Pin size={14} aria-hidden="true" />}
          </button>
        </div>
      ) : null}

      <div className="tile-footer">
        {isMutedByHost ? (
          <span className="tile-icon tile-icon--danger" title="Muted by host">
            <MicOff size={12} aria-hidden="true" />
            <span className="sr-only">Muted by host</span>
          </span>
        ) : null}
        {isScreenSharing ? (
          <span className="tile-icon" title="Sharing screen">
            <MonitorUp size={12} aria-hidden="true" />
            <span className="sr-only">Sharing screen</span>
          </span>
        ) : null}
        <span className="tile-name">{feed.displayName}</span>
        {subtitle ? <span className="tile-subtitle">{subtitle}</span> : null}
      </div>
    </article>
  );
}
