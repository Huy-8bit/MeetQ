import { useEffect, useRef, useState, type ReactNode } from "react";
import { Maximize2, Minimize2, Pin, PinOff, Video } from "lucide-react";
import type { ParticipantSnapshot } from "../types/api";
import type { ScreenShareFeed, VideoFeed } from "../types/livekit";
import type { BrseRoomMode } from "../lib/brseModes";
import { preferScreenShareHighQuality } from "../lib/livekit";
import { ParticipantTile } from "./ParticipantTile";
import { VideoTrackView } from "./MediaElements";
import { EmptyState } from "./ui/EmptyState";

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
  const stageClass = `stage stage--${stageMode}`;
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
    <section className={stageClass} aria-label="Meeting stage">
      {stageLabel ? <div className="stage-label">{stageLabel}</div> : null}

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
    <div className="stage-share">
      <StageMediaSurface>
        {selectedScreenFeed?.track ? (
          <VideoTrackView
            track={selectedScreenFeed.track}
            fit="contain"
            className="screen-share-video"
          />
        ) : (
          <div className="stage-placeholder">
            <strong>{selectedScreenSharer.display_name}</strong>
            <p>Screen share is connecting…</p>
          </div>
        )}
        <ScreenShareActions
          isPinned={isPinned}
          displayName={selectedScreenSharer.display_name}
          onTogglePin={handleToggleSharePin}
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
    <div className={hasSecondaryContent ? "stage-pinned" : "stage-pinned is-solo"}>
      <div className="stage-pinned-primary">
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
        <div className="stage-strip" aria-label="Other participants">
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
    <div className="stage-share-slot" ref={slotRef}>
      <div
        className="stage-share-frame"
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
    <div className="stage-grid" data-count={Math.min(videos.length, 9)}>
      {videos.length === 0 ? (
        <div className="stage-empty">
          <EmptyState
            icon={<Video size={20} />}
            title="Waiting for video"
            description="Audio, relay, chat and notes keep working while cameras connect."
          />
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
    <div className="stage-strip" aria-label="Participants">
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
      isHost={!!participant?.is_host || participant?.role === "host"}
      isCoHost={participant?.role === "co_host"}
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

function ScreenShareActions({
  isPinned,
  displayName,
  onTogglePin,
}: {
  isPinned: boolean;
  displayName: string;
  onTogglePin: () => void;
}) {
  const actionsRef = useRef<HTMLDivElement | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const fullscreenEnabled = typeof document !== "undefined" && document.fullscreenEnabled === true;

  useEffect(() => {
    if (!fullscreenEnabled) {
      return;
    }

    const handleChange = () => {
      const frame = actionsRef.current?.closest(".stage-share-frame") ?? null;
      setIsFullscreen(!!frame && document.fullscreenElement === frame);
    };
    handleChange();
    document.addEventListener("fullscreenchange", handleChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleChange);
    };
  }, [fullscreenEnabled]);

  const handleToggleFullscreen = () => {
    if (isFullscreen) {
      void document.exitFullscreen().catch(() => undefined);
      return;
    }
    const frame = actionsRef.current?.closest(".stage-share-frame");
    void frame?.requestFullscreen().catch(() => undefined);
  };

  return (
    <div className="stage-share-action" ref={actionsRef}>
      {fullscreenEnabled ? (
        <button
          className="tile-action"
          type="button"
          aria-label={isFullscreen ? "Exit full screen" : `Show ${displayName}'s shared screen full screen`}
          title={isFullscreen ? "Exit full screen" : "Full screen"}
          onClick={handleToggleFullscreen}
        >
          {isFullscreen ? <Minimize2 size={14} aria-hidden="true" /> : <Maximize2 size={14} aria-hidden="true" />}
          <span>{isFullscreen ? "Exit" : "Full screen"}</span>
        </button>
      ) : null}
      <button
        className="tile-action"
        type="button"
        aria-label={isPinned ? `Unpin ${displayName}'s shared screen` : `Pin ${displayName}'s shared screen`}
        aria-pressed={isPinned}
        title={isPinned ? "Unpin shared screen" : "Pin shared screen"}
        onClick={onTogglePin}
      >
        {isPinned ? <PinOff size={14} aria-hidden="true" /> : <Pin size={14} aria-hidden="true" />}
        <span>{isPinned ? "Unpin" : "Pin"}</span>
      </button>
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
    <article className="tile tile--share-preview">
      <div className="tile-media">
        {feed?.track ? (
          <VideoTrackView
            track={feed.track}
            fit="contain"
          />
        ) : (
          <div className="stage-placeholder">
            <strong>{sharer.display_name}</strong>
            <p>Share connecting…</p>
          </div>
        )}
      </div>
      <div className="tile-actions">
        <button
          className="tile-action"
          type="button"
          aria-label={`Pin ${sharer.display_name}'s shared screen`}
          title="Pin shared screen"
          onClick={onPin}
        >
          <Pin size={14} aria-hidden="true" />
          <span>Pin</span>
        </button>
      </div>
      <div className="tile-footer">
        <span className="tile-name">{sharer.display_name}&apos;s screen</span>
      </div>
    </article>
  );
}
