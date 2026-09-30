import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// findBy*/waitFor give up after 1s by default, which a busy machine can exceed.
configure({ asyncUtilTimeout: 5000 });

afterEach(cleanup);
