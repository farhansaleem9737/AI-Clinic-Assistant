import { act, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ThinkingWords from "./ThinkingWords";
import { LEAVE_MS, REVEAL_MS, THINKING_WORDS, WORD_MS } from "./thinkingWordList";

const node = () => document.querySelector(".ai-thinking-word");
// What is visible: the revealed letters (the unrevealed rest is laid out but hidden).
const visible = () => {
  const copy = node().cloneNode(true);
  copy.querySelector(".ai-thinking-rest")?.remove();
  return copy.textContent;
};
const full = () => !node().querySelector(".ai-thinking-rest");
const word = () => node().textContent.replace(/…$/, "");
// Advances the fake clock by `ms` in small steps, so each timer React schedules after an update also runs.
const runFor = (ms, step = 1) => {
  for (let left = ms; left > 0; left -= step) act(() => vi.advanceTimersByTime(Math.min(step, left)));
};
// Runs timers one by one until the word changes; returns how long that took.
const untilNextWord = () => {
  const [from, start] = [word(), Date.now()];
  while (word() === from) act(() => vi.advanceTimersToNextTimer());
  return Date.now() - start;
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  delete window.matchMedia;
});

describe("ThinkingWords", () => {
  it("starts with Thinking, under one stable status for screen readers", () => {
    render(<ThinkingWords />);
    const status = screen.getByRole("status", { name: "Assistant is preparing a response" });
    expect(word()).toBe("Thinking");
    expect(node()).toHaveAttribute("aria-hidden", "true"); // letters and words are not announced
    expect(status).toHaveTextContent("Thinking…");
  });

  it("types the word out letter by letter within about 300 ms, keeping its width", () => {
    render(<ThinkingWords />);
    const started = Date.now();
    const steps = [visible()];
    // The hidden rest reserves the full word's width from the first letter.
    expect(node().textContent).toBe("Thinking…");
    while (!full()) {
      runFor(1);
      if (visible() !== steps.at(-1)) steps.push(visible());
    }
    expect(steps).toEqual(["T", "Th", "Thi", "Thin", "Think", "Thinki", "Thinkin", "Thinking…"]);
    const took = Date.now() - started;
    expect(took).toBeGreaterThanOrEqual(250);
    expect(took).toBeLessThanOrEqual(350);
  });

  it("keeps the full word on screen for the rest of the 3 s cycle, then shows a different word", () => {
    render(<ThinkingWords />);
    runFor(REVEAL_MS + 5);
    expect(full()).toBe(true);
    runFor(WORD_MS - LEAVE_MS - REVEAL_MS - 15);
    expect(visible()).toBe("Thinking…");
    expect(node()).not.toHaveClass("leaving");
    runFor(15);
    expect(node()).toHaveClass("leaving"); // the existing short fade before the next word
    runFor(LEAVE_MS);
    expect(word()).not.toBe("Thinking");
    expect(THINKING_WORDS).toContain(word());
    expect(visible()).toBe(word()[0]); // the next word starts its own reveal
    runFor(REVEAL_MS + 5);
    expect(full()).toBe(true);
  });

  it("changes word every 3000 ms, never twice in a row nor before the others have had a turn", () => {
    render(<ThinkingWords />);
    const seen = [word()];
    for (let i = 0; i < THINKING_WORDS.length + 5; i++) {
      expect(untilNextWord()).toBe(WORD_MS);
      seen.push(word());
    }
    for (let i = 1; i < seen.length; i++) expect(seen[i]).not.toBe(seen[i - 1]);
    const round = seen.slice(1, THINKING_WORDS.length + 1);
    expect(new Set(round).size).toBe(THINKING_WORDS.length);
    expect(THINKING_WORDS).not.toContain("Clauding");
    expect(THINKING_WORDS).not.toContain("Gitifying");
  });

  it("with reduced motion shows each word whole, still every 3000 ms", () => {
    window.matchMedia = () => ({ matches: true });
    render(<ThinkingWords />);
    expect(visible()).toBe("Thinking…");
    runFor(WORD_MS - 10);
    expect(word()).toBe("Thinking");
    runFor(10);
    expect(word()).not.toBe("Thinking");
    expect(full()).toBe(true);
  });

  it("leaves no timer running once removed", () => {
    const { unmount } = render(<ThinkingWords />);
    runFor(4500);
    expect(vi.getTimerCount()).toBe(1); // one timer at a time, never a growing set
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("styles: no movement with reduced motion, hidden letters keep their space, no overflow", () => {
    const css = readFileSync("src/index.css", "utf8");
    const block = css.slice(css.indexOf(".ai-thinking {"), css.indexOf("ai-history-empty"));
    expect(block).toMatch(/prefers-reduced-motion: reduce\)\s*\{\s*\.ai-thinking-word \{ animation: none; transition: none; \}/);
    expect(css).toMatch(/\.ai-thinking-rest \{ visibility: hidden; \}/);
    expect(css).toMatch(/\.ai-thinking-word \{[^}]*white-space: nowrap; text-overflow: ellipsis;/);
    expect(css).toMatch(/\.ai-thinking \{[^}]*max-width: 100%; height: 1\.5rem;[^}]*overflow: hidden;/);
    expect(css).not.toMatch(/\.ai-typing/);
  });
});
