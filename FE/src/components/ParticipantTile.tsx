import type { VideoFeed } from "../types/livekit";
import type { BrseRoomMode } from "../lib/brseModes";
import { getLanguageLabel } from "../lib/languages";
import { VideoTrackView } from "./MediaElements";

interface ParticipantTileProps {
  feed: VideoFeed;
  label?: string;
  isScreenSharing?: boolean;
  isHost?: boolean;
  isMutedByHost?: boolean;
  isBrseEnabled?: boolean;
  brseRoomMode?: BrseRoomMode;
  brseAudioExpected?: boolean;
  relayStatusLabel?: string;
}

export function ParticipantTile({
  feed,
  label,
  isScreenSharing = false,
  isHost = false,
  isMutedByHost = false,
  isBrseEnabled = true,
  brseRoomMode = "voice_text",
  brseAudioExpected = true,
  relayStatusLabel = "Relay idle",
}: ParticipantTileProps) {
  const isBrse = feed.kind === "virtual_brse" || feed.isVirtual;
  const brseCaption =
    !isBrseEnabled
      ? "Normal meeting mode"
      : brseRoomMode === "text_only" || !brseAudioExpected
        ? "Text relay only"
        : brseRoomMode === "silent_summary"
          ? "Summary capture"
          : "AI voice + text relay";
  const brseBadge =
    !isBrseEnabled
      ? "BRSE off"
      : brseRoomMode === "text_only" || !brseAudioExpected
      ? "Text-only"
      : brseRoomMode === "silent_summary"
        ? "Summary"
        : "AI relay";
  const initials = feed.displayName
    .split(" ")
    .map((part) => part[0]?.toUpperCase())
    .filter(Boolean)
    .slice(0, 2)
    .join("");

  return (
    <article
      className={[
        "participant-tile",
        isBrse ? "participant-tile-brse" : "",
        isBrse && isBrseEnabled && (brseRoomMode === "text_only" || !brseAudioExpected)
          ? "participant-tile-brse-text-only"
          : "",
        feed.isSpeaking ? "is-speaking" : "",
      ].filter(Boolean).join(" ")}
    >
      <div className="participant-media-frame">
        {feed.track && !feed.isCameraOff ? (
          <VideoTrackView track={feed.track} mirrored={feed.isLocal} />
        ) : isBrse ? (
          <div className="participant-fallback participant-fallback-brse">
            <img src="/cat.jpg" alt="AI relay avatar" className="brse-avatar-img" />
            <strong>{isBrseEnabled ? relayStatusLabel : "Relay off"}</strong>
            <p>{brseCaption}</p>
          </div>
        ) : (
          <div className="participant-fallback participant-fallback-human">
            <span>{initials || "?"}</span>
            <strong>{feed.isLocal && feed.isCameraOff ? "Camera off" : feed.displayName}</strong>
          </div>
        )}
      </div>
      <div className="participant-tile-footer">
        <div>
          <strong>{feed.displayName}</strong>
          <p>
            {label
              || (feed.isLocal
                ? "You"
                : isBrse
                  ? relayStatusLabel
                  : "Participant")}
          </p>
        </div>
        <div className="participant-tile-tags">
          {isHost ? <span className="badge badge-host">Host</span> : null}
          {isBrse ? <span className="badge kind">{brseBadge}</span> : null}
          {isScreenSharing ? <span className="badge live">Sharing screen</span> : null}
          {isMutedByHost ? <span className="badge badge-muted-by-host">Muted</span> : null}
          {feed.language ? (
            <span className="language-pill">{getLanguageLabel(feed.language)}</span>
          ) : null}
        </div>
      </div>
    </article>
  );
}
