import type { SummaryDocument } from "../api/types";
import { formatDateTime, humanize, languageName } from "../lib/format";
import { KeyValueList } from "./Page";
import { SummaryStatusBadge } from "./StatusBadges";

const SUMMARY_ERROR_TEXT: Record<string, string> = {
  insufficient_source_content: "Not enough transcript or chat content to summarize.",
};

function describeSummaryError(summary: SummaryDocument): string {
  const raw = summary.error || summary.summary_text || "";
  if (!raw) return "No summary content.";
  return SUMMARY_ERROR_TEXT[raw] ?? (/^[a-z0-9_]+$/.test(raw) ? humanize(raw) : raw);
}

function ListSection({ title, items }: { title: string; items: string[] | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <section className="adm-summary-section">
      <h4>{title}</h4>
      <ul>
        {items.map((item, index) => (
          <li key={`${title}-${index}`}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

/** Same section order as the MeetQ room Summary tab (docs/system-design/03 R-43). */
export function SummaryView({ summary, title }: { summary: SummaryDocument; title: string }) {
  const actions = summary.action_item_details?.length
    ? summary.action_item_details
    : (summary.action_items ?? []).map((text) => ({ text, owner: null, due: null }));
  const stats = summary.source_stats ?? {};
  const statParts = [
    ["included_message_count", "included messages"],
    ["transcript_count", "transcripts"],
    ["relay_count", "relay lines"],
    ["chat_count", "chat messages"],
  ]
    .map(([key, label]) => (typeof stats[key] === "number" && (stats[key] as number) > 0 ? `${stats[key]} ${label}` : null))
    .filter(Boolean);

  return (
    <article className="adm-summary">
      <header className="adm-summary-header">
        <h3>{title}</h3>
        <SummaryStatusBadge status={summary.status} />
      </header>
      <KeyValueList
        items={[
          { label: "Language", value: languageName(summary.summary_language) },
          { label: "Requested", value: formatDateTime(summary.created_at) },
          { label: "Generated", value: formatDateTime(summary.generated_at) },
          { label: "Trigger", value: summary.trigger_reason ? humanize(summary.trigger_reason) : "—" },
        ]}
      />
      {summary.status === "failed" || summary.status === "skipped" ? (
        <p className="adm-summary-error">{describeSummaryError(summary)}</p>
      ) : null}
      {summary.status === "completed" ? (
        <div className="adm-summary-body">
          {summary.summary_text ? (
            <section className="adm-summary-section">
              <h4>Overview</h4>
              <p>{summary.summary_text}</p>
            </section>
          ) : null}
          <ListSection title="Key points" items={summary.key_points} />
          <ListSection title="Decisions" items={summary.decisions} />
          {actions.length > 0 ? (
            <section className="adm-summary-section">
              <h4>Action items</h4>
              <ul>
                {actions.map((item, index) => (
                  <li key={`action-${index}`}>
                    {item.text}
                    {item.owner || item.due ? (
                      <span className="adm-summary-meta"> — {[item.owner, item.due].filter(Boolean).join(" / ")}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <ListSection title="Risks and blockers" items={summary.risks_blockers} />
          <ListSection title="Open questions" items={summary.open_questions} />
          <ListSection title="Next steps" items={summary.next_steps} />
          {summary.participant_highlights?.length ? (
            <section className="adm-summary-section">
              <h4>Participants</h4>
              <ul>
                {summary.participant_highlights.map((item, index) => (
                  <li key={item.participant_id ?? index}>
                    {item.display_name ? <strong>{item.display_name}: </strong> : null}
                    {item.summary}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {statParts.length ? <p className="adm-summary-source">Based on {statParts.join(" · ")}{stats.truncated ? " · truncated source" : ""}</p> : null}
        </div>
      ) : null}
    </article>
  );
}
