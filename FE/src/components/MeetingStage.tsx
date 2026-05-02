import type { ParticipantSnapshot } from "../types/api";
import type { ScreenShareFeed, VideoFeed } from "../types/livekit";
import { ParticipantTile } from "./ParticipantTile";
import { VideoTrackView } from "./MediaElements";

interface MeetingStageProps {
  videos: VideoFeed[];
  participants: ParticipantSnapshot[];
  selectedScreenSharer: ParticipantSnapshot | null;
  selectedScreenFeed: ScreenShareFeed | null;
  activeScreenShareCount: number;
  brseEnabled: boolean;
  relayStatusLabel: string;
}

export function MeetingStage({
  videos,
  participants,
  selectedScreenSharer,
  selectedScreenFeed,
  activeScreenShareCount,
  brseEnabled,
  relayStatusLabel,
}: MeetingStageProps) {
  const participantById = new Map(
    participants.map((participant) => [participant.participant_id, participant]),
  );
  const hasScreenShare = !!selectedScreenSharer;

  return (
    <section className={hasScreenShare ? "meeting-stage has-screen-share" : "meeting-stage"}>
      <div className="stage-status-row">
        <div>
          <span className="stage-kicker">Meeting stage</span>
          <h2>
            {selectedScreenSharer
              ? `${selectedScreenSharer.display_name} is sharing`
              : "Live video"}
          </h2>
        </div>
        <div className="stage-state-pills">
          <span>{activeScreenShareCount > 0 ? `${activeScreenShareCount} sharing` : "No screen share"}</span>
          <span>{brseEnabled ? `BRSE ${relayStatusLabel}` : "Normal mode"}</span>
        </div>
      </div>

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
  return (
    <div className="screen-share-stage">
      <div className="screen-share-frame">
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
      </div>

      <ParticipantFilmstrip
        videos={videos}
        participantById={participantById}
        brseEnabled={brseEnabled}
        relayStatusLabel={relayStatusLabel}
      />
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
          <strong>No camera feeds yet</strong>
          <p>Participants appear here after their room media connects.</p>
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
