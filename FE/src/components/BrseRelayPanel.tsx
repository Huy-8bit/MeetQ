import { useCallback, useEffect, useMemo, useRef } from "react";
import type { InterpreterStatusEntry } from "../features/room/interpreter";
import type { TranscriptEntry } from "../features/room/transcripts";
import { formatLanguageFlow, getLanguageLabel } from "../lib/languages";
import type { MeetingLanguage } from "../types/api";

interface BrseRelayPanelProps {
  brseEnabled: boolean;
  statuses: InterpreterStatusEntry[];
  transcripts: TranscriptEntry[];
  meetingLanguages: MeetingLanguage[];
}

const MAX_VISIBLE = 25;
const AUTO_SCROLL_THRESHOLD = 120;

export function BrseRelayPanel({
  brseEnabled,
  transcripts,
}: BrseRelayPanelProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const isNearBottomRef = useRef(true);

  const visibleEntries = useMemo(
    () => (transcripts.length > MAX_VISIBLE ? transcripts.slice(-MAX_VISIBLE) : transcripts),
    [transcripts],
  );

  const latestId = visibleEntries[visibleEntries.length - 1]?.transcriptId ?? null;

  const handleScroll = useCallback(() => {
    const node = listRef.current;
    if (!node) return;
    const dist = node.scrollHeight - node.scrollTop - node.clientHeight;
    isNearBottomRef.current = dist < AUTO_SCROLL_THRESHOLD;
  }, []);

  useEffect(() => {
    const node = listRef.current;
    if (!node || visibleEntries.length === 0) return;
    if (isNearBottomRef.current) {
      node.scrollTop = node.scrollHeight;
    }
  }, [visibleEntries]);

  if (visibleEntries.length === 0) {
    return (
      <div className="relay-history-empty">
        <span>{brseEnabled ? "Waiting for speech" : "Relay is off"}</span>
      </div>
    );
  }

  return (
    <div className="relay-history-list" ref={listRef} onScroll={handleScroll}>
      {visibleEntries.map((entry) => (
        <RelayEntry
          key={entry.transcriptId}
          entry={entry}
          isLatest={latestId === entry.transcriptId}
        />
      ))}
    </div>
  );
}

function RelayEntry({
  entry,
  isLatest,
}: {
  entry: TranscriptEntry;
  isLatest: boolean;
}) {
  const isRelay = entry.kind === "relay";
  const isPartial = !entry.isFinal;

  return (
    <article
      className={[
        "relay-entry",
        isRelay ? "relay-entry-relay" : "relay-entry-human",
        isPartial ? "relay-entry-partial" : "",
        isLatest ? "relay-entry-latest" : "",
      ].filter(Boolean).join(" ")}
    >
      <div className="relay-entry-meta">
        <span className="relay-entry-speaker">{entry.actorName}</span>
        <span className="relay-entry-lang">{getLanguageLabel(entry.actorLanguage)}</span>
        {isRelay ? (
          <span className="relay-entry-kind">
            {formatLanguageFlow(entry.sourceSpeakerLanguage, entry.relayTargetLanguage ?? "auto")}
          </span>
        ) : null}
        {isPartial ? <span className="relay-entry-live" /> : null}
      </div>

      {isRelay ? (
        <div className="relay-entry-body">
          <p className="relay-source-text">{entry.sourceText}</p>
          <p className="relay-translated-text">{entry.relayText ?? entry.text}</p>
        </div>
      ) : (
        <div className="relay-entry-body">
          <p className="relay-source-text">{entry.text}</p>
        </div>
      )}
    </article>
  );
}
