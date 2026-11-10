import { describe, expect, it } from "vitest";
import { getErrorMessage, isNetworkError, NETWORK_MESSAGE } from "./api";

describe("getErrorMessage", () => {
  it("a server fault uses the page's own words and a short reference, never the generic server text", () => {
    const err = { response: { status: 500, data: { error: { code: "INTERNAL_ERROR", message: "An unexpected error occurred", request_id: "9411df26482d" } } } };
    expect(getErrorMessage(err, "We couldn't load your appointments. Please try again.")).toBe(
      "We couldn't load your appointments. Please try again. (reference 9411df26)"
    );
  });

  it("no answer at all is a connection problem", () => {
    const err = { request: {}, message: "Network Error", code: "ERR_NETWORK" };
    expect(isNetworkError(err)).toBe(true);
    expect(getErrorMessage(err, "x")).toBe(NETWORK_MESSAGE);
  });

  it("known errors keep the server's specific, safe message", () => {
    const update = { response: { status: 503, data: { error: { code: "SCHEMA_OUT_OF_DATE", message: "This part of the clinic system is being updated. Please try again a little later." } } } };
    expect(getErrorMessage(update, "x")).toMatch(/being updated/);
    const taken = { response: { status: 409, data: { error: { code: "SLOT_UNAVAILABLE", message: "That time is not available" } } } };
    expect(getErrorMessage(taken, "x")).toBe("That time is not available");
    expect(getErrorMessage(new Error("boom"), "fallback")).toBe("fallback");
  });
});
