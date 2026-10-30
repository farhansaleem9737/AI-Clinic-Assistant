import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken } from "./api";
import { streamAssistantMessage } from "./aiService";

// A fetch Response whose body arrives in the given pieces (split anywhere, like a network).
function sse(pieces, status = 200) {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const piece of pieces) controller.enqueue(encoder.encode(piece));
      controller.close();
    },
  });
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

const DONE = { conversation: { id: "c-1" }, user_message: { id: "u" }, assistant_message: { id: "a", content: "Hello there" } };

beforeEach(() => {
  setAccessToken("token-1");
  globalThis.fetch = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

describe("streamAssistantMessage", () => {
  it("sends the token, passes each delta on, and resolves with the saved messages", async () => {
    const stream = 'event: delta\ndata: {"text":"Hel"}\n\nevent: delta\ndata: {"text":"lo there"}\n\nevent: done\ndata: ' + JSON.stringify(DONE) + "\n\n";
    // Split mid-event, as a network may.
    fetch.mockResolvedValue(sse([stream.slice(0, 17), stream.slice(17, 60), stream.slice(60)]));
    const deltas = [];
    const result = await streamAssistantMessage({ text: "hi" }, { onDelta: (t) => deltas.push(t) });
    expect(deltas).toEqual(["Hel", "lo there"]);
    expect(result).toEqual(DONE);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toMatch(/\/ai\/messages\/stream$/);
    expect(init.headers.Authorization).toBe("Bearer token-1");
    expect(JSON.parse(init.body)).toEqual({ text: "hi" });
  });

  it("an error event rejects like an API error", async () => {
    fetch.mockResolvedValue(sse(['event: error\ndata: {"code":"AI_RATE_LIMITED","message":"busy"}\n\n']));
    await expect(streamAssistantMessage({ text: "hi" })).rejects.toEqual({
      response: { status: 503, data: { error: { code: "AI_RATE_LIMITED", message: "busy" } } },
    });
  });

  it("a usage-limit error event rejects as 429 with the server's message", async () => {
    fetch.mockResolvedValue(sse(['event: error\ndata: {"code":"AI_USER_DAILY_LIMIT","message":"limit reached"}\n\n']));
    await expect(streamAssistantMessage({ text: "hi" })).rejects.toEqual({
      response: { status: 429, data: { error: { code: "AI_USER_DAILY_LIMIT", message: "limit reached" } } },
    });
  });

  it("a non-streaming error response keeps its status and body", async () => {
    fetch.mockResolvedValue(new Response(JSON.stringify({ error: { code: "AI_NOT_CONFIGURED", message: "not set up" } }), { status: 503 }));
    await expect(streamAssistantMessage({ text: "hi" })).rejects.toMatchObject({ response: { status: 503, data: { error: { code: "AI_NOT_CONFIGURED" } } } });
  });

  it("a stream that ends without done is reported, not treated as an answer", async () => {
    fetch.mockResolvedValue(sse(['event: delta\ndata: {"text":"half"}\n\n']));
    await expect(streamAssistantMessage({ text: "hi" })).rejects.toMatchObject({ response: { status: 503 } });
  });
});
