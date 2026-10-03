import { useCallback, useEffect, useMemo, useRef } from "react";
import { Captions } from "lucide-react";
import type { InterpreterStatusEntry } from "../features/room/interpreter";
import type { TranscriptEntry } from "../features/room/transcripts";
import type { BrseRoomMode } from "../lib/brseModes";
import { formatLanguageFlow, getLanguageLabel } from "../lib/languages";
import type { MeetingLanguage } from "../types/api";
import { EmptyState } from "./ui/EmptyState";

interface BrseRelayPanelProps {
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
  statuses: InterpreterStatusEntry[];
  transcripts: TranscriptEntry[];
  meetingLanguages: MeetingLanguage[];
}

const MAX_VISIBLE = 25;
const AUTO_SCROLL_THRESHOLD = 120;

export function BrseRelayPanel({
  brseEnabled,
  brseRoomMode,
  brseAudioExpected,
  transcripts,
  meetingLanguages,
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
    const emptyCopy = getRelayEmptyCopy({
      brseEnabled,
      brseRoomMode,
      brseAudioExpected,
      languageCount: meetingLanguages.length,
    });

    return (
      <EmptyState icon={<Captions size={20} />} title={emptyCopy.title} description={emptyCopy.detail} />
    );
  }

  return (
    <div className="feed" ref={listRef} onScroll={handleScroll} aria-live="polite" aria-relevant="additions">
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

function getRelayEmptyCopy({
  brseEnabled,
  brseRoomMode,
  brseAudioExpected,
  languageCount,
}: {
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
  languageCount: number;
}) {
  if (!brseEnabled) {
    return {
      title: "Relay is off",
      detail: "BRSE text relay is not running for this room.",
    };
  }

  if (brseRoomMode === "text_only" || !brseAudioExpected) {
    if (languageCount === 1) {
      return {
        title: "Caption mode",
        detail: "Single-language captions will appear here. AI voice is off.",
      };
    }

    if (languageCount > 2) {
      return {
        title: "Waiting for speech",
        detail: "Multi-language text relay will appear here. AI voice is off.",
      };
    }

    return {
      title: "Waiting for speech",
      detail: "Text relay will appear here. AI voice is off.",
    };
  }

  if (brseRoomMode === "silent_summary") {
    return {
      title: "Summary capture",
      detail: "BRSE is listening for summary context without public relay.",
    };
  }

  return {
    title: "Waiting for speech",
    detail: "Text and AI voice relay will appear here.",
  };
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
        "feed-item",
        isRelay ? "feed-item--relay" : "",
        isPartial ? "is-partial" : "",
        isLatest ? "is-latest" : "",
      ].filter(Boolean).join(" ")}
    >
      <header className="feed-item-meta">
        <span className="feed-item-author">{isRelay ? entry.sourceSpeakerName || entry.actorName : entry.actorName}</span>
        <span>
          {isRelay
            ? formatLanguageFlow(entry.sourceSpeakerLanguage, entry.relayTargetLanguage ?? "auto")
            : getLanguageLabel(entry.actorLanguage)}
        </span>
        {isPartial ? <span className="feed-item-live">Live</span> : null}
      </header>

      {isRelay ? (
        <>
          <p className="feed-item-text">{entry.relayText ?? entry.text}</p>
          <p className="feed-item-source">{entry.sourceText}</p>
        </>
      ) : (
        <p className="feed-item-text">{entry.text}</p>
      )}
    </article>
  );
}
