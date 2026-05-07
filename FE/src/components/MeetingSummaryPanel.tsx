import type {
  MeetingSummaryResponse,
  MeetingSummaryType,
} from "../types/api";

interface MeetingSummaryPanelProps {
  summary: MeetingSummaryResponse | null;
  intent: MeetingSummaryType;
  roomEnded?: boolean;
  isLoading?: boolean;
  isGenerating?: boolean;
  error?: string | null;
  canRefreshInterim?: boolean;
  onRefreshInterim: () => void;
  onCheckInterim: () => void;
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
  canRefreshInterim = true,
  onRefreshInterim,
  onCheckInterim,
  onPrepareFinal,
  embedded = false,
}: MeetingSummaryPanelProps) {
  const visibleType = roomEnded ? "final" : summary?.summary_type ?? intent;
  const status = summary?.status ?? null;
  const isPending = status === "pending";
  const hasCompletedContent =
    status === "completed" && !!summary?.summary_text?.trim();
  const canUseInterimAction =
    !roomEnded && canRefreshInterim && !isLoading && !isGenerating && !isPending;
  const generatedLabel = formatGeneratedTime(summary);

  return (
    <section className={embedded ? "meeting-summary-panel panel-section" : "panel meeting-summary-panel"}>
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

      <div className="summary-action-row">
        {roomEnded ? (
          <button
            type="button"
            className="button-primary summary-primary-action"
            onClick={onPrepareFinal}
            disabled={isLoading || isGenerating}
          >
            {isGenerating ? "Preparing..." : summary ? "Check final" : "Prepare final"}
          </button>
        ) : (
          <>
            <button
              type="button"
              className="button-primary summary-primary-action"
              onClick={onRefreshInterim}
              disabled={!canUseInterimAction}
            >
              {isGenerating || isPending
                ? "Generating..."
                : summary?.summary_type === "interim"
                  ? "Refresh summary"
                  : "Generate summary"}
            </button>
            <button
              type="button"
              className="button-secondary summary-secondary-action"
              onClick={onCheckInterim}
              disabled={isLoading || isGenerating}
            >
              {isLoading ? "Checking..." : "Check latest"}
            </button>
          </>
        )}
      </div>

      {error ? (
        <div className="summary-alert summary-alert-error" role="status">
          {error}
        </div>
      ) : null}

      <div className="summary-body">
        {isLoading && !summary ? (
          <SummaryState
            title="Checking summary"
            text="Looking for the latest saved meeting summary."
          />
        ) : null}

        {isGenerating && !summary ? (
          <SummaryState
            title={roomEnded ? "Preparing final summary" : "Generating summary"}
            text={
              roomEnded
                ? "The final summary can take a moment after the meeting closes."
                : "The live checkpoint is being generated from recent room activity."
            }
          />
        ) : null}

        {!isLoading && !isGenerating && !summary ? (
          <SummaryState
            title={roomEnded ? "Final summary is being prepared" : "No summary yet"}
            text={
              roomEnded
                ? "Check again shortly to read the final notes for this meeting."
                : "Generate a live checkpoint when you want a quick read of the meeting so far."
            }
          />
        ) : null}

        {summary && status === "pending" ? (
          <SummaryState
            title={roomEnded ? "Final summary is being prepared" : "Summary is being prepared"}
            text="This view will update when the backend finishes generating the summary."
          />
        ) : null}

        {summary && status === "skipped" ? (
          <SummaryState
            title="Not enough content yet"
            text={summary.error || "The meeting does not have enough transcript or chat content to summarize."}
          />
        ) : null}

        {summary && status === "failed" ? (
          <SummaryState
            title="Summary failed"
            text={summary.error || "The summary could not be generated. Try again."}
          />
        ) : null}

        {hasCompletedContent ? (
          <article className="summary-artifact">
            <div className="summary-artifact-meta">
              <span>{visibleType === "final" ? "Final summary" : "Current summary"}</span>
              {generatedLabel ? <time>{generatedLabel}</time> : null}
            </div>

            <p className="summary-main-text">{summary!.summary_text}</p>

            <SummaryList title="Highlights" items={summary!.highlights ?? []} />
            <SummaryList title="Decisions" items={summary!.decisions ?? []} />
            <ActionItems items={summary!.action_items ?? []} />
            <ParticipantSummaries items={summary!.participant_summary ?? []} />
          </article>
        ) : null}
      </div>
    </section>
  );
}

function SummaryState({ title, text }: { title: string; text: string }) {
  return (
    <div className="summary-state-card">
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
  items: NonNullable<MeetingSummaryResponse["action_items"]>;
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
