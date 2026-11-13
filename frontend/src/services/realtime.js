import api, { apiUrl } from "./api";

/**
 * Live updates (D122): one WebSocket per browser tab, shared by every page.
 *
 * Events only say what changed ({ type, resource, resource_id, payload });
 * pages re-read the data through the REST API, which stays the source of
 * truth. Nothing depends on the socket: when it is down the app works as
 * before (pages load on open; the bell and queue fall back to polling), and
 * after every reconnect listeners get a "resync" event to re-read what they show.
 *
 * Opening: POST /realtime/ticket (normal Bearer auth) → a one-time ticket,
 * sent as the socket's first message. No token ever goes in the URL.
 */

export const STATUS = { idle: "idle", connecting: "connecting", open: "open", offline: "offline" };
export const RESYNC = "resync"; // a pseudo-event sent to listeners after a reconnect
// A pseudo-event: the account's roles changed (the server asked for a reconnect);
// the signed-in user is re-read so menus and permissions follow.
export const ACCOUNT_CHANGED = "account.changed";

const HEARTBEAT_MS = 25_000; // ping this often…
const PONG_TIMEOUT_MS = 10_000; // …and give up on the socket if no pong comes back in time
const BACKOFF_BASE_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;
const TOO_MANY = 4429;
const RECONNECT = 4000;

/**
 * Where the socket connects. VITE_REALTIME_URL when set: in production the
 * REST calls go through Vercel's /api rewrite, which cannot carry a WebSocket,
 * so the socket goes straight to the API host (wss://<api-host>/api/v1/ws).
 * Otherwise ws(s)://<host>/api/v1/ws from the API base URL (development: the
 * Vite proxy forwards it).
 *
 * null when it cannot work (D130): a production build with a relative API base
 * and no VITE_REALTIME_URL would send the handshake through the Vercel rewrite,
 * which drops the Upgrade header, so the API answers 404 and the tab retried
 * for ever. The app then simply stays on its polling fallback.
 */
export function socketUrl(
  base = apiUrl(""),
  location = window.location,
  configured = import.meta.env.VITE_REALTIME_URL,
  production = import.meta.env.PROD,
) {
  if (configured) return configured;
  if (production && !/^https?:\/\//i.test(base)) return null;
  const absolute = new URL(base, location.href);
  absolute.protocol = absolute.protocol === "https:" ? "wss:" : "ws:";
  absolute.pathname = `${absolute.pathname.replace(/\/$/, "")}/ws`;
  absolute.search = "";
  return absolute.toString();
}

/** Full jitter: a random wait up to the exponential cap, so clients don't reconnect in step. */
export function backoffDelay(attempt, random = Math.random) {
  const cap = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** attempt);
  return Math.round(cap / 2 + (random() * cap) / 2);
}

export function createRealtimeClient({
  requestTicket = () => api.post("/realtime/ticket").then((res) => res.data.ticket),
  WebSocketImpl = globalThis.WebSocket,
  url = () => socketUrl(),
  random = Math.random,
  win = typeof window === "undefined" ? null : window,
  doc = typeof document === "undefined" ? null : document,
} = {}) {
  const listeners = new Set();
  const statusListeners = new Set();
  let status = STATUS.idle;
  let started = false;
  let generation = 0; // bumped by stop(): late callbacks of an old socket are ignored
  let socket = null;
  let attempt = 0;
  let everOpened = false;
  let retryTimer = null;
  let heartbeatTimer = null;
  let pongTimer = null;
  const watches = new Map(); // patient id → how many components watch that record

  const setStatus = (next) => {
    if (next === status) return;
    status = next;
    statusListeners.forEach((fn) => fn(status));
  };
  const dispatch = (event) => {
    listeners.forEach((fn) => {
      try {
        fn(event);
      } catch (err) {
        console.error("realtime listener failed", err); // one page's bug must not stop the others
      }
    });
  };
  const clearTimers = () => {
    clearTimeout(retryTimer);
    clearInterval(heartbeatTimer);
    clearTimeout(pongTimer);
    retryTimer = heartbeatTimer = pongTimer = null;
  };
  const dropSocket = () => {
    if (!socket) return;
    const old = socket;
    socket = null;
    old.onopen = old.onmessage = old.onclose = old.onerror = null;
    try {
      old.close(1000);
    } catch {
      /* already closed */
    }
  };
  const online = () => !win?.navigator || win.navigator.onLine !== false;

  const scheduleRetry = (minimum = 0) => {
    if (!started) return;
    clearTimers();
    if (!online()) {
      setStatus(STATUS.offline); // the "online" event reconnects
      return;
    }
    setStatus(STATUS.connecting);
    retryTimer = setTimeout(connect, Math.max(minimum, backoffDelay(attempt, random)));
    attempt += 1;
  };

  const startHeartbeat = (ws) => {
    heartbeatTimer = setInterval(() => {
      if (ws.readyState !== 1) return;
      ws.send('{"type":"ping"}');
      clearTimeout(pongTimer);
      // No answer: the connection is dead even if the browser hasn't noticed (sleep, network change).
      pongTimer = setTimeout(() => {
        dropSocket();
        scheduleRetry();
      }, PONG_TIMEOUT_MS);
    }, HEARTBEAT_MS);
  };

  async function connect() {
    if (!started || socket) return;
    const target = url();
    if (!target) {
      setStatus(STATUS.idle); // live updates are not configured for this deployment: never retry
      return;
    }
    const mine = generation;
    setStatus(STATUS.connecting);
    let ticket;
    try {
      ticket = await requestTicket();
    } catch (err) {
      if (mine !== generation) return;
      const code = err?.response?.status;
      // Signed out (the API client handles the session) or live updates switched off: stop trying.
      if (code === 401 || code === 403 || code === 404) {
        setStatus(STATUS.idle);
        return;
      }
      scheduleRetry();
      return;
    }
    if (mine !== generation || !started) return;

    const ws = new WebSocketImpl(target);
    socket = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", ticket }));
    ws.onmessage = (message) => {
      let data;
      try {
        data = JSON.parse(message.data);
      } catch {
        return; // not ours
      }
      if (data?.type === "ready") {
        const reconnected = everOpened;
        everOpened = true;
        attempt = 0;
        setStatus(STATUS.open);
        startHeartbeat(ws);
        // Watches belong to a connection: ask again on every new one (the server re-checks each).
        for (const patientId of watches.keys()) ws.send(JSON.stringify({ type: "watch", patient_id: patientId }));
        if (reconnected) dispatch({ type: RESYNC }); // events may have been missed while away
      } else if (data?.type === "pong") {
        clearTimeout(pongTimer);
      } else if (data?.version === 1 && typeof data.type === "string" && data.type.includes(".")) {
        dispatch(data);
      } // anything else (errors, unknown versions) is ignored
    };
    ws.onclose = (event) => {
      if (socket !== ws) return;
      socket = null;
      clearTimers();
      if (event.code === RECONNECT) {
        attempt = 0; // roles changed: reconnect promptly, and re-read who is signed in
        dispatch({ type: ACCOUNT_CHANGED });
      }
      // Too many tabs: wait the longest; a refused ticket: a new one after the usual backoff.
      scheduleRetry(event.code === TOO_MANY ? BACKOFF_MAX_MS : 0);
    };
    ws.onerror = () => {}; // followed by onclose
  }

  const onOnline = () => {
    if (!started || socket) return;
    attempt = 0;
    clearTimers();
    connect();
  };
  const onOffline = () => {
    if (!started) return;
    clearTimers();
    dropSocket();
    setStatus(STATUS.offline);
  };
  // Back to a tab that slept: reconnect now instead of waiting out the backoff.
  const onVisible = () => {
    if (started && doc?.visibilityState === "visible" && !socket) onOnline();
  };

  return {
    /** Connect (signed in). Calling it again while started does nothing. */
    start() {
      if (started) return;
      started = true;
      attempt = 0;
      win?.addEventListener("online", onOnline);
      win?.addEventListener("offline", onOffline);
      doc?.addEventListener("visibilitychange", onVisible);
      connect();
    },
    /** Disconnect (sign-out, layout unmount). No reconnect afterwards. */
    stop() {
      if (!started) return;
      started = false;
      generation += 1;
      everOpened = false;
      clearTimers();
      dropSocket();
      win?.removeEventListener("online", onOnline);
      win?.removeEventListener("offline", onOffline);
      doc?.removeEventListener("visibilitychange", onVisible);
      setStatus(STATUS.idle);
    },
    /** Listen to events (and RESYNC). The same function twice is still called once. Returns the unsubscribe. */
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    /**
     * Hear changes to one patient's health record (a treating doctor's open
     * patient page). The server allows it only to those who may read the record.
     * Returns the function that stops watching.
     */
    watch(patientId) {
      const count = watches.get(patientId) ?? 0;
      watches.set(patientId, count + 1);
      if (count === 0 && socket?.readyState === 1 && status === STATUS.open) {
        socket.send(JSON.stringify({ type: "watch", patient_id: patientId }));
      }
      let done = false;
      return () => {
        if (done) return;
        done = true;
        const left = (watches.get(patientId) ?? 1) - 1;
        if (left > 0) {
          watches.set(patientId, left);
          return;
        }
        watches.delete(patientId);
        if (socket?.readyState === 1) socket.send(JSON.stringify({ type: "unwatch", patient_id: patientId }));
      };
    },
    onStatus(listener) {
      statusListeners.add(listener);
      return () => statusListeners.delete(listener);
    },
    get status() {
      return status;
    },
    get connected() {
      return status === STATUS.open;
    },
  };
}

// The app's one client.
const realtime = createRealtimeClient();
export default realtime;
