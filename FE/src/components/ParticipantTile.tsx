import type { VideoFeed } from "../types/livekit";
import { getLanguageLabel } from "../lib/languages";
import { VideoTrackView } from "./MediaElements";

interface ParticipantTileProps {
  feed: VideoFeed;
  label?: string;
  isScreenSharing?: boolean;
  isHost?: boolean;
  isMutedByHost?: boolean;
  isBrseEnabled?: boolean;
  relayStatusLabel?: string;
}

export function ParticipantTile({
  feed,
  label,
  isScreenSharing = false,
  isHost = false,
  isMutedByHost = false,
  isBrseEnabled = true,
  relayStatusLabel = "Relay idle",
}: ParticipantTileProps) {
  const isBrse = feed.kind === "virtual_brse" || feed.isVirtual;
  const initials = feed.displayName
    .split(" ")
    .map((part) => part[0]?.toUpperCase())
    .filter(Boolean)
    .slice(0, 2)
    .join("");

  return (
    <article className={`participant-tile ${isBrse ? "participant-tile-brse" : ""} ${feed.isSpeaking ? "is-speaking" : ""}`.trim()}>
      <div className="participant-media-frame">
        {feed.track && !feed.isCameraOff ? (
          <VideoTrackView track={feed.track} mirrored={feed.isLocal} />
        ) : isBrse ? (
          <div className="participant-fallback participant-fallback-brse">
            <img src="/cat.jpg" alt="AI relay avatar" className="brse-avatar-img" />
            <strong>{isBrseEnabled ? relayStatusLabel : "Relay off"}</strong>
            <p>{isBrseEnabled ? "AI relay participant" : "Normal meeting mode"}</p>
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
          {isBrse ? <span className="badge kind">AI relay</span> : null}
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
