import axios from "axios";
import { invalidateAfterChange } from "./queryClient";

// Set in frontend/.env (see .env.example). In development this is the relative
// path "/api/v1": the Vite dev server proxies it to FastAPI, so the page and the
// API share one origin and the SameSite=Strict session cookie is always sent.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;
if (!API_BASE_URL) {
  throw new Error("VITE_API_BASE_URL is not set. Copy frontend/.env.example to frontend/.env.");
}

const CSRF_COOKIE = "csrf_token";
const CSRF_HEADER = "X-CSRF-Token";

const api = axios.create({ baseURL: API_BASE_URL });

// A successful change (anything but GET) marks the cached data it affects as
// out of date (services/queryClient.js). Only after the server confirmed it:
// a failed request changes nothing.
api.interceptors.response.use((response) => {
  const method = (response.config?.method ?? "get").toLowerCase();
  if (method !== "get" && method !== "head") invalidateAfterChange(response.config.url);
  return response;
});

// The access token lives only in memory — never in localStorage, where any
// injected script could read it. A page reload loses it on purpose; the
// HttpOnly refresh cookie restores the session (see restoreSession).
let accessToken = null;
let onSessionExpired = () => {};

export function setAccessToken(token) {
  accessToken = token;
}

// For the few calls that cannot go through axios (streamed responses read with fetch).
export const getAccessToken = () => accessToken;
export const apiUrl = (path) => `${API_BASE_URL}${path}`;

export function setSessionExpiredHandler(handler) {
  onSessionExpired = handler;
}

function readCookie(name) {
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

// The CSRF cookie is set and cleared together with the HttpOnly refresh
// cookie, so its presence tells us whether a session may exist.
export function mayHaveSession() {
  return readCookie(CSRF_COOKIE) !== null;
}

// Headers for the endpoints authenticated by the refresh cookie (double-submit CSRF).
export function csrfHeaders() {
  const token = readCookie(CSRF_COOKIE);
  return token ? { [CSRF_HEADER]: token } : {};
}

// Single-flight: however many requests hit a 401 at once, only one refresh
// call is made. Parallel refreshes would rotate the token several times and
// trip the server's reuse detection.
let refreshInFlight = null;

export function refreshAccessToken() {
  if (!refreshInFlight) {
    refreshInFlight = axios
      .post(`${API_BASE_URL}/auth/refresh`, null, { headers: csrfHeaders() })
      .then((res) => {
        setAccessToken(res.data.access_token);
        return res.data.access_token;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    // A 401 from these means "bad credentials/session", not "access token expired".
    const isSessionCall = /^\/auth\/(login|register|refresh|logout)/.test(original?.url ?? "");

    if (error.response?.status === 401 && original && !original._retry && !isSessionCall) {
      original._retry = true;
      try {
        const token = await refreshAccessToken();
        original.headers.Authorization = `Bearer ${token}`;
        return api(original);
      } catch {
        setAccessToken(null);
        onSessionExpired();
      }
    }
    return Promise.reject(error);
  }
);

// The backend returns every error as
//   {"error": {"code", "message", "details", "request_id"}}
// This turns one into text a page can show.
export const NETWORK_MESSAGE = "We couldn't connect to the server. Please try again.";

/** True when the request never got an answer (offline, server down, timeout). */
export const isNetworkError = (err) => Boolean(err && !err.response && (err.request || err.code === "ERR_NETWORK"));

/**
 * The message to show for a failed request. A server fault ("INTERNAL_ERROR")
 * is shown with the page's own wording (`fallback`, e.g. "We couldn't load your
 * appointments") and a short reference staff can find in the logs, never the
 * server's generic text; no answer at all is a connection message.
 */
export function getErrorMessage(err, fallback = "Something went wrong") {
  if (isNetworkError(err)) return NETWORK_MESSAGE;
  const error = err?.response?.data?.error;
  if (!error) return fallback;
  if (error.code === "VALIDATION_ERROR") {
    const first = error.details?.errors?.[0];
    if (first) return `${first.loc.at(-1)}: ${first.msg}`;
  }
  if (error.code === "INTERNAL_ERROR") {
    return error.request_id ? `${fallback} (reference ${String(error.request_id).slice(0, 8)})` : fallback;
  }
  return error.message || fallback;
}

export default api;
