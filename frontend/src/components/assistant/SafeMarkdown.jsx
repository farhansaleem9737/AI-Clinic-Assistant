// A deliberately small Markdown subset rendered as React elements: paragraphs,
// bullet and numbered lists, headings, **bold**, *italic* and `code`. Text is
// never parsed as HTML (no dangerouslySetInnerHTML), so model output cannot
// inject markup or scripts. Links are shown as plain text.

function inline(text, keyPrefix) {
  const parts = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let match;
  let i = 0;
  while ((match = pattern.exec(text))) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${i++}`;
    if (token.startsWith("**")) parts.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith("`")) parts.push(<code key={key}>{token.slice(1, -1)}</code>);
    else parts.push(<em key={key}>{token.slice(1, -1)}</em>);
    last = match.index + token.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export default function SafeMarkdown({ text }) {
  const blocks = [];
  let list = null;
  const flush = () => {
    if (list) blocks.push(list);
    list = null;
  };
  (text ?? "").split(/\r?\n/).forEach((raw, index) => {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    const heading = line.match(/^#{1,4}\s+(.*)$/);
    if (bullet || numbered) {
      const type = bullet ? "ul" : "ol";
      if (!list || list.type !== type) {
        flush();
        list = { type, items: [] };
      }
      list.items.push(inline((bullet ?? numbered)[1], `li${index}`));
      return;
    }
    flush();
    if (!line.trim()) return;
    if (heading) blocks.push({ type: "h", content: inline(heading[1], `h${index}`) });
    else blocks.push({ type: "p", content: inline(line, `p${index}`) });
  });
  flush();
  return (
    <div className="ai-markdown">
      {blocks.map((block, i) => {
        if (block.type === "ul" || block.type === "ol") {
          const List = block.type;
          return (
            <List key={i}>
              {block.items.map((item, j) => (
                <li key={j}>{item}</li>
              ))}
            </List>
          );
        }
        if (block.type === "h") return <h4 key={i}>{block.content}</h4>;
        return <p key={i}>{block.content}</p>;
      })}
    </div>
  );
}
