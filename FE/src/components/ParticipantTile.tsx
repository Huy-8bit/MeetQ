import type { VideoFeed } from "../types/livekit";
import { VideoTrackView } from "./MediaElements";

interface ParticipantTileProps {
  feed: VideoFeed;
  label?: string;
}

export function ParticipantTile({ feed, label }: ParticipantTileProps) {
  const initials = feed.displayName
    .split(" ")
    .map((part) => part[0]?.toUpperCase())
    .filter(Boolean)
    .slice(0, 2)
    .join("");

  return (
    <article className="participant-tile">
      <div className="participant-media-frame">
        {feed.track ? (
          <VideoTrackView track={feed.track} mirrored={feed.isLocal} />
        ) : (
          <div className="participant-fallback">
            <span>{initials || "?"}</span>
          </div>
        )}
      </div>
      <div className="participant-tile-footer">
        <div>
          <strong>{feed.displayName}</strong>
          <p>{label || (feed.isLocal ? "You" : "Participant")}</p>
        </div>
        {feed.language ? (
          <span className="language-pill">{feed.language.toUpperCase()}</span>
        ) : null}
      </div>
    </article>
  );
}
