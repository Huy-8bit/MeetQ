import type { VideoFeed } from "../types/livekit";
import { VideoTrackView } from "./MediaElements";

interface ParticipantTileProps {
  feed: VideoFeed;
  label?: string;
  isScreenSharing?: boolean;
}

export function ParticipantTile({ feed, label, isScreenSharing = false }: ParticipantTileProps) {
  const isBrse = feed.kind === "virtual_brse" || feed.isVirtual;
  const initials = feed.displayName
    .split(" ")
    .map((part) => part[0]?.toUpperCase())
    .filter(Boolean)
    .slice(0, 2)
    .join("");

  return (
    <article className={`participant-tile ${isBrse ? "participant-tile-brse" : ""}`}>
      <div className="participant-media-frame">
        {feed.track ? (
          <VideoTrackView track={feed.track} mirrored={feed.isLocal} />
        ) : (
          <div className="participant-fallback">
            <span>{isBrse ? "AI" : initials || "?"}</span>
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
                  ? "Virtual BRSE relay"
                  : "Participant")}
          </p>
        </div>
        <div className="participant-tile-tags">
          {isBrse ? <span className="badge kind">BRSE AI</span> : null}
          {isScreenSharing ? <span className="badge live">Sharing screen</span> : null}
          {feed.language ? (
            <span className="language-pill">{feed.language.toUpperCase()}</span>
          ) : null}
        </div>
      </div>
    </article>
  );
}
