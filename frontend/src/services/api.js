import axios from "axios";

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

// The access token lives only in memory — never in localStorage, where any
// injected script could read it. A page reload loses it on purpose; the
// HttpOnly refresh cookie restores the session (see restoreSession).
let accessToken = null;
let onSessionExpired = () => {};

export function setAccessToken(token) {
  accessToken = token;
}

export function setSessionExpiredHandler(handler) {
  onSessionExpired = handler;
}

function readCookie(name) {
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
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
export function getErrorMessage(err, fallback = "Something went wrong") {
  const error = err?.response?.data?.error;
  if (!error) return fallback;
  if (error.code === "VALIDATION_ERROR") {
    const first = error.details?.errors?.[0];
    if (first) return `${first.loc.at(-1)}: ${first.msg}`;
  }
  return error.message || fallback;
}

export default api;
