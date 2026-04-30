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
          <h3>Conversation + BRSE Relay</h3>
          <p>Original speech stays visible, and BRSE AI relay lines are rendered as separate room-wide events.</p>
        </div>
      </div>

      <div className="transcript-list" ref={listRef}>
        {entries.length === 0 ? (
          <div className="empty-state small">
            <strong>Waiting for speech</strong>
            <p>Human speech and BRSE relay transcripts will appear here as the meeting progresses.</p>
          </div>
        ) : null}

        {entries.map((entry) => (
          <article
            className={`transcript-item ${entry.isFinal ? "" : "is-partial"} ${latestTranscriptId === entry.transcriptId ? "is-latest" : ""}`}
            key={entry.transcriptId}
          >
            <header className="transcript-item-header">
              <div>
                <strong>{entry.actorName}</strong>
                <span>{entry.actorLanguage.toUpperCase()}</span>
              </div>
              <div className="transcript-badges">
                <span className={`badge ${entry.isFinal ? "" : "live"}`}>
                  {entry.isFinal ? "Final" : "Partial"}
                </span>
                <span className="badge kind">
                  {entry.kind === "relay"
                    ? `BRSE Relay ${entry.sourceSpeakerLanguage.toUpperCase()}->${(entry.relayTargetLanguage ?? "AUTO").toUpperCase()}`
                    : entry.kind === "translated"
                      ? `Translated ${entry.sourceSpeakerLanguage.toUpperCase()}->${(entry.relayTargetLanguage ?? "AUTO").toUpperCase()}`
                      : `Human Source ${entry.sourceSpeakerLanguage.toUpperCase()}`}
                </span>
                {entry.fallbackUsed ? (
                  <span className="badge warning">Degraded</span>
                ) : null}
              </div>
            </header>
            <div className="transcript-copy">
              {entry.kind === "relay" ? (
                <>
                  <p className="transcript-source">
                    <strong>{entry.sourceSpeakerName}</strong>
                    {` (${entry.sourceSpeakerLanguage.toUpperCase()}): `}
                    {entry.sourceText}
                  </p>
                  <p className="transcript-relay">
                    <strong>{entry.actorName}</strong>
                    {` (${(entry.relayTargetLanguage ?? entry.actorLanguage).toUpperCase()}): `}
                    {entry.relayText ?? entry.text}
                  </p>
                </>
              ) : (
                <p className="transcript-source">{entry.text}</p>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
