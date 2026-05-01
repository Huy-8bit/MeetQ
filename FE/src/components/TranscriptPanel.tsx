import { useEffect, useMemo, useRef } from "react";
import type { TranscriptEntry } from "../features/room/transcripts";
import { formatLanguageFlow, getLanguageLabel } from "../lib/languages";

interface TranscriptPanelProps {
  entries: TranscriptEntry[];
  brseEnabled?: boolean;
  embedded?: boolean;
}

export function TranscriptPanel({
  entries,
  brseEnabled = true,
  embedded = false,
}: TranscriptPanelProps) {
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
    <section className={embedded ? "transcript-panel panel-section" : "panel transcript-panel"}>
      <div className="panel-header">
        <div>
          <h3>{brseEnabled ? "Transcript + Relay" : "Transcript"}</h3>
          <p>
            {brseEnabled
              ? "Original speech and BRSE relay lines stay separated for scanning."
              : "Normal meeting transcript appears here when speech is available."}
          </p>
        </div>
      </div>

      <div className="transcript-list" ref={listRef}>
        {entries.length === 0 ? (
          <div className="empty-state small">
            <strong>Waiting for speech</strong>
            <p>
              {brseEnabled
                ? "Human speech and relay output will appear here."
                : "Human speech will appear here when available."}
            </p>
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
                <span>{getLanguageLabel(entry.actorLanguage)}</span>
              </div>
              <div className="transcript-badges">
                <span className={`badge ${entry.isFinal ? "" : "live"}`}>
                  {entry.isFinal ? "Final" : "Partial"}
                </span>
                <span className="badge kind">
                  {entry.kind === "relay"
                    ? `BRSE Relay ${formatLanguageFlow(entry.sourceSpeakerLanguage, entry.relayTargetLanguage ?? "auto")}`
                    : entry.kind === "translated"
                      ? `Translated ${formatLanguageFlow(entry.sourceSpeakerLanguage, entry.relayTargetLanguage ?? "auto")}`
                      : `Human Source ${getLanguageLabel(entry.sourceSpeakerLanguage)}`}
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
                    {` (${getLanguageLabel(entry.sourceSpeakerLanguage)}): `}
                    {entry.sourceText}
                  </p>
                  <p className="transcript-relay">
                    <strong>{entry.actorName}</strong>
                    {` (${getLanguageLabel(entry.relayTargetLanguage ?? entry.actorLanguage)}): `}
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
