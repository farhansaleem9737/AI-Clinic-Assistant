import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";
import { clearDrafts } from "../services/drafts";
import { queryClient } from "../services/queryClient";

// findBy*/waitFor give up after 1s by default, which a busy machine can exceed.
configure({ asyncUtilTimeout: 5000 });

// A mocked failure should show at once, not after the app's automatic retry.
queryClient.setDefaultOptions({ queries: { ...queryClient.getDefaultOptions().queries, retry: false } });

// Every test starts with nothing cached and no drafts.
afterEach(() => {
  cleanup();
  queryClient.clear();
  clearDrafts();
});
