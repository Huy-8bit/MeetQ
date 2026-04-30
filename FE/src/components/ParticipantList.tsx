import type { ParticipantSnapshot } from "../types/api";

interface ParticipantListProps {
  participants: ParticipantSnapshot[];
  selfParticipantId?: string;
}

export function ParticipantList({
  participants,
  selfParticipantId,
}: ParticipantListProps) {
  return (
    <section className="panel participant-list-panel">
      <div className="panel-header">
        <div>
          <h3>Participants</h3>
          <p>Human attendees and the virtual BRSE AI participant are tracked from gateway room state.</p>
        </div>
        <span className="panel-count">{participants.length}</span>
      </div>

      <div className="participant-list">
        {participants.map((participant) => (
          <div className="participant-row" key={participant.participant_id}>
            <div>
              <strong>
                {participant.display_name}
                {participant.participant_id === selfParticipantId ? " (You)" : ""}
              </strong>
              <p>
                {participant.kind === "virtual_brse" || participant.is_virtual
                  ? "AI relay participant"
                  : participant.status}
              </p>
            </div>
            <div className="participant-row-tags">
              {participant.kind === "virtual_brse" || participant.is_virtual ? (
                <span className="badge kind">BRSE AI</span>
              ) : null}
              {participant.is_screen_sharing ? (
                <span className="badge live">Sharing screen</span>
              ) : null}
              <span className="language-pill">{participant.language.toUpperCase()}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
