import { useEffect, useRef, useState, type ReactNode } from "react";
import { Pin, PinOff } from "lucide-react";
import type { ParticipantSnapshot } from "../types/api";
import type { ScreenShareFeed, VideoFeed } from "../types/livekit";
import type { BrseRoomMode } from "../lib/brseModes";
import { preferScreenShareHighQuality } from "../lib/livekit";
import { useContentSwitchMotion } from "../lib/motion";
import { ParticipantTile } from "./ParticipantTile";
import { VideoTrackView } from "./MediaElements";
import { MotionButton } from "./MotionButton";

const SCREEN_SHARE_ASPECT_RATIO = 16 / 9;

export type PinnedStageTarget =
  | { type: "participant"; participantId: string }
  | { type: "screen"; participantId: string; trackSid?: string };

interface MeetingStageProps {
  videos: VideoFeed[];
  participants: ParticipantSnapshot[];
  selectedScreenSharer: ParticipantSnapshot | null;
  selectedScreenFeed: ScreenShareFeed | null;
  activeScreenShareCount: number;
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
  relayStatusLabel: string;
  sidePanelOpen?: boolean;
  pinnedTarget: PinnedStageTarget | null;
  onPinParticipant: (participantId: string) => void;
  onPinScreenShare: (participantId: string, trackSid?: string) => void;
  onUnpinStage: () => void;
}

export function MeetingStage({
  videos,
  participants,
  selectedScreenSharer,
  selectedScreenFeed,
  activeScreenShareCount,
  brseEnabled,
  brseRoomMode,
  brseAudioExpected,
  relayStatusLabel,
  sidePanelOpen: _sidePanelOpen,
  pinnedTarget,
  onPinParticipant,
  onPinScreenShare,
  onUnpinStage,
}: MeetingStageProps) {
  const participantById = new Map(
    participants.map((participant) => [participant.participant_id, participant]),
  );
  const hasScreenShare = !!selectedScreenSharer;
  const pinnedParticipantFeed =
    pinnedTarget?.type === "participant"
      ? videos.find((feed) => feed.participantId === pinnedTarget.participantId) ?? null
      : null;
  const pinnedScreenShareActive =
    pinnedTarget?.type === "screen"
    && !!selectedScreenSharer
    && selectedScreenSharer.participant_id === pinnedTarget.participantId;
  const stageMode = pinnedParticipantFeed
    ? "pinned-participant"
    : hasScreenShare
      ? "screen-share"
      : "participant-grid";
  const stageMotionRef = useContentSwitchMotion<HTMLElement>(
    `${stageMode}-${pinnedTarget?.type ?? "auto"}-${pinnedTarget?.participantId ?? "none"}`,
    {
      selector: ":scope > *",
      distance: 10,
      stagger: 0,
    },
  );

  const stageClass = [
    "meeting-stage",
    stageMode === "screen-share" ? "has-screen-share" : "",
    stageMode === "pinned-participant" ? "has-pinned-participant" : "",
    pinnedScreenShareActive ? "has-pinned-screen-share" : "",
    (stageMode === "screen-share" || pinnedParticipantFeed) ? "has-sharer-label" : "",
  ].filter(Boolean).join(" ");
  const additionalShareCount = Math.max(0, activeScreenShareCount - 1);
  const additionalShareLabel = additionalShareCount > 0
    ? ` + ${additionalShareCount} more`
    : "";
  const stageLabel = pinnedParticipantFeed
    ? `Pinned ${pinnedParticipantFeed.displayName}`
    : hasScreenShare && selectedScreenSharer
      ? pinnedScreenShareActive
        ? `Pinned share from ${selectedScreenSharer.display_name}${additionalShareLabel}`
        : `${selectedScreenSharer.display_name} is sharing${additionalShareLabel}`
      : null;

  return (
    <section className={stageClass} ref={stageMotionRef}>
      {stageLabel ? (
        <div className="stage-sharer-label stage-priority-label">
          <span>{stageLabel}</span>
        </div>
      ) : null}

      {pinnedParticipantFeed ? (
        <PinnedParticipantStage
          pinnedFeed={pinnedParticipantFeed}
          videos={videos}
          participantById={participantById}
          selectedScreenSharer={selectedScreenSharer}
          selectedScreenFeed={selectedScreenFeed}
          brseEnabled={brseEnabled}
          brseRoomMode={brseRoomMode}
          brseAudioExpected={brseAudioExpected}
          relayStatusLabel={relayStatusLabel}
          onPinParticipant={onPinParticipant}
          onPinScreenShare={onPinScreenShare}
          onUnpinStage={onUnpinStage}
        />
      ) : hasScreenShare ? (
        <SharedScreenStage
          videos={videos}
          participantById={participantById}
          selectedScreenSharer={selectedScreenSharer}
          selectedScreenFeed={selectedScreenFeed}
          brseEnabled={brseEnabled}
          brseRoomMode={brseRoomMode}
          brseAudioExpected={brseAudioExpected}
          relayStatusLabel={relayStatusLabel}
          isPinned={pinnedScreenShareActive}
          onPinParticipant={onPinParticipant}
          onPinScreenShare={onPinScreenShare}
          onUnpinStage={onUnpinStage}
        />
      ) : (
        <ParticipantGrid
          videos={videos}
          participantById={participantById}
          brseEnabled={brseEnabled}
          brseRoomMode={brseRoomMode}
          brseAudioExpected={brseAudioExpected}
          relayStatusLabel={relayStatusLabel}
          onPinParticipant={onPinParticipant}
          onUnpinStage={onUnpinStage}
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
  brseRoomMode,
  brseAudioExpected,
  relayStatusLabel,
  isPinned,
  onPinParticipant,
  onPinScreenShare,
  onUnpinStage,
}: {
  videos: VideoFeed[];
  participantById: Map<string, ParticipantSnapshot>;
  selectedScreenSharer: ParticipantSnapshot;
  selectedScreenFeed: ScreenShareFeed | null;
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
  relayStatusLabel: string;
  isPinned: boolean;
  onPinParticipant: (participantId: string) => void;
  onPinScreenShare: (participantId: string, trackSid?: string) => void;
  onUnpinStage: () => void;
}) {
  useEffect(() => {
    preferScreenShareHighQuality(selectedScreenFeed);
  }, [selectedScreenFeed]);

  const handleToggleSharePin = () => {
    if (isPinned) {
      onUnpinStage();
      return;
    }

    onPinScreenShare(selectedScreenSharer.participant_id, selectedScreenFeed?.trackSid);
  };

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
        <ScreenSharePinButton
          isPinned={isPinned}
          displayName={selectedScreenSharer.display_name}
          onClick={handleToggleSharePin}
        />
      </StageMediaSurface>

      <ParticipantFilmstrip
        videos={videos}
        participantById={participantById}
        brseEnabled={brseEnabled}
        brseRoomMode={brseRoomMode}
        brseAudioExpected={brseAudioExpected}
        relayStatusLabel={relayStatusLabel}
        pinnedParticipantId={null}
        onPinParticipant={onPinParticipant}
        onUnpinStage={onUnpinStage}
      />
    </div>
  );
}

function PinnedParticipantStage({
  pinnedFeed,
  videos,
  participantById,
  selectedScreenSharer,
  selectedScreenFeed,
  brseEnabled,
  brseRoomMode,
  brseAudioExpected,
  relayStatusLabel,
  onPinParticipant,
  onPinScreenShare,
  onUnpinStage,
}: {
  pinnedFeed: VideoFeed;
  videos: VideoFeed[];
  participantById: Map<string, ParticipantSnapshot>;
  selectedScreenSharer: ParticipantSnapshot | null;
  selectedScreenFeed: ScreenShareFeed | null;
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
  relayStatusLabel: string;
  onPinParticipant: (participantId: string) => void;
  onPinScreenShare: (participantId: string, trackSid?: string) => void;
  onUnpinStage: () => void;
}) {
  const secondaryVideos = videos.filter(
    (feed) => feed.participantId !== pinnedFeed.participantId,
  );
  const hasSecondaryContent = !!selectedScreenSharer || secondaryVideos.length > 0;

  return (
    <div className={hasSecondaryContent ? "pinned-participant-stage" : "pinned-participant-stage is-solo"}>
      <div className="pinned-participant-primary">
        <StageTile
          feed={pinnedFeed}
          participant={participantById.get(pinnedFeed.participantId)}
          brseEnabled={brseEnabled}
          brseRoomMode={brseRoomMode}
          brseAudioExpected={brseAudioExpected}
          relayStatusLabel={relayStatusLabel}
          isPinned
          onPinParticipant={onPinParticipant}
          onUnpinStage={onUnpinStage}
        />
      </div>

      {hasSecondaryContent ? (
        <div className="stage-video-strip pinned-stage-strip" aria-label="Other stage content">
          {selectedScreenSharer ? (
            <ScreenSharePreviewTile
              sharer={selectedScreenSharer}
              feed={selectedScreenFeed}
              onPin={() => onPinScreenShare(
                selectedScreenSharer.participant_id,
                selectedScreenFeed?.trackSid,
              )}
            />
          ) : null}
          {secondaryVideos.map((feed) => (
            <StageTile
              key={feed.participantId}
              feed={feed}
              participant={participantById.get(feed.participantId)}
              brseEnabled={brseEnabled}
              brseRoomMode={brseRoomMode}
              brseAudioExpected={brseAudioExpected}
              relayStatusLabel={relayStatusLabel}
              isPinned={false}
              onPinParticipant={onPinParticipant}
              onUnpinStage={onUnpinStage}
            />
          ))}
        </div>
      ) : null}
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
  brseRoomMode,
  brseAudioExpected,
  relayStatusLabel,
  onPinParticipant,
  onUnpinStage,
}: {
  videos: VideoFeed[];
  participantById: Map<string, ParticipantSnapshot>;
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
  relayStatusLabel: string;
  onPinParticipant: (participantId: string) => void;
  onUnpinStage: () => void;
}) {
  return (
    <div className={videos.length <= 2 ? "stage-video-grid is-few" : "stage-video-grid"}>
      {videos.length === 0 ? (
        <div className="stage-empty-state">
          <span className="stage-empty-kicker">Stage</span>
          <strong>Waiting for video</strong>
          <p>Audio, relay, chat, and notes stay active while cameras connect.</p>
        </div>
      ) : (
        videos.map((feed) => (
          <StageTile
            key={feed.participantId}
            feed={feed}
            participant={participantById.get(feed.participantId)}
            brseEnabled={brseEnabled}
            brseRoomMode={brseRoomMode}
            brseAudioExpected={brseAudioExpected}
            relayStatusLabel={relayStatusLabel}
            isPinned={false}
            onPinParticipant={onPinParticipant}
            onUnpinStage={onUnpinStage}
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
  brseRoomMode,
  brseAudioExpected,
  relayStatusLabel,
  pinnedParticipantId,
  onPinParticipant,
  onUnpinStage,
}: {
  videos: VideoFeed[];
  participantById: Map<string, ParticipantSnapshot>;
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
  relayStatusLabel: string;
  pinnedParticipantId: string | null;
  onPinParticipant: (participantId: string) => void;
  onUnpinStage: () => void;
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
          brseRoomMode={brseRoomMode}
          brseAudioExpected={brseAudioExpected}
          relayStatusLabel={relayStatusLabel}
          isPinned={feed.participantId === pinnedParticipantId}
          onPinParticipant={onPinParticipant}
          onUnpinStage={onUnpinStage}
        />
      ))}
    </div>
  );
}

function StageTile({
  feed,
  participant,
  brseEnabled,
  brseRoomMode,
  brseAudioExpected,
  relayStatusLabel,
  isPinned,
  onPinParticipant,
  onUnpinStage,
}: {
  feed: VideoFeed;
  participant?: ParticipantSnapshot;
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
  relayStatusLabel: string;
  isPinned: boolean;
  onPinParticipant: (participantId: string) => void;
  onUnpinStage: () => void;
}) {
  const isBrse = feed.kind === "virtual_brse" || feed.isVirtual;

  return (
    <ParticipantTile
      feed={feed}
      isScreenSharing={!!participant?.is_screen_sharing}
      isHost={!!participant?.is_host}
      isMutedByHost={!!participant?.muted_by_host}
      isBrseEnabled={brseEnabled}
      brseRoomMode={brseRoomMode}
      brseAudioExpected={brseAudioExpected}
      relayStatusLabel={relayStatusLabel}
      isPinned={isPinned}
      onPin={() => onPinParticipant(feed.participantId)}
      onUnpin={onUnpinStage}
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

function ScreenSharePinButton({
  isPinned,
  displayName,
  onClick,
}: {
  isPinned: boolean;
  displayName: string;
  onClick: () => void;
}) {
  return (
    <div className="screen-share-stage-action">
      <MotionButton
        className={isPinned ? "stage-pin-button is-active" : "stage-pin-button"}
        type="button"
        aria-label={isPinned ? `Unpin ${displayName}'s shared screen` : `Pin ${displayName}'s shared screen`}
        aria-pressed={isPinned}
        title={isPinned ? "Unpin shared screen" : "Pin shared screen"}
        onClick={onClick}
      >
        {isPinned ? <PinOff size={15} /> : <Pin size={15} />}
        <span>{isPinned ? "Unpin" : "Pin share"}</span>
      </MotionButton>
    </div>
  );
}

function ScreenSharePreviewTile({
  sharer,
  feed,
  onPin,
}: {
  sharer: ParticipantSnapshot;
  feed: ScreenShareFeed | null;
  onPin: () => void;
}) {
  return (
    <article className="screen-share-preview-card">
      <div className="screen-share-preview-media">
        {feed?.track ? (
          <VideoTrackView
            track={feed.track}
            fit="contain"
            className="screen-share-preview-video"
          />
        ) : (
          <div className="screen-share-preview-placeholder">
            <strong>{sharer.display_name}</strong>
            <span>Share connecting</span>
          </div>
        )}
      </div>
      <div className="screen-share-preview-footer">
        <div>
          <strong>Screen share</strong>
          <p>{sharer.display_name}</p>
        </div>
        <MotionButton
          className="tile-action-button screen-preview-pin"
          type="button"
          aria-label={`Pin ${sharer.display_name}'s shared screen`}
          title="Pin shared screen"
          onClick={onPin}
        >
          <Pin size={14} />
          <span>Pin</span>
        </MotionButton>
      </div>
    </article>
  );
}
