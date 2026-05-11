import type { InterpreterStatusEntry } from "../features/room/interpreter";
import { formatLanguageFlow, getLanguageLabel } from "../lib/languages";
import { useRevealMotion } from "../lib/motion";

interface InterpreterStatusPanelProps {
  statuses: InterpreterStatusEntry[];
}

export function InterpreterStatusPanel({
  statuses,
}: InterpreterStatusPanelProps) {
  const statusMotionRef = useRevealMotion<HTMLElement>({
    selector: "[data-status-motion]",
    distance: 8,
    duration: 300,
    stagger: 30,
    dependencies: [statuses.length],
  });

  return (
    <section className="panel interpreter-panel" ref={statusMotionRef}>
      <div className="panel-header">
        <div>
          <h3>AI Relay Status</h3>
          <p>Shows room-wide relay activity from the virtual BRSE participant.</p>
        </div>
      </div>

      <div className="status-list">
        {statuses.length === 0 ? (
          <div className="empty-state small" data-status-motion>
            <strong>No BRSE relay activity yet</strong>
            <p>Status updates appear once AI relay begins listening or relaying speech.</p>
          </div>
        ) : null}

        {statuses.map((item) => (
          <div className="status-item" key={item.key} data-status-motion>
            <div>
              <strong>{item.brseParticipantName}</strong>
              <p>
                Relaying {item.speakerName}
                {item.sourceLanguage
                  ? ` ${formatLanguageFlow(item.sourceLanguage, item.targetLanguage)}`
                  : ` to ${getLanguageLabel(item.targetLanguage)}`}
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
