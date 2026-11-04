import { lazy } from "react";

// A page's code failing to download (flaky network, or a new deployment
// replaced the file) is tried twice more before the page reports it.
const RETRY_DELAYS_MS = [500, 1500];
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function importWithRetry(load, delays) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await load();
    } catch (err) {
      if (attempt >= delays.length) {
        const error = new Error("This page's code could not be downloaded.", { cause: err });
        error.name = "ChunkLoadError";
        throw error;
      }
      await wait(delays[attempt]);
    }
  }
}

// Pages whose download failed, each with a way to start over.
const failed = new Set();

/** "Try again" after a failed download (ErrorBoundary): the next render downloads again. */
export function retryFailedPages() {
  for (const startOver of failed) startOver();
  failed.clear();
}

/**
 * React.lazy remembers a failed import for good, so "Try again" could never
 * recover. Here a failure stays failed (the error boundary shows it; nothing
 * retries in a loop) until retryFailedPages() swaps in a fresh lazy
 * component. Nothing reloads the document by itself; the boundary offers that.
 */
export function lazyPage(load, { retryDelays = RETRY_DELAYS_MS } = {}) {
  let Lazy;
  const startOver = () => {
    Lazy = lazy(() =>
      importWithRetry(load, retryDelays).catch((err) => {
        failed.add(startOver);
        throw err;
      })
    );
  };
  startOver();
  return function LazyPage(props) {
    return <Lazy {...props} />;
  };
}
