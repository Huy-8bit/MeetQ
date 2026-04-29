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
          <p>Gateway state remains the source of truth for language and presence.</p>
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
              <p>{participant.status}</p>
            </div>
            <span className="language-pill">{participant.language.toUpperCase()}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
