import type { InterpreterStatusEntry } from "../features/room/interpreter";

interface InterpreterStatusPanelProps {
  statuses: InterpreterStatusEntry[];
}

export function InterpreterStatusPanel({
  statuses,
}: InterpreterStatusPanelProps) {
  return (
    <section className="panel interpreter-panel">
      <div className="panel-header">
        <div>
          <h3>Interpreter Status</h3>
          <p>Only statuses relevant to your current listening language are shown.</p>
        </div>
      </div>

      <div className="status-list">
        {statuses.length === 0 ? (
          <div className="empty-state small">
            <strong>No interpreter activity yet</strong>
            <p>Status updates appear once the backend begins routing speech.</p>
          </div>
        ) : null}

        {statuses.map((item) => (
          <div className="status-item" key={item.key}>
            <div>
              <strong>{item.speakerName}</strong>
              <p>
                {item.targetLanguage.toUpperCase()} listener track
                {item.message ? ` · ${item.message}` : ""}
              </p>
            </div>
            <div className="transcript-badges">
              <span className={`badge status-${item.status}`}>{item.status}</span>
              {item.fallbackUsed ? (
                <span className="badge warning">Fallback</span>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
