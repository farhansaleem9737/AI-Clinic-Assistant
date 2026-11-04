import { useEffect, useState } from "react";
import { LEAVE_MS, REVEAL_MS, shuffled, WORD_MS } from "./thinkingWordList";

const reducedMotion = () => Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
// Letters shown when a word appears: the first one, or all of them without motion.
const start = (word) => (reducedMotion() ? word.length : 1);

/**
 * Shown in the assistant's reply bubble until the first words of the answer
 * arrive; it unmounts then (and on completion, error or cancel), which stops
 * its timer. Each word types itself out within REVEAL_MS, stays, then fades
 * before the next. Screen readers hear one stable status, not every word.
 */
export default function ThinkingWords() {
  const [state, setState] = useState(() => ({ word: "Thinking", shown: start("Thinking"), leaving: false, deck: null }));

  useEffect(() => {
    const { word, shown, leaving } = state;
    // One timer at a time: the next letter, the fade-out, or the next word.
    // The whole cycle (reveal, full word, fade) takes WORD_MS.
    const revealed = start(word) < word.length;
    const delay = leaving
      ? LEAVE_MS
      : shown < word.length
        ? // Whole milliseconds that add up to exactly REVEAL_MS for the word.
          Math.round((REVEAL_MS * shown) / (word.length - 1)) - Math.round((REVEAL_MS * (shown - 1)) / (word.length - 1))
        : WORD_MS - LEAVE_MS - (revealed ? REVEAL_MS : 0);
    const timer = setTimeout(
      () =>
        setState((current) => {
          if (current.leaving) {
            const next = current.deck?.length ? current.deck : shuffled(current.word);
            return { word: next[0], shown: start(next[0]), leaving: false, deck: next.slice(1) };
          }
          if (current.shown < current.word.length) return { ...current, shown: current.shown + 1 };
          return { ...current, leaving: true };
        }),
      delay
    );
    return () => clearTimeout(timer);
  }, [state]);

  const { word, shown, leaving } = state;
  return (
    <span className="ai-thinking" role="status" aria-label="Assistant is preparing a response">
      <span key={word} className={`ai-thinking-word${leaving ? " leaving" : ""}`} aria-hidden="true">
        {word.slice(0, shown)}
        {/* The rest is laid out but invisible, so the bubble keeps one width while the letters appear. */}
        {shown < word.length ? <span className="ai-thinking-rest">{word.slice(shown)}…</span> : "…"}
      </span>
    </span>
  );
}
