import { render } from "@testing-library/react";
import { StrictMode, useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { backoffDelay, createRealtimeClient, RESYNC, socketUrl, STATUS } from "./realtime";

// A stand-in for the browser's WebSocket that the test drives by hand.
class FakeSocket {
  static all = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    this.closedWith = null;
    FakeSocket.all.push(this);
  }
  send(text) {
    this.sent.push(JSON.parse(text));
  }
  close(code) {
    this.closedWith = code;
    this.readyState = 3;
  }
  // test helpers: what the server does
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  message(data) {
    this.onmessage?.({ data: typeof data === "string" ? data : JSON.stringify(data) });
  }
  ready() {
    this.open();
    this.message({ type: "ready", version: 1 });
  }
  drop(code = 1006) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

const flush = () => vi.advanceTimersByTimeAsync(0);
const event = (type, extra = {}) => ({ version: 1, type, resource: type.split(".")[0], resource_id: "r1", payload: {}, ...extra });

let client;
let requestTicket;
let tickets;
const win = new EventTarget();
win.navigator = { onLine: true };
const doc = new EventTarget();
doc.visibilityState = "visible";

function make() {
  tickets = 0;
  requestTicket = vi.fn(async () => `ticket-${++tickets}`);
  client = createRealtimeClient({ requestTicket, WebSocketImpl: FakeSocket, url: () => "ws://test/api/v1/ws", random: () => 0, win, doc });
  return client;
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.all = [];
  win.navigator.onLine = true;
  make();
});
afterEach(() => {
  client.stop();
  vi.useRealTimers();
});

describe("connecting", () => {
  it("asks for a ticket, sends it as the first message and is open on ready", async () => {
    client.start();
    await flush();
    const [ws] = FakeSocket.all;
    expect(ws.url).toBe("ws://test/api/v1/ws"); // no token or ticket in the URL
    ws.open();
    expect(ws.sent).toEqual([{ type: "auth", ticket: "ticket-1" }]);
    expect(client.status).toBe(STATUS.connecting);
    ws.message({ type: "ready", version: 1 });
    expect(client.connected).toBe(true);
  });

  it("start twice still opens one socket", async () => {
    client.start();
    client.start();
    await flush();
    expect(FakeSocket.all).toHaveLength(1);
  });

  it("builds ws:// or wss:// from the API base", () => {
    expect(socketUrl("/api/v1", { href: "http://localhost:5173/dashboard" }, "")).toBe("ws://localhost:5173/api/v1/ws");
    expect(socketUrl("https://api.example.com/api/v1", { href: "https://app.example.com/" }, "")).toBe("wss://api.example.com/api/v1/ws");
    // Production: the socket bypasses Vercel's rewrite and goes to the API host.
    expect(socketUrl("/api/v1", { href: "https://app.vercel.app/" }, "wss://api.onrender.com/api/v1/ws")).toBe("wss://api.onrender.com/api/v1/ws");
  });
});

describe("events", () => {
  it("hands events to each listener once; unknown or malformed messages are ignored", async () => {
    const seen = vi.fn();
    client.subscribe(seen);
    client.subscribe(seen); // the same function twice: still one call per event
    client.start();
    await flush();
    const [ws] = FakeSocket.all;
    ws.ready();
    ws.message(event("appointment.created"));
    ws.message("not json");
    ws.message({ type: "error", code: "UNSUPPORTED_MESSAGE" });
    ws.message({ version: 2, type: "appointment.created" });
    expect(seen).toHaveBeenCalledTimes(1);
    expect(seen.mock.calls[0][0].type).toBe("appointment.created");
  });

  it("a failing listener does not stop the others", async () => {
    const after = vi.fn();
    vi.spyOn(console, "error").mockImplementation(() => {});
    client.subscribe(() => {
      throw new Error("page bug");
    });
    client.subscribe(after);
    client.start();
    await flush();
    FakeSocket.all[0].ready();
    FakeSocket.all[0].message(event("notification.created"));
    expect(after).toHaveBeenCalledOnce();
  });

  it("unsubscribe stops delivery", async () => {
    const seen = vi.fn();
    const off = client.subscribe(seen);
    client.start();
    await flush();
    FakeSocket.all[0].ready();
    off();
    FakeSocket.all[0].message(event("appointment.created"));
    expect(seen).not.toHaveBeenCalled();
  });
});

describe("reconnecting", () => {
  it("reconnects with backoff and a fresh ticket, then asks pages to re-read (resync)", async () => {
    const seen = vi.fn();
    client.subscribe(seen);
    client.start();
    await flush();
    FakeSocket.all[0].ready();
    FakeSocket.all[0].drop(1012); // server restarting
    expect(client.status).toBe(STATUS.connecting);
    await vi.advanceTimersByTimeAsync(499);
    expect(FakeSocket.all).toHaveLength(1); // still waiting (backoff: 500 ms with no jitter)
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.all).toHaveLength(2);
    FakeSocket.all[1].open();
    expect(FakeSocket.all[1].sent[0]).toEqual({ type: "auth", ticket: "ticket-2" });
    FakeSocket.all[1].message({ type: "ready", version: 1 });
    expect(seen).toHaveBeenCalledWith({ type: RESYNC });
  });

  it("the first connection is not a resync", async () => {
    const seen = vi.fn();
    client.subscribe(seen);
    client.start();
    await flush();
    FakeSocket.all[0].ready();
    expect(seen).not.toHaveBeenCalled();
  });

  it("backs off exponentially, with jitter, up to 30 s", () => {
    expect([0, 1, 2, 3].map((n) => backoffDelay(n, () => 0))).toEqual([500, 1000, 2000, 4000]);
    expect(backoffDelay(20, () => 1)).toBe(30000);
    expect(backoffDelay(20, () => 0)).toBe(15000);
  });

  it("a ticket request that fails for the network is retried; a signed-out answer stops it", async () => {
    requestTicket.mockRejectedValueOnce(new Error("Network Error"));
    client.start();
    await flush();
    expect(FakeSocket.all).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(500);
    expect(FakeSocket.all).toHaveLength(1);
    client.stop();

    make();
    requestTicket.mockRejectedValue({ response: { status: 401 } });
    client.start();
    await vi.advanceTimersByTimeAsync(60000);
    expect(requestTicket).toHaveBeenCalledOnce();
    expect(client.status).toBe(STATUS.idle);
  });

  it("a silent connection is detected by the heartbeat and replaced", async () => {
    client.start();
    await flush();
    const [ws] = FakeSocket.all;
    ws.ready();
    await vi.advanceTimersByTimeAsync(25000);
    expect(ws.sent.at(-1)).toEqual({ type: "ping" });
    ws.message({ type: "pong" }); // answered: still fine
    await vi.advanceTimersByTimeAsync(25000);
    await vi.advanceTimersByTimeAsync(10000); // this ping goes unanswered
    expect(ws.closedWith).toBe(1000);
    await vi.advanceTimersByTimeAsync(1000);
    expect(FakeSocket.all).toHaveLength(2);
  });

  it("offline waits for the network; online reconnects at once", async () => {
    client.start();
    await flush();
    FakeSocket.all[0].ready();
    win.navigator.onLine = false;
    win.dispatchEvent(new Event("offline"));
    expect(client.status).toBe(STATUS.offline);
    await vi.advanceTimersByTimeAsync(60000);
    expect(FakeSocket.all).toHaveLength(1);
    win.navigator.onLine = true;
    win.dispatchEvent(new Event("online"));
    await flush();
    expect(FakeSocket.all).toHaveLength(2);
  });
});

describe("stopping", () => {
  it("sign-out closes the socket and nothing reconnects", async () => {
    client.start();
    await flush();
    const [ws] = FakeSocket.all;
    ws.ready();
    client.stop();
    expect(ws.closedWith).toBe(1000);
    expect(client.status).toBe(STATUS.idle);
    await vi.advanceTimersByTimeAsync(120000);
    expect(FakeSocket.all).toHaveLength(1);
  });

  it("a ticket that arrives after stop opens nothing", async () => {
    let answer;
    requestTicket.mockImplementationOnce(() => new Promise((resolve) => (answer = resolve)));
    client.start();
    client.stop();
    answer("late-ticket");
    await flush();
    expect(FakeSocket.all).toHaveLength(0);
  });

  it("React Strict Mode's double mount leaves exactly one open connection", async () => {
    function Live() {
      useEffect(() => {
        client.start();
        return () => client.stop();
      }, []);
      return null;
    }
    render(
      <StrictMode>
        <Live />
      </StrictMode>
    );
    await flush();
    const live = FakeSocket.all.filter((ws) => ws.closedWith === null);
    expect(live).toHaveLength(1);
    expect(requestTicket.mock.calls.length).toBeLessThanOrEqual(2);
  });
});

describe("watching a patient's record and account changes", () => {
  it("one watch message per patient, again after a reconnect; unwatch when the last page stops", async () => {
    client.start();
    await flush();
    FakeSocket.all[0].ready();
    const stopA = client.watch("pat-1");
    const stopB = client.watch("pat-1"); // a second component on the same patient
    expect(FakeSocket.all[0].sent.filter((m) => m.type === "watch")).toEqual([{ type: "watch", patient_id: "pat-1" }]);

    FakeSocket.all[0].drop(1012);
    await vi.advanceTimersByTimeAsync(500);
    FakeSocket.all[1].ready();
    expect(FakeSocket.all[1].sent.filter((m) => m.type === "watch")).toEqual([{ type: "watch", patient_id: "pat-1" }]);

    stopA();
    expect(FakeSocket.all[1].sent.some((m) => m.type === "unwatch")).toBe(false); // still watched by B
    stopB();
    stopB(); // calling it twice changes nothing
    expect(FakeSocket.all[1].sent.filter((m) => m.type === "unwatch")).toEqual([{ type: "unwatch", patient_id: "pat-1" }]);
  });

  it("a watch made before the socket is open is sent once it is ready", async () => {
    client.watch("pat-2");
    client.start();
    await flush();
    FakeSocket.all[0].open();
    expect(FakeSocket.all[0].sent).toEqual([{ type: "auth", ticket: "ticket-1" }]);
    FakeSocket.all[0].message({ type: "ready", version: 1 });
    expect(FakeSocket.all[0].sent.at(-1)).toEqual({ type: "watch", patient_id: "pat-2" });
  });

  it("roles changed: listeners hear account.changed and the socket reconnects promptly", async () => {
    const seen = vi.fn();
    client.subscribe(seen);
    client.start();
    await flush();
    FakeSocket.all[0].ready();
    FakeSocket.all[0].drop(4000);
    expect(seen).toHaveBeenCalledWith({ type: "account.changed" });
    await vi.advanceTimersByTimeAsync(500);
    expect(FakeSocket.all).toHaveLength(2);
  });
});
