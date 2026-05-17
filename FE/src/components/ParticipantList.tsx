import type { ParticipantSnapshot } from "../types/api";
import type { BrseRoomMode } from "../lib/brseModes";
import { getLanguageLabel } from "../lib/languages";
import { useRevealMotion } from "../lib/motion";
import { useTextAnimations } from "../lib/textAnimations";
import { MotionButton } from "./MotionButton";

interface ParticipantListProps {
  participants: ParticipantSnapshot[];
  selfParticipantId?: string;
  isCurrentUserHost?: boolean;
  onMuteParticipant?: (participantId: string) => void;
  isMutingParticipant?: string | null;
  brseEnabled?: boolean;
  brseRoomMode?: BrseRoomMode;
  brseAudioExpected?: boolean;
  embedded?: boolean;
}

export function ParticipantList({
  participants,
  selfParticipantId,
  isCurrentUserHost = false,
  onMuteParticipant,
  isMutingParticipant,
  brseEnabled = true,
  brseRoomMode = "voice_text",
  brseAudioExpected = true,
  embedded = false,
}: ParticipantListProps) {
  const participantMotionRef = useRevealMotion<HTMLElement>({
    selector: "[data-participant-motion]",
    distance: 8,
    duration: 300,
    stagger: 28,
    scaleFrom: 0.996,
    dependencies: [participants.length, brseEnabled, brseRoomMode, brseAudioExpected],
  });
  useTextAnimations(participantMotionRef, {
    dependencies: [participants.length, brseEnabled, brseRoomMode, brseAudioExpected],
  });
  const brsePeopleCopy = getBrsePeopleCopy({
    brseEnabled,
    brseRoomMode,
    brseAudioExpected,
  });

  return (
    <section
      className={embedded ? "participant-list-panel panel-section" : "panel participant-list-panel"}
      ref={participantMotionRef}
    >
      <div className="panel-header">
        <div>
          <h3 data-text-animate="fade">Participants</h3>
          <p data-text-animate="fade">{brsePeopleCopy.panel}</p>
        </div>
        <span className="panel-count" data-text-animate="fade">{participants.length}</span>
      </div>

      <div className="participant-list">
        {participants.length === 0 ? (
          <div className="people-empty panel-empty-state" data-participant-motion>
            <span className="panel-empty-kicker" data-text-animate="highlight">People</span>
            <strong data-text-animate="fade">No participants yet</strong>
            <p data-text-animate="fade">Joined participants and BRSE relay presence will appear here.</p>
          </div>
        ) : null}

        {participants.map((participant) => {
          const isSelf = participant.participant_id === selfParticipantId;
          const isVirtual = participant.kind === "virtual_brse" || participant.is_virtual;
          const participantStatus = isVirtual
            ? brsePeopleCopy.virtual
            : participant.muted_by_host
              ? "Muted by host"
              : formatParticipantStatus(participant.status);
          const canMute =
            isCurrentUserHost &&
            !isSelf &&
            !isVirtual &&
            onMuteParticipant;

          return (
            <div
              className="participant-row"
              key={participant.participant_id}
              data-participant-motion
            >
              <div
                className={[
                  "participant-avatar",
                  isVirtual ? "is-virtual" : "",
                  participant.status === "connected" ? "is-online" : "",
                ].filter(Boolean).join(" ")}
                aria-hidden="true"
              >
                <span>{getParticipantInitials(participant.display_name, Boolean(isVirtual))}</span>
              </div>

              <div className="participant-main">
                <div className="participant-identity">
                  <strong data-text-animate="fade">{participant.display_name}</strong>
                  {isSelf ? <span className="participant-you-chip">You</span> : null}
                </div>
                <p data-text-animate="fade">{participantStatus}</p>
              </div>

              <div className="participant-row-tags">
                {participant.is_host ? (
                  <span className="badge badge-host">Host</span>
                ) : null}
                {isVirtual ? (
                  <span className="badge kind">{brsePeopleCopy.badge}</span>
                ) : null}
                {participant.is_screen_sharing ? (
                  <span className="badge live">Sharing screen</span>
                ) : null}
                {participant.muted_by_host ? (
                  <span className="badge badge-muted-by-host">Muted</span>
                ) : null}
                <span className="language-pill">{getLanguageLabel(participant.language)}</span>
                {canMute ? (
                  <MotionButton
                    className="button-mute-participant"
                    onClick={() => onMuteParticipant(participant.participant_id)}
                    disabled={isMutingParticipant === participant.participant_id}
                  >
                    {isMutingParticipant === participant.participant_id ? "Muting..." : "Mute"}
                  </MotionButton>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function getBrsePeopleCopy({
  brseEnabled,
  brseRoomMode,
  brseAudioExpected,
}: {
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
}) {
  if (!brseEnabled) {
    return {
      panel: "People currently in the room.",
      virtual: "BRSE relay is off",
      badge: "BRSE off",
    };
  }

  if (brseRoomMode === "text_only" || !brseAudioExpected) {
    return {
      panel: "People and the text relay presence.",
      virtual: "BRSE text relay participant",
      badge: "BRSE text",
    };
  }

  if (brseRoomMode === "silent_summary") {
    return {
      panel: "People and summary capture presence.",
      virtual: "BRSE summary participant",
      badge: "BRSE summary",
    };
  }

  return {
    panel: "People and AI relay presence.",
    virtual: "AI voice + text relay participant",
    badge: "AI relay",
  };
}

function getParticipantInitials(displayName: string, isVirtual: boolean): string {
  if (isVirtual) {
    return "AI";
  }

  const normalized = displayName.trim();
  if (!normalized) {
    return "U";
  }

  const parts = normalized.split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase()).join("") || "U";
}

function formatParticipantStatus(status: ParticipantSnapshot["status"]): string {
  switch (status) {
    case "connected":
      return "In room";
    case "joining":
      return "Joining";
    case "reconnecting":
      return "Reconnecting";
    case "disconnected":
      return "Disconnected";
    default:
      return status;
  }
}
