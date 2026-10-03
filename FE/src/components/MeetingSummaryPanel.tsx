import type {
  MeetingSummaryActionItem,
  MeetingSummaryActionItemPayload,
  MeetingSummaryResponse,
  MeetingSummaryType,
} from "../types/api";
import { FileText, RefreshCw } from "lucide-react";
import { Alert } from "./ui/Alert";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { SkeletonLines, Spinner } from "./ui/Spinner";

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
  return (
    <section className="summary" aria-label="Meeting summary">
      <header className="summary-toolbar">
        <div className="summary-heading">
          <h2 className="section-title">{visibleType === "final" ? "Final summary" : "Live summary"}</h2>
          <p className="section-description">
            {generatedLabel
              ? [`Updated ${generatedLabel}`, summaryLanguage].filter(Boolean).join(" · ")
              : visibleType === "final"
                ? "Notes from the whole meeting."
                : "A checkpoint of the meeting so far."}
          </p>
        </div>

        <div className="summary-actions">
          {roomEnded ? (
            <>
              {showFinalCheckAction ? (
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<RefreshCw size={14} />}
                  onClick={onCheckFinal}
                  loading={isLoading}
                  disabled={isGenerating}
                >
                  Check latest
                </Button>
              ) : null}
              {showFinalGenerateAction ? (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={onPrepareFinal}
                  loading={isGenerating}
                  disabled={isLoading || isPending || hasCompletedContent}
                >
                  {isGenerating
                    ? "Preparing…"
                    : isFailed || errorSource === "generate"
                      ? "Retry"
                      : "Prepare final"}
                </Button>
              ) : null}
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant="ghost"
                iconOnly
                icon={<RefreshCw size={14} />}
                onClick={onCheckInterim}
                loading={isLoading}
                disabled={isGenerating}
                aria-label="Check for the latest summary"
                title="Check for the latest summary"
              />
              <Button
                size="sm"
                variant="primary"
                onClick={onRefreshInterim}
                loading={isGenerating || isPending}
                disabled={!canUseInterimAction}
              >
                {isGenerating || isPending
                  ? "Generating…"
                  : visibleSummary?.summary_type === "interim"
                    ? "Update"
                    : "Generate"}
              </Button>
            </>
          )}
        </div>
      </header>

      {error ? <Alert tone="danger">{error}</Alert> : null}

      <div className="summary-body">
        {isLoading && !visibleSummary ? (
          <SummaryState
            title="Checking summary"
            text="Looking for the latest saved meeting summary."
            isLoading
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
            isLoading
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
            isLoading
          />
        ) : null}

        {visibleSummary && status === "skipped" ? (
          <SummaryState
            title={roomEnded ? "Final summary is not available" : "Not enough content yet"}
            text={
              visibleSummary.summary_text
              || visibleSummary.error
              || "The meeting does not have enough transcript or chat content to summarize."
            }
          />
        ) : null}

        {visibleSummary && status === "failed" ? (
          <SummaryState
            title={roomEnded ? "Final summary failed" : "Summary failed"}
            text={visibleSummary.error || "The summary could not be generated. Try again."}
          />
        ) : null}

        {hasCompletedContent ? (
          <article className="summary-doc">
            {visibleSummary!.summary_text ? (
              <p className="summary-lead">{visibleSummary!.summary_text}</p>
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
            <SummaryList title="Risks and blockers" items={visibleSummary!.risks_blockers ?? []} />
            <SummaryList title="Open questions" items={visibleSummary!.open_questions ?? []} />
            <SummaryList title="Next steps" items={visibleSummary!.next_steps ?? []} />
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

function SummaryState({
  title,
  text,
  isLoading = false,
}: {
  title: string;
  text: string;
  isLoading?: boolean;
}) {
  if (isLoading) {
    return (
      <div className="summary-loading" role="status">
        <div className="summary-loading-head">
          <Spinner />
          <div>
            <p className="section-title">{title}</p>
            <p className="section-description">{text}</p>
          </div>
        </div>
        <SkeletonLines count={5} />
      </div>
    );
  }

  return <EmptyState icon={<FileText size={20} />} title={title} description={text} />;
}

function SummaryList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return null;
  }

  return (
    <section className="summary-section">
      <h3>{title}</h3>
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
      <h3>Action items</h3>
      <ul className="summary-list summary-list--actions">
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
      <h3>Participants</h3>
      <div className="summary-people">
        {items.map((item, index) => (
          <div className="summary-person" key={item.participant_id || `participant-${index}`}>
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
    stats.truncated ? "truncated source" : null,
  ].filter((item): item is string => !!item);

  if (statItems.length === 0) {
    return null;
  }

  return <p className="summary-source">Based on {statItems.join(" · ")}</p>;
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

  return `${value} ${label.toLowerCase()}`;
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
      || summary.risks_blockers?.length
      || summary.open_questions?.length
      || summary.next_steps?.length
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
