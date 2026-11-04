import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { invalidateAfterChange, queryClient, setCacheOwner } from "../services/queryClient";
import { useFetch } from "./useFetch";

function Probe({ fetcher, query, deps = [], label = "probe" }) {
  const [attempt, setAttempt] = useState(0);
  const { data, loading, error } = useFetch(fetcher, deps, { query, refresh: attempt });
  return (
    <section aria-label={label} aria-busy={loading}>
      {error ? <p role="alert">{error}</p> : <p>{data ?? "nothing yet"}</p>}
      <button type="button" onClick={() => setAttempt((n) => n + 1)}>
        Refresh {label}
      </button>
    </section>
  );
}
const answer = (value) => Promise.resolve({ data: value });
const deferred = () => {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve: (value) => resolve({ data: value }) };
};
const isInvalidated = (name) => queryClient.getQueryCache().find({ queryKey: [null, name] })?.state.isInvalidated;

afterEach(() => setCacheOwner(null));

describe("cached page data (D107)", () => {
  it("a page opened again shows its data at once, with no request while it is fresh", async () => {
    const fetcher = vi.fn(() => answer("3 appointments"));
    const { unmount } = render(<Probe fetcher={fetcher} query="appointments/list" />);
    expect(await screen.findByText("3 appointments")).toBeInTheDocument();
    unmount();

    render(<Probe fetcher={fetcher} query="appointments/list" />);
    // On the first render: no skeleton, no loading state.
    expect(screen.getByText("3 appointments")).toBeInTheDocument();
    expect(screen.getByLabelText("probe")).toHaveAttribute("aria-busy", "false");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("out-of-date data stays on screen while it refreshes in the background", async () => {
    const fetcher = vi.fn(() => answer("09:00 free"));
    const { unmount } = render(<Probe fetcher={fetcher} query="availability/doc-1" />);
    expect(await screen.findByText("09:00 free")).toBeInTheDocument();
    unmount();

    const next = deferred();
    fetcher.mockReturnValue(next.promise);
    render(<Probe fetcher={fetcher} query="availability/doc-1" />); // availability is never fresh
    expect(screen.getByText("09:00 free")).toBeInTheDocument();
    expect(screen.getByLabelText("probe")).toHaveAttribute("aria-busy", "false");
    expect(fetcher).toHaveBeenCalledTimes(2);
    await act(async () => next.resolve("09:30 free"));
    expect(await screen.findByText("09:30 free")).toBeInTheDocument();
  });

  it("unnamed calls are not cached: they load again on every visit", async () => {
    const fetcher = vi.fn(() => answer("checked"));
    const { unmount } = render(<Probe fetcher={fetcher} />);
    expect(await screen.findByText("checked")).toBeInTheDocument();
    unmount();
    render(<Probe fetcher={fetcher} />);
    expect(screen.getByText("nothing yet")).toBeInTheDocument();
    expect(await screen.findByText("checked")).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("sends one request when several parts of a page need the same data", async () => {
    const fetcher = vi.fn(() => answer("summary"));
    render(
      <>
        <Probe fetcher={fetcher} query="dashboard/summary" label="first" />
        <Probe fetcher={fetcher} query="dashboard/summary" label="second" />
      </>
    );
    expect(await screen.findAllByText("summary")).toHaveLength(2);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("Try again re-fetches and shows loading until the answer arrives", async () => {
    const fetcher = vi.fn(() => Promise.reject({ response: { status: 500, data: { error: { message: "Database unavailable" } } } }));
    render(<Probe fetcher={fetcher} query="appointments/list" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Database unavailable");
    const next = deferred();
    fetcher.mockReturnValue(next.promise);
    await userEvent.click(screen.getByRole("button", { name: "Refresh probe" }));
    expect(screen.getByLabelText("probe")).toHaveAttribute("aria-busy", "true");
    await act(async () => next.resolve("2 appointments"));
    expect(await screen.findByText("2 appointments")).toBeInTheDocument();
  });

  it("a successful change marks only the data it affects as out of date", async () => {
    const { unmount } = render(
      <>
        <Probe fetcher={() => answer("list")} query="appointments/list" label="a" />
        <Probe fetcher={() => answer("week")} query="schedule/weekly" label="b" />
        <Probe fetcher={() => answer("departments")} query="departments/public" label="c" />
      </>
    );
    expect(await screen.findByText("departments")).toBeInTheDocument();
    unmount();

    invalidateAfterChange("/api/v1/appointments/appt-1/status");
    expect(isInvalidated("appointments/list")).toBe(true);
    expect(isInvalidated("schedule/weekly")).toBe(true); // the doctor's booked slots changed
    expect(isInvalidated("departments/public")).toBe(false);
  });

  it("assistant messages change nothing; a confirmed assistant action may change anything", async () => {
    const { unmount } = render(<Probe fetcher={() => answer("departments")} query="departments/public" />);
    expect(await screen.findByText("departments")).toBeInTheDocument();
    unmount();
    invalidateAfterChange("/api/v1/ai/messages");
    expect(isInvalidated("departments/public")).toBe(false);
    invalidateAfterChange("/api/v1/ai/conversations/c-1/messages/m-1/decision");
    expect(isInvalidated("departments/public")).toBe(true);
  });

  it("another user never sees the previous user's data", async () => {
    setCacheOwner("patient-1");
    const fetcher = vi.fn(() => answer("patient 1 appointments"));
    const { unmount } = render(<Probe fetcher={fetcher} query="appointments/list" />);
    expect(await screen.findByText("patient 1 appointments")).toBeInTheDocument();
    unmount();

    setCacheOwner("patient-2");
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
    fetcher.mockReturnValue(answer("patient 2 appointments"));
    render(<Probe fetcher={fetcher} query="appointments/list" />);
    expect(screen.queryByText("patient 1 appointments")).not.toBeInTheDocument();
    expect(await screen.findByText("patient 2 appointments")).toBeInTheDocument();
  });
});
