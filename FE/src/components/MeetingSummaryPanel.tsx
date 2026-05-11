import type {
  MeetingSummaryActionItem,
  MeetingSummaryActionItemPayload,
  MeetingSummaryResponse,
  MeetingSummaryType,
} from "../types/api";
import { useRevealMotion } from "../lib/motion";
import { MotionButton } from "./MotionButton";

interface MeetingSummaryPanelProps {
  summary: MeetingSummaryResponse | null;
  intent: MeetingSummaryType;
  roomEnded?: boolean;
  isLoading?: boolean;
  isGenerating?: boolean;
  error?: string | null;
  errorSource?: "fetch" | "generate" | null;
  canRefreshInterim?: boolean;
  onRefreshInterim: () => void;
  onCheckInterim: () => void;
  onCheckFinal: () => void;
  onPrepareFinal: () => void;
  embedded?: boolean;
}

export function MeetingSummaryPanel({
  summary,
  intent,
  roomEnded = false,
  isLoading = false,
  isGenerating = false,
  error = null,
  errorSource = null,
  canRefreshInterim = true,
  onRefreshInterim,
  onCheckInterim,
  onCheckFinal,
  onPrepareFinal,
  embedded = false,
}: MeetingSummaryPanelProps) {
  const visibleSummary =
    roomEnded && summary?.summary_type && summary.summary_type !== "final" ? null : summary;
  const visibleType = roomEnded ? "final" : visibleSummary?.summary_type ?? intent;
  const status = visibleSummary?.status ?? null;
  const isPending = status === "pending";
  const isFailed = status === "failed";
  const isSkipped = status === "skipped";
  const hasCompletedContent =
    status === "completed" && hasSummaryContent(visibleSummary);
  const canUseInterimAction =
    !roomEnded && canRefreshInterim && !isLoading && !isGenerating && !isPending;
  const showFinalGenerateAction =
    roomEnded
    && (
      isGenerating
      || (
        !isLoading
        && !hasCompletedContent
        && !isPending
        && (!error || errorSource === "generate")
        && (!visibleSummary || isFailed)
      )
    );
  const showFinalCheckAction = roomEnded && !isGenerating;
  const generatedLabel = formatGeneratedTime(visibleSummary);
  const summaryLanguage = formatSummaryLanguage(visibleSummary?.summary_language);
  const summaryMotionRef = useRevealMotion<HTMLElement>({
    selector: "[data-summary-motion]",
    distance: 8,
    duration: 300,
    stagger: 34,
    scaleFrom: 0.996,
    dependencies: [
      visibleType,
      status,
      hasCompletedContent,
      isLoading,
      isGenerating,
      error,
      visibleSummary?.generated_at,
      visibleSummary?.created_at,
    ],
  });

  return (
    <section
      className={embedded ? "meeting-summary-panel panel-section" : "panel meeting-summary-panel"}
      ref={summaryMotionRef}
    >
      <div className="panel-header summary-panel-header">
        <div>
          <h3>Summary</h3>
          <p>
            {visibleType === "final"
              ? "Final meeting notes after the room closes."
              : "A live checkpoint updated during the meeting."}
          </p>
        </div>
        <span className={`summary-type-chip summary-type-${visibleType}`}>
          {visibleType === "final" ? "Final" : "Current"}
        </span>
      </div>

      <div className="summary-action-row" data-summary-motion>
        {roomEnded ? (
          <>
            {showFinalGenerateAction ? (
              <MotionButton
                type="button"
                className="button-primary summary-primary-action"
                onClick={onPrepareFinal}
                disabled={isLoading || isGenerating || isPending || hasCompletedContent}
              >
                {isGenerating
                  ? "Preparing..."
                  : isFailed || errorSource === "generate"
                    ? "Retry final"
                    : "Prepare final"}
              </MotionButton>
            ) : null}
            {showFinalCheckAction ? (
              <MotionButton
                type="button"
                className="button-secondary summary-secondary-action"
                onClick={onCheckFinal}
                disabled={isLoading || isGenerating}
              >
                {isLoading ? "Checking..." : "Check latest"}
              </MotionButton>
            ) : null}
          </>
        ) : (
          <>
            <MotionButton
              type="button"
              className="button-primary summary-primary-action"
              onClick={onRefreshInterim}
              disabled={!canUseInterimAction}
            >
              {isGenerating || isPending
                ? "Generating..."
                : visibleSummary?.summary_type === "interim"
                  ? "Refresh summary"
                  : "Generate summary"}
            </MotionButton>
            <MotionButton
              type="button"
              className="button-secondary summary-secondary-action"
              onClick={onCheckInterim}
              disabled={isLoading || isGenerating}
            >
              {isLoading ? "Checking..." : "Check latest"}
            </MotionButton>
          </>
        )}
      </div>

      {error ? (
        <div className="summary-alert summary-alert-error" role="status" data-summary-motion>
          {error}
        </div>
      ) : null}

      <div className="summary-body">
        {isLoading && !visibleSummary ? (
          <SummaryState
            title="Checking summary"
            text="Looking for the latest saved meeting summary."
          />
        ) : null}

        {isGenerating && !visibleSummary ? (
          <SummaryState
            title={roomEnded ? "Preparing final summary" : "Generating summary"}
            text={
              roomEnded
                ? "The final summary can take a moment after the meeting closes."
                : "The live checkpoint is being generated from recent room activity."
            }
          />
        ) : null}

        {!isLoading && !isGenerating && !visibleSummary && !error ? (
          <SummaryState
            title={roomEnded ? "Final summary is not available yet" : "No summary yet"}
            text={
              roomEnded
                ? "Prepare it only if the saved final notes are not available."
                : "Generate a live checkpoint when you want a quick read of the meeting so far."
            }
          />
        ) : null}

        {visibleSummary && status === "pending" ? (
          <SummaryState
            title={roomEnded ? "Final summary is being prepared" : "Summary is being prepared"}
            text="This view will update when the backend finishes generating the summary."
          />
        ) : null}

        {visibleSummary && status === "skipped" ? (
          <SummaryState
            title={roomEnded ? "Final summary is not available" : "Not enough content yet"}
            text={visibleSummary.error || "The meeting does not have enough transcript or chat content to summarize."}
          />
        ) : null}

        {visibleSummary && status === "failed" ? (
          <SummaryState
            title={roomEnded ? "Final summary failed" : "Summary failed"}
            text={visibleSummary.error || "The summary could not be generated. Try again."}
          />
        ) : null}

        {hasCompletedContent ? (
          <article className="summary-artifact" data-summary-motion>
            <div className="summary-artifact-meta">
              <span>{visibleType === "final" ? "Final summary" : "Current summary"}</span>
              <div className="summary-artifact-meta-tail">
                {summaryLanguage ? <span>{summaryLanguage}</span> : null}
                {generatedLabel ? <time>{generatedLabel}</time> : null}
              </div>
            </div>

            {visibleSummary!.summary_text ? (
              <p className="summary-main-text">{visibleSummary!.summary_text}</p>
            ) : null}

            <SummaryList
              title="Key points"
              items={visibleSummary!.key_points ?? visibleSummary!.highlights ?? []}
            />
            <SummaryList title="Decisions" items={visibleSummary!.decisions ?? []} />
            <ActionItems
              items={normalizeActionItemsForDisplay(
                visibleSummary!.action_items,
                visibleSummary!.action_item_details,
              )}
            />
            <ParticipantSummaries
              items={
                visibleSummary!.participant_highlights?.length
                  ? visibleSummary!.participant_highlights
                  : visibleSummary!.participant_summary ?? []
              }
            />
            <SourceStats stats={visibleSummary!.source_stats} />
          </article>
        ) : null}
      </div>
    </section>
  );
}

function SummaryState({ title, text }: { title: string; text: string }) {
  return (
    <div className="summary-state-card panel-empty-state" data-summary-motion>
      <span className="panel-empty-kicker">Summary</span>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

function SummaryList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return null;
  }

  return (
    <section className="summary-section">
      <h4>{title}</h4>
      <ul className="summary-list">
        {items.map((item, index) => (
          <li key={`${title}-${index}`}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function ActionItems({
  items,
}: {
  items: MeetingSummaryActionItem[];
}) {
  if (items.length === 0) {
    return null;
  }

  return (
    <section className="summary-section">
      <h4>Action items</h4>
      <ul className="summary-action-list">
        {items.map((item, index) => {
          const meta = [item.owner, item.due].filter(Boolean).join(" / ");
          return (
            <li key={`action-${index}`}>
              <span>{item.text}</span>
              {meta ? <small>{meta}</small> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function ParticipantSummaries({
  items,
}: {
  items: NonNullable<MeetingSummaryResponse["participant_summary"]>;
}) {
  if (items.length === 0) {
    return null;
  }

  return (
    <section className="summary-section">
      <h4>Participants</h4>
      <div className="summary-participant-list">
        {items.map((item, index) => (
          <div className="summary-participant-item" key={item.participant_id || `participant-${index}`}>
            {item.display_name ? <strong>{item.display_name}</strong> : null}
            <p>{item.summary}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function SourceStats({
  stats,
}: {
  stats: MeetingSummaryResponse["source_stats"];
}) {
  if (!stats) {
    return null;
  }

  const statItems = [
    formatCountStat("Included messages", stats.included_message_count),
    formatCountStat("Transcripts", stats.transcript_count),
    formatCountStat("Source lines", stats.source_transcript_count),
    formatCountStat("Relay lines", stats.relay_count),
    formatCountStat("Chat messages", stats.chat_count),
    stats.truncated ? "Source truncated" : null,
  ].filter((item): item is string => !!item);

  if (statItems.length === 0) {
    return null;
  }

  return (
    <section className="summary-section">
      <h4>Source</h4>
      <div className="summary-stat-list">
        {statItems.map((item) => (
          <span key={item}>{item}</span>
        ))}
      </div>
    </section>
  );
}

function formatGeneratedTime(summary: MeetingSummaryResponse | null): string | null {
  const timestamp = summary?.generated_at || summary?.created_at;
  if (!timestamp) {
    return null;
  }

  const date = new Date(timestamp);
  if (!Number.isFinite(date.getTime())) {
    return null;
  }

  return date.toLocaleString([], {
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    day: "numeric",
  });
}

function formatSummaryLanguage(language: string | null | undefined): string | null {
  if (!language?.trim()) {
    return null;
  }

  return language.trim().toUpperCase();
}

function formatCountStat(label: string, value: number | null | undefined): string | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return null;
  }

  return `${label}: ${value}`;
}

function hasSummaryContent(summary: MeetingSummaryResponse | null): boolean {
  if (!summary) {
    return false;
  }

  return Boolean(
    summary.summary_text?.trim()
      || summary.key_points?.length
      || summary.highlights?.length
      || summary.decisions?.length
      || summary.action_items?.length
      || summary.participant_highlights?.length
      || summary.participant_summary?.length,
  );
}

function normalizeActionItemsForDisplay(
  items: MeetingSummaryResponse["action_items"],
  details: MeetingSummaryResponse["action_item_details"],
): MeetingSummaryActionItem[] {
  const sourceItems =
    Array.isArray(details) && details.length > 0 ? details : items;
  if (!Array.isArray(sourceItems)) {
    return [];
  }

  const normalized: MeetingSummaryActionItem[] = [];
  for (const item of sourceItems as MeetingSummaryActionItemPayload[]) {
    if (typeof item === "string") {
      const text = item.trim();
      if (text) {
        normalized.push({ text, owner: null, due: null });
      }
      continue;
    }

    if (!item || typeof item.text !== "string" || !item.text.trim()) {
      continue;
    }

    normalized.push({
      text: item.text.trim(),
      owner: typeof item.owner === "string" ? item.owner : null,
      due: typeof item.due === "string" ? item.due : null,
    });
  }

  return normalized;
}
