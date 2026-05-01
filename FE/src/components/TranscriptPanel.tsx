import { useCallback, useEffect, useMemo, useRef } from "react";
import type { TranscriptEntry } from "../features/room/transcripts";
import { formatLanguageFlow, getLanguageLabel } from "../lib/languages";

/**
 * Max items rendered in the transcript list at the render layer.
 * This is a safety net on top of state-layer pruning (MAX_TRANSCRIPT_ENTRIES=30).
 * Using 25 here to keep the visible list slightly shorter and more scannable.
 */
const MAX_VISIBLE_ENTRIES = 25;

/**
 * Distance (px) from the bottom edge within which auto-scroll activates.
 * If the user has scrolled more than this distance away from the bottom,
 * we assume they are reviewing history and do NOT force-scroll.
 */
const AUTO_SCROLL_THRESHOLD = 120;

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
  const isNearBottomRef = useRef(true);

  const visibleEntries = useMemo(
    () => (entries.length > MAX_VISIBLE_ENTRIES ? entries.slice(-MAX_VISIBLE_ENTRIES) : entries),
    [entries],
  );

  const latestTranscriptId = useMemo(
    () => visibleEntries[visibleEntries.length - 1]?.transcriptId ?? null,
    [visibleEntries],
  );

  const handleScroll = useCallback(() => {
    const node = listRef.current;
    if (!node) {
      return;
    }

    const distanceFromBottom =
      node.scrollHeight - node.scrollTop - node.clientHeight;
    isNearBottomRef.current = distanceFromBottom < AUTO_SCROLL_THRESHOLD;
  }, []);

  useEffect(() => {
    const node = listRef.current;
    if (!node || visibleEntries.length === 0) {
      return;
    }

    if (isNearBottomRef.current) {
      node.scrollTop = node.scrollHeight;
    }
  }, [visibleEntries]);

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
        {visibleEntries.length > 0 ? (
          <span className="panel-count">{visibleEntries.length}</span>
        ) : null}
      </div>

      <div className="transcript-list" ref={listRef} onScroll={handleScroll}>
        {visibleEntries.length === 0 ? (
          <div className="empty-state small">
            <strong>Waiting for speech</strong>
            <p>
              {brseEnabled
                ? "Human speech and relay output will appear here."
                : "Human speech will appear here when available."}
            </p>
          </div>
        ) : null}

        {visibleEntries.map((entry) => (
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
