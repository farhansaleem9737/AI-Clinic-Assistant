import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ErrorBoundary from "../components/ErrorBoundary";
import { lazyPage } from "./lazyPage";

const page = { default: () => <h1>Appointments</h1> };
const chunkError = () => new TypeError("Failed to fetch dynamically imported module");

function renderPage(Page) {
  return render(
    <MemoryRouter>
      <ErrorBoundary>
        <Suspense fallback={<p>Loading page</p>}>
          <Page />
        </Suspense>
      </ErrorBoundary>
    </MemoryRouter>
  );
}

describe("page code downloads (D107)", () => {
  it("retries a failed download before showing anything is wrong", async () => {
    const load = vi.fn().mockRejectedValueOnce(chunkError()).mockResolvedValue(page);
    renderPage(lazyPage(load, { retryDelays: [0, 0] }));
    expect(await screen.findByRole("heading", { name: "Appointments" })).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("after the retries, says the page could not be downloaded; Try again downloads it again", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const load = vi.fn().mockRejectedValue(chunkError());
    renderPage(lazyPage(load, { retryDelays: [0, 0] }));
    expect(await screen.findByText("This page could not be downloaded. Check your connection and try again.")).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(3); // bounded: the first try and two retries
    // Reloading is offered, never done automatically (no reload loops).
    expect(screen.getByRole("button", { name: "Reload app" })).toBeInTheDocument();

    // React.lazy alone would keep the failure for good; a fresh attempt now succeeds.
    load.mockResolvedValue(page);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Appointments" })).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(4);
    spy.mockRestore();
  });

  it("a page that fails to render is not reported as a download problem", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const Broken = () => {
      throw new Error("bad data");
    };
    renderPage(lazyPage(() => Promise.resolve({ default: Broken })));
    expect(await screen.findByText("Something went wrong while displaying this page.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reload app" })).not.toBeInTheDocument();
    spy.mockRestore();
  });
});
