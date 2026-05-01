import type { ParticipantSnapshot } from "../types/api";
import { getLanguageLabel } from "../lib/languages";

interface ParticipantListProps {
  participants: ParticipantSnapshot[];
  selfParticipantId?: string;
  isCurrentUserHost?: boolean;
  onMuteParticipant?: (participantId: string) => void;
  isMutingParticipant?: string | null;
  brseEnabled?: boolean;
  embedded?: boolean;
}

export function ParticipantList({
  participants,
  selfParticipantId,
  isCurrentUserHost = false,
  onMuteParticipant,
  isMutingParticipant,
  brseEnabled = true,
  embedded = false,
}: ParticipantListProps) {
  return (
    <section className={embedded ? "participant-list-panel panel-section" : "panel participant-list-panel"}>
      <div className="panel-header">
        <div>
          <h3>Participants</h3>
          <p>
            {brseEnabled
              ? "Human attendees and the AI relay are tracked from room state."
              : "Human attendees in the normal meeting."}
          </p>
        </div>
        <span className="panel-count">{participants.length}</span>
      </div>

      <div className="participant-list">
        {participants.map((participant) => {
          const isSelf = participant.participant_id === selfParticipantId;
          const isVirtual = participant.kind === "virtual_brse" || participant.is_virtual;
          const canMute =
            isCurrentUserHost &&
            !isSelf &&
            !isVirtual &&
            onMuteParticipant;

          return (
            <div className="participant-row" key={participant.participant_id}>
              <div>
                <strong>
                  {participant.display_name}
                  {isSelf ? " (You)" : ""}
                </strong>
                <p>
                  {isVirtual
                    ? "AI relay participant"
                    : participant.muted_by_host
                      ? "Muted by host"
                      : participant.status}
                </p>
              </div>
              <div className="participant-row-tags">
                {participant.is_host ? (
                  <span className="badge badge-host">Host</span>
                ) : null}
                {isVirtual ? (
                  <span className="badge kind">AI relay</span>
                ) : null}
                {participant.is_screen_sharing ? (
                  <span className="badge live">Sharing screen</span>
                ) : null}
                {participant.muted_by_host ? (
                  <span className="badge badge-muted-by-host">Muted</span>
                ) : null}
                <span className="language-pill">{getLanguageLabel(participant.language)}</span>
                {canMute ? (
                  <button
                    className="button-mute-participant"
                    onClick={() => onMuteParticipant(participant.participant_id)}
                    disabled={isMutingParticipant === participant.participant_id}
                  >
                    {isMutingParticipant === participant.participant_id ? "Muting..." : "Mute"}
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
