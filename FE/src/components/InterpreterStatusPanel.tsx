import type { InterpreterStatusEntry } from "../features/room/interpreter";
import { formatLanguageFlow, getLanguageLabel } from "../lib/languages";
import { useRevealMotion } from "../lib/motion";
import { useTextAnimations } from "../lib/textAnimations";

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
  useTextAnimations(statusMotionRef, {
    dependencies: [statuses.length],
  });

  return (
    <section className="panel interpreter-panel" ref={statusMotionRef}>
      <div className="panel-header">
        <div>
          <h3 data-text-animate="fade">AI Relay Status</h3>
          <p data-text-animate="fade">Shows room-wide relay activity from the virtual BRSE participant.</p>
        </div>
      </div>

      <div className="status-list">
        {statuses.length === 0 ? (
          <div className="empty-state small" data-status-motion>
            <strong data-text-animate="fade">No BRSE relay activity yet</strong>
            <p data-text-animate="fade">Status updates appear once AI relay begins listening or relaying speech.</p>
          </div>
        ) : null}

        {statuses.map((item) => (
          <div className="status-item" key={item.key} data-status-motion>
            <div>
              <strong data-text-animate="fade">{item.brseParticipantName}</strong>
              <p data-text-animate="fade">
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
