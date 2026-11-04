import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDraft } from "../hooks/useDraft";
import { clearDrafts, loadStoredDraft, setDraftOwner, storeDraft } from "./drafts";

function Search({ draftKey = "patients:q" }) {
  const [q, setQ] = useDraft(draftKey, "");
  return <input aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} />;
}
const always = () => true;

afterEach(() => {
  setDraftOwner(null);
  vi.useRealTimers();
});

describe("drafts (D107)", () => {
  it("unfinished input survives leaving the page and coming back", async () => {
    setDraftOwner("u-1");
    const { unmount } = render(<Search />);
    await userEvent.type(screen.getByLabelText("Search"), "khan");
    unmount();
    render(<Search />);
    expect(screen.getByLabelText("Search")).toHaveValue("khan");
  });

  it("another user, or signing out, starts empty", async () => {
    setDraftOwner("u-1");
    const { unmount } = render(<Search />);
    await userEvent.type(screen.getByLabelText("Search"), "khan");
    unmount();
    setDraftOwner("u-2");
    const second = render(<Search />);
    expect(screen.getByLabelText("Search")).toHaveValue("");
    second.unmount();
    setDraftOwner("u-1"); // back to the first user: memory was emptied on the switch
    render(<Search />);
    expect(screen.getByLabelText("Search")).toHaveValue("");
  });

  it("without a key it is plain state", async () => {
    const { unmount } = render(<Search draftKey={null} />);
    await userEvent.type(screen.getByLabelText("Search"), "khan");
    unmount();
    render(<Search draftKey={null} />);
    expect(screen.getByLabelText("Search")).toHaveValue("");
  });

  it("a value kept for a reload comes back only for its user, valid and unexpired", () => {
    vi.useFakeTimers();
    setDraftOwner("u-1");
    storeDraft("booking:", { doctorId: "doc-1", step: 2 }, 60_000);
    expect(loadStoredDraft("booking:", always)).toEqual({ doctorId: "doc-1", step: 2 });
    expect(loadStoredDraft("booking:", (v) => v.step === 3)).toBeNull(); // fails validation: removed
    expect(loadStoredDraft("booking:", always)).toBeNull();

    storeDraft("booking:", { doctorId: "doc-1", step: 2 }, 60_000);
    setDraftOwner("u-2");
    expect(loadStoredDraft("booking:", always)).toBeNull(); // another user's key

    setDraftOwner("u-1");
    vi.advanceTimersByTime(60_001);
    expect(loadStoredDraft("booking:", always)).toBeNull(); // expired
  });

  it("ignores malformed or old-version stored drafts and nothing is kept without a user", () => {
    setDraftOwner("u-1");
    sessionStorage.setItem("clinic-draft:u-1:booking:", "{not json");
    expect(loadStoredDraft("booking:", always)).toBeNull();
    sessionStorage.setItem("clinic-draft:u-1:booking:", JSON.stringify({ v: 0, owner: "u-1", expires: Date.now() + 1000, value: {} }));
    expect(loadStoredDraft("booking:", always)).toBeNull();
    expect(sessionStorage.getItem("clinic-draft:u-1:booking:")).toBeNull();

    setDraftOwner(null);
    storeDraft("booking:", { doctorId: "doc-1" }, 60_000);
    expect(Object.keys(sessionStorage)).toEqual([]);
  });

  it("signing out removes every stored draft", () => {
    setDraftOwner("u-1");
    storeDraft("booking:", { doctorId: "doc-1" }, 60_000);
    sessionStorage.setItem("unrelated", "kept");
    clearDrafts();
    expect(Object.keys(sessionStorage)).toEqual(["unrelated"]);
    sessionStorage.removeItem("unrelated");
  });
});
