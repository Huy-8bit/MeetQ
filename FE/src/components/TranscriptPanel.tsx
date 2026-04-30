import { useEffect, useMemo, useRef } from "react";
import type { TranscriptEntry } from "../features/room/transcripts";

interface TranscriptPanelProps {
  entries: TranscriptEntry[];
}

export function TranscriptPanel({ entries }: TranscriptPanelProps) {
  const listRef = useRef<HTMLDivElement | null>(null);

  const latestTranscriptId = useMemo(
    () => entries[entries.length - 1]?.transcriptId ?? null,
    [entries],
  );

  useEffect(() => {
    const node = listRef.current;
    if (!node || entries.length === 0) {
      return;
    }

    const distanceFromBottom =
      node.scrollHeight - node.scrollTop - node.clientHeight;
    if (distanceFromBottom < 80) {
      node.scrollTop = node.scrollHeight;
    }
  }, [entries]);

  return (
    <section className="panel transcript-panel">
      <div className="panel-header">
        <div>
          <h3>Realtime Transcript</h3>
          <p>Speaker lines update live. Partial segments are upgraded to final in place.</p>
        </div>
      </div>

      <div className="transcript-list" ref={listRef}>
        {entries.length === 0 ? (
          <div className="empty-state small">
            <strong>Waiting for speech</strong>
            <p>Transcripts will appear here as the interpreter publishes events.</p>
          </div>
        ) : null}

        {entries.map((entry) => (
          <article
            className={`transcript-item ${entry.isFinal ? "" : "is-partial"} ${latestTranscriptId === entry.transcriptId ? "is-latest" : ""}`}
            key={entry.transcriptId}
          >
            <header className="transcript-item-header">
              <div>
                <strong>{entry.speakerName}</strong>
                <span>{entry.speakerLanguage.toUpperCase()}</span>
              </div>
              <div className="transcript-badges">
                <span className={`badge ${entry.isFinal ? "" : "live"}`}>
                  {entry.isFinal ? "Final" : "Partial"}
                </span>
                <span className="badge kind">
                  {entry.kind === "translated"
                    ? `Translated ${entry.srcLang.toUpperCase()}->${(entry.tgtLang ?? "-").toUpperCase()}`
                    : `Source ${entry.srcLang.toUpperCase()}`}
                </span>
                {entry.fallbackUsed ? (
                  <span className="badge warning">Degraded</span>
                ) : null}
              </div>
            </header>
            <div className="transcript-copy">
              <p className="transcript-source">{entry.text}</p>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
