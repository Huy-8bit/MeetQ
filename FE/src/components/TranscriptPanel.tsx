import type { TranscriptEntry } from "../features/room/transcripts";

interface TranscriptPanelProps {
  entries: TranscriptEntry[];
}

export function TranscriptPanel({ entries }: TranscriptPanelProps) {
  return (
    <section className="panel transcript-panel">
      <div className="panel-header">
        <div>
          <h3>Realtime Transcript</h3>
          <p>Partial segments update in place and final segments replace them.</p>
        </div>
      </div>

      <div className="transcript-list">
        {entries.length === 0 ? (
          <div className="empty-state small">
            <strong>Waiting for speech</strong>
            <p>Transcripts will appear here as the interpreter publishes events.</p>
          </div>
        ) : null}

        {entries.map((entry) => (
          <article className="transcript-item" key={entry.transcriptId}>
            <header className="transcript-item-header">
              <div>
                <strong>{entry.speakerName}</strong>
                <span>
                  {entry.sourceLanguage.toUpperCase()}
                  {entry.targetLanguage
                    ? ` -> ${entry.targetLanguage.toUpperCase()}`
                    : ""}
                </span>
              </div>
              <div className="transcript-badges">
                {!entry.isFinal ? <span className="badge">Partial</span> : null}
                {entry.fallbackUsed ? (
                  <span className="badge warning">Degraded</span>
                ) : null}
              </div>
            </header>
            <div className="transcript-copy">
              <p className="transcript-source">{entry.sourceText}</p>
              <p className="transcript-translation">
                {entry.translatedText || "No translated text in snapshot yet."}
              </p>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
