import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SafeMarkdown from "../components/assistant/SafeMarkdown";
import { withoutInternalNotes } from "./assistant";

// D133: answers saved before the server removed internal notes may still contain them.
const LEAKED =
  "Here are the dermatologists.\n[Shown to the user: list of 3 doctors]\n" +
  "Shown to the user: doctors in this order: 1. Dr. Emily Carter (doctor_id 01a0f29d-c6b3-72cb-b652-0e8508aca522, Dermatology)\n" +
  "Would you like to book with one of them?";

describe("internal notes in assistant answers", () => {
  it("are removed, and ordinary text is left alone", () => {
    const clean = withoutInternalNotes(LEAKED);
    expect(clean).not.toMatch(/shown to the user/i);
    expect(clean).not.toMatch(/doctor_id|01a0f29d/);
    expect(clean).toContain("Here are the dermatologists.");
    expect(clean).toContain("Would you like to book with one of them?");
    const ordinary = "I found three dermatologists. You can choose one below (or ask for the earliest time).";
    expect(withoutInternalNotes(ordinary)).toBe(ordinary);
  });

  it("are never rendered in the chat", () => {
    const { container } = render(<SafeMarkdown text={LEAKED} />);
    expect(container.textContent).not.toMatch(/shown to the user|doctor_id|01a0f29d/i);
    expect(container.textContent).toContain("Would you like to book with one of them?");
  });
});
