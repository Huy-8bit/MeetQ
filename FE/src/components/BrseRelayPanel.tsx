import { useCallback, useEffect, useMemo, useRef } from "react";
import type { InterpreterStatusEntry } from "../features/room/interpreter";
import type { TranscriptEntry } from "../features/room/transcripts";
import type { BrseRoomMode } from "../lib/brseModes";
import { formatLanguageFlow, getLanguageLabel } from "../lib/languages";
import { animateLatestItem, useRevealMotion } from "../lib/motion";
import { useTextAnimations } from "../lib/textAnimations";
import type { MeetingLanguage } from "../types/api";

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
}: BrseRelayPanelProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const emptyMotionRef = useRevealMotion<HTMLDivElement>({
    selector: "[data-relay-empty-motion]",
    distance: 8,
    duration: 280,
    stagger: 36,
    dependencies: [brseEnabled, brseRoomMode, brseAudioExpected],
  });
  useTextAnimations(emptyMotionRef, {
    dependencies: [brseEnabled, brseRoomMode, brseAudioExpected],
  });
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

  useEffect(() => {
    const animation = animateLatestItem(listRef.current);
    return () => animation?.pause?.();
  }, [latestId]);

  if (visibleEntries.length === 0) {
    const emptyCopy = getRelayEmptyCopy({
      brseEnabled,
      brseRoomMode,
      brseAudioExpected,
    });

    return (
      <div className="relay-history-empty panel-empty-state" ref={emptyMotionRef}>
        <span className="panel-empty-kicker" data-relay-empty-motion data-text-animate="highlight">Relay</span>
        <strong data-relay-empty-motion data-text-animate="fade">{emptyCopy.title}</strong>
        <p data-relay-empty-motion data-text-animate="fade">{emptyCopy.detail}</p>
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

function getRelayEmptyCopy({
  brseEnabled,
  brseRoomMode,
  brseAudioExpected,
}: {
  brseEnabled: boolean;
  brseRoomMode: BrseRoomMode;
  brseAudioExpected: boolean;
}) {
  if (!brseEnabled) {
    return {
      title: "Relay is off",
      detail: "BRSE text relay is not running for this room.",
    };
  }

  if (brseRoomMode === "text_only" || !brseAudioExpected) {
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
        "relay-entry",
        isRelay ? "relay-entry-relay" : "relay-entry-human",
        isPartial ? "relay-entry-partial" : "",
        isLatest ? "relay-entry-latest" : "",
      ].filter(Boolean).join(" ")}
      data-motion-latest={isLatest ? "true" : undefined}
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
