import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ParticipantSnapshot } from "../types/api";
import type { ScreenShareFeed, VideoFeed } from "../types/livekit";
import { preferScreenShareHighQuality } from "../lib/livekit";
import { ParticipantTile } from "./ParticipantTile";
import { VideoTrackView } from "./MediaElements";

const SCREEN_SHARE_ASPECT_RATIO = 16 / 9;

interface MeetingStageProps {
  videos: VideoFeed[];
  participants: ParticipantSnapshot[];
  selectedScreenSharer: ParticipantSnapshot | null;
  selectedScreenFeed: ScreenShareFeed | null;
  activeScreenShareCount: number;
  brseEnabled: boolean;
  relayStatusLabel: string;
  sidePanelOpen?: boolean;
}

export function MeetingStage({
  videos,
  participants,
  selectedScreenSharer,
  selectedScreenFeed,
  activeScreenShareCount,
  brseEnabled,
  relayStatusLabel,
  sidePanelOpen: _sidePanelOpen,
}: MeetingStageProps) {
  const participantById = new Map(
    participants.map((participant) => [participant.participant_id, participant]),
  );
  const hasScreenShare = !!selectedScreenSharer;

  const stageClass = [
    "meeting-stage",
    hasScreenShare ? "has-screen-share" : "",
    hasScreenShare && selectedScreenSharer ? "has-sharer-label" : "",
  ].filter(Boolean).join(" ");

  return (
    <section className={stageClass}>
      {hasScreenShare && selectedScreenSharer ? (
        <div className="stage-sharer-label">
          <span>{selectedScreenSharer.display_name} is sharing</span>
        </div>
      ) : null}

      {hasScreenShare ? (
        <SharedScreenStage
          videos={videos}
          participantById={participantById}
          selectedScreenSharer={selectedScreenSharer}
          selectedScreenFeed={selectedScreenFeed}
          brseEnabled={brseEnabled}
          relayStatusLabel={relayStatusLabel}
        />
      ) : (
        <ParticipantGrid
          videos={videos}
          participantById={participantById}
          brseEnabled={brseEnabled}
          relayStatusLabel={relayStatusLabel}
        />
      )}
    </section>
  );
}

function SharedScreenStage({
  videos,
  participantById,
  selectedScreenSharer,
  selectedScreenFeed,
  brseEnabled,
  relayStatusLabel,
}: {
  videos: VideoFeed[];
  participantById: Map<string, ParticipantSnapshot>;
  selectedScreenSharer: ParticipantSnapshot;
  selectedScreenFeed: ScreenShareFeed | null;
  brseEnabled: boolean;
  relayStatusLabel: string;
}) {
  useEffect(() => {
    preferScreenShareHighQuality(selectedScreenFeed);
  }, [selectedScreenFeed]);

  return (
    <div className="screen-share-stage">
      <StageMediaSurface>
        {selectedScreenFeed?.track ? (
          <VideoTrackView
            track={selectedScreenFeed.track}
            fit="contain"
            className="screen-share-video"
          />
        ) : (
          <div className="screen-stage-placeholder">
            <strong>{selectedScreenSharer.display_name}</strong>
            <p>Screen stream is connecting.</p>
          </div>
        )}
      </StageMediaSurface>

      <ParticipantFilmstrip
        videos={videos}
        participantById={participantById}
        brseEnabled={brseEnabled}
        relayStatusLabel={relayStatusLabel}
      />
    </div>
  );
}

function StageMediaSurface({ children }: { children: ReactNode }) {
  const slotRef = useRef<HTMLDivElement | null>(null);
  const [frameSize, setFrameSize] = useState<{
    width: number;
    height: number;
  } | null>(null);

  useEffect(() => {
    const slot = slotRef.current;
    if (!slot) {
      return;
    }

    let animationFrame = 0;

    const updateFrameSize = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(() => {
        const availableWidth = slot.clientWidth;
        const availableHeight = slot.clientHeight;
        if (availableWidth <= 0 || availableHeight <= 0) {
          return;
        }

        let width = availableWidth;
        let height = width / SCREEN_SHARE_ASPECT_RATIO;
        if (height > availableHeight) {
          height = availableHeight;
          width = height * SCREEN_SHARE_ASPECT_RATIO;
        }

        const nextSize = {
          width: Math.floor(width),
          height: Math.floor(height),
        };

        setFrameSize((current) => {
          if (
            current
            && current.width === nextSize.width
            && current.height === nextSize.height
          ) {
            return current;
          }

          return nextSize;
        });
      });
    };

    updateFrameSize();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateFrameSize);
      return () => {
        window.cancelAnimationFrame(animationFrame);
        window.removeEventListener("resize", updateFrameSize);
      };
    }

    const observer = new ResizeObserver(updateFrameSize);
    observer.observe(slot);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      observer.disconnect();
    };
  }, []);

  return (
    <div className="screen-share-surface-slot" ref={slotRef}>
      <div
        className="screen-share-frame"
        style={
          frameSize
            ? {
                width: `${frameSize.width}px`,
                height: `${frameSize.height}px`,
              }
            : undefined
        }
      >
        {children}
      </div>
    </div>
  );
}

function ParticipantGrid({
  videos,
  participantById,
  brseEnabled,
  relayStatusLabel,
}: {
  videos: VideoFeed[];
  participantById: Map<string, ParticipantSnapshot>;
  brseEnabled: boolean;
  relayStatusLabel: string;
}) {
  return (
    <div className={videos.length <= 2 ? "stage-video-grid is-few" : "stage-video-grid"}>
      {videos.length === 0 ? (
        <div className="stage-empty-state">
          <strong>Waiting for video</strong>
        </div>
      ) : (
        videos.map((feed) => (
          <StageTile
            key={feed.participantId}
            feed={feed}
            participant={participantById.get(feed.participantId)}
            brseEnabled={brseEnabled}
            relayStatusLabel={relayStatusLabel}
          />
        ))
      )}
    </div>
  );
}

function ParticipantFilmstrip({
  videos,
  participantById,
  brseEnabled,
  relayStatusLabel,
}: {
  videos: VideoFeed[];
  participantById: Map<string, ParticipantSnapshot>;
  brseEnabled: boolean;
  relayStatusLabel: string;
}) {
  if (videos.length === 0) {
    return null;
  }

  return (
    <div className="stage-video-strip" aria-label="Participant video strip">
      {videos.map((feed) => (
        <StageTile
          key={feed.participantId}
          feed={feed}
          participant={participantById.get(feed.participantId)}
          brseEnabled={brseEnabled}
          relayStatusLabel={relayStatusLabel}
        />
      ))}
    </div>
  );
}

function StageTile({
  feed,
  participant,
  brseEnabled,
  relayStatusLabel,
}: {
  feed: VideoFeed;
  participant?: ParticipantSnapshot;
  brseEnabled: boolean;
  relayStatusLabel: string;
}) {
  const isBrse = feed.kind === "virtual_brse" || feed.isVirtual;

  return (
    <ParticipantTile
      feed={feed}
      isScreenSharing={!!participant?.is_screen_sharing}
      isHost={!!participant?.is_host}
      isMutedByHost={!!participant?.muted_by_host}
      isBrseEnabled={brseEnabled}
      relayStatusLabel={relayStatusLabel}
      label={
        feed.isLocal
          ? "You"
          : isBrse
            ? relayStatusLabel
            : participant?.status || "Participant"
      }
    />
  );
}
