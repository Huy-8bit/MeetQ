import { Badge } from "../../components/ui/Badge";
import type { TranscriptLine } from "../api/types";
import { formatClock, languageName, languageShort } from "../lib/format";

const KIND_LABELS: Record<TranscriptLine["kind"], string> = {
  source: "Source",
  relay: "Relay",
  translated: "Translated",
  chat: "Chat",
  system: "System",
};

export function TranscriptList({ lines, showDate = false }: { lines: TranscriptLine[]; showDate?: boolean }) {
  return (
    <ol className="adm-transcript">
      {lines.map((line) => (
        <li key={`${line.kind}:${line.id}`} className={`adm-transcript-line is-${line.kind}`}>
          <div className="adm-transcript-meta">
            <time dateTime={line.created_at ?? undefined}>
              {showDate && line.created_at ? new Date(line.created_at).toLocaleString() : formatClock(line.created_at, true)}
            </time>
            <span className="adm-transcript-speaker">
              {line.kind === "relay" || line.kind === "translated" ? `Relay of ${line.speaker_name ?? "speaker"}` : line.speaker_name ?? "—"}
            </span>
            <span>
              {line.target_language ? `${languageShort(line.language)} → ${languageShort(line.target_language)}` : languageName(line.language)}
            </span>
            <Badge tone={line.kind === "system" ? "danger" : "neutral"} outline>
              {KIND_LABELS[line.kind]}
            </Badge>
          </div>
          <p className="adm-transcript-text">{line.text}</p>
          {line.source_text && line.kind !== "source" ? <p className="adm-transcript-source">{line.source_text}</p> : null}
          {line.translations.length > 0 ? (
            <ul className="adm-transcript-translations">
              {line.translations.map((translation) => (
                <li key={translation.language}>
                  <span>{languageShort(translation.language)}</span>
                  {translation.text}
                </li>
              ))}
            </ul>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
