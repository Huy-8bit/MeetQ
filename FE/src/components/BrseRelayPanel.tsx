import type { InterpreterStatusEntry } from "../features/room/interpreter";
import type { TranscriptEntry } from "../features/room/transcripts";
import {
  formatLanguageFlow,
  formatMeetingLanguageBridge,
  getLanguageLabel,
} from "../lib/languages";
import type { MeetingLanguage } from "../types/api";

interface BrseRelayPanelProps {
  brseEnabled: boolean;
  statuses: InterpreterStatusEntry[];
  transcripts: TranscriptEntry[];
  meetingLanguages: MeetingLanguage[];
}

export function BrseRelayPanel({
  brseEnabled,
  statuses,
  transcripts,
  meetingLanguages,
}: BrseRelayPanelProps) {
  const latestStatus = statuses[0] ?? null;
  const latestRelay = [...transcripts].reverse().find((entry) => entry.kind === "relay") ?? null;
  const modeLabel = brseEnabled ? "BRSE On" : "BRSE Off";
  const activityLabel = !brseEnabled
    ? "Normal meeting"
    : latestStatus
      ? normalizeStatusLabel(latestStatus.status)
      : "Idle";

  return (
    <section className="brse-relay-panel">
      <div className={brseEnabled ? "relay-mode-card is-on" : "relay-mode-card"}>
        <div>
          <span className="relay-mode-kicker">{modeLabel}</span>
          <h2>{brseEnabled ? "AI relay is available" : "Normal meeting mode"}</h2>
          <p>
            {brseEnabled
              ? `${formatMeetingLanguageBridge(meetingLanguages)} relay is ready for cross-language speech.`
              : "Human audio, chat, screen share, and participants remain active without BRSE AI relay."}
          </p>
        </div>
        <span className="relay-activity-badge">{activityLabel}</span>
      </div>

      {brseEnabled ? (
        <div className="relay-status-block">
          <div className="panel-header compact">
            <div>
              <h3>Relay State</h3>
              <p>
                {latestRelay
                  ? `Latest relay from ${latestRelay.sourceSpeakerName} to ${getLanguageLabel(latestRelay.relayTargetLanguage)}`
                  : "BRSE AI is waiting for speech that needs relay."}
              </p>
            </div>
          </div>

          {statuses.length === 0 ? (
            <div className="inline-empty-state">
              <strong>Idle</strong>
              <p>Relay status appears here when BRSE AI starts capturing or playing speech.</p>
            </div>
          ) : (
            <div className="status-list compact">
              {statuses.slice(0, 4).map((item) => (
                <div className="status-item compact" key={item.key}>
                  <div>
                    <strong>{item.brseParticipantName}</strong>
                    <p>
                      {item.speakerName}
                      {item.sourceLanguage
                        ? ` ${formatLanguageFlow(item.sourceLanguage, item.targetLanguage)}`
                        : ` to ${getLanguageLabel(item.targetLanguage)}`}
                      {item.message ? ` - ${item.message}` : ""}
                    </p>
                  </div>
                  <div className="transcript-badges">
                    <span className={`badge status-${item.status}`}>{normalizeStatusLabel(item.status)}</span>
                    {item.fallbackUsed ? <span className="badge warning">Fallback</span> : null}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="inline-empty-state">
          <strong>BRSE relay is off</strong>
          <p>Transcript will show normal meeting speech when available. Relay-only output is hidden in this mode.</p>
        </div>
      )}
    </section>
  );
}

function normalizeStatusLabel(status: InterpreterStatusEntry["status"]): string {
  return status
    .split("_")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}
