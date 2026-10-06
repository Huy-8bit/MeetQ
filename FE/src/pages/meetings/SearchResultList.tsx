import { HighlightedText } from "../../components/HighlightedText";
import type { SearchResultItem, SearchSourceType } from "../../types/recording";

const SOURCE_LABEL: Record<SearchSourceType, string> = {
  transcript: "Transcript",
  relay: "Relay",
  chat: "Chat",
  summary: "Summary",
};

export function formatClock(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Keyword search results: source, time, speaker and a highlighted snippet. */
export function SearchResultList({
  items,
  total,
  showMeeting = false,
  onOpen,
}: {
  items: SearchResultItem[];
  total: number;
  showMeeting?: boolean;
  onOpen: (item: SearchResultItem) => void;
}) {
  return (
    <div className="search-results">
      <p className="search-results-count" role="status">
        {total === 1 ? "1 result" : `${total} results`}
      </p>
      <ol className="search-result-list">
        {items.map((item, index) => (
          <li key={`${item.meeting_id}-${item.source_type}-${item.source_item_id ?? index}-${index}`}>
            <button type="button" className="search-result" onClick={() => onOpen(item)}>
              <span className="search-result-meta">
                <span className="search-result-source">{SOURCE_LABEL[item.source_type]}</span>
                {item.section ? <span>{item.section}</span> : null}
                {item.timestamp && item.source_type !== "summary" ? <time dateTime={item.timestamp}>{formatClock(item.timestamp)}</time> : null}
                {item.speaker ? <span>{item.speaker}</span> : null}
                {showMeeting ? <span className="search-result-meeting">{item.meeting_title?.trim() || item.meeting_id}</span> : null}
              </span>
              <span className="search-result-text">
                <HighlightedText text={item.text} highlights={item.highlights} />
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
