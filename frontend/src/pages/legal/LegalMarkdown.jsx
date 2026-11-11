import { Fragment } from "react";

/**
 * Renders a legal document kept as Markdown in this folder, so the clinic's text
 * can be replaced without touching code. Only what these documents use:
 * # / ## / ### headings, "- " and "1. " lists, **bold**, and lines ending in two
 * spaces as line breaks. "[Square brackets]" are the drafter's placeholders and
 * notes; they are shown highlighted so an unfinished document is obvious.
 * Plain text only: nothing is inserted as HTML.
 */
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*|\[[^\]]+\])/).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("[") && part.endsWith("]")) return <mark key={i} className="legal-placeholder">{part}</mark>;
    return part;
  });
}

function block(lines, key) {
  const first = lines[0];
  if (first.startsWith("# ")) return <h2 key={key} className="auth-title">{first.slice(2)}</h2>;
  if (first.startsWith("## ")) return <h3 key={key}>{inline(first.slice(3))}</h3>;
  if (first.startsWith("### ")) return <h4 key={key}>{inline(first.slice(4))}</h4>;
  if (lines.every((l) => l.startsWith("- "))) {
    return <ul key={key} className="legal-list">{lines.map((l, i) => <li key={i}>{inline(l.slice(2))}</li>)}</ul>;
  }
  if (lines.every((l) => /^\d+\. /.test(l))) {
    return <ol key={key} className="legal-list">{lines.map((l, i) => <li key={i}>{inline(l.replace(/^\d+\. /, ""))}</li>)}</ol>;
  }
  return (
    <p key={key}>
      {lines.map((l, i) => (
        <Fragment key={i}>
          {i > 0 && <br />}
          {inline(l.trimEnd())}
        </Fragment>
      ))}
    </p>
  );
}

export default function LegalMarkdown({ source }) {
  const blocks = source.replace(/\r\n/g, "\n").trim().split(/\n\s*\n/).map((b) => b.split("\n"));
  return <article className="legal-document">{blocks.map((lines, i) => block(lines, i))}</article>;
}
