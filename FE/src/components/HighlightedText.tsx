/**
 * Plain-text highlighting from server-provided [start, end] offsets. Text is rendered
 * as React text nodes only — never as HTML — so snippets can't inject markup.
 */
export function HighlightedText({ text, highlights }: { text: string; highlights: Array<[number, number]> }) {
  const ranges = [...highlights]
    .filter(([start, end]) => start >= 0 && end > start && end <= text.length)
    .sort((a, b) => a[0] - b[0]);
  const parts: Array<{ text: string; marked: boolean }> = [];
  let cursor = 0;
  for (const [start, end] of ranges) {
    if (start < cursor) continue;
    if (start > cursor) parts.push({ text: text.slice(cursor, start), marked: false });
    parts.push({ text: text.slice(start, end), marked: true });
    cursor = end;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), marked: false });
  return (
    <>
      {parts.map((part, index) => (part.marked ? <mark key={index}>{part.text}</mark> : <span key={index}>{part.text}</span>))}
    </>
  );
}
