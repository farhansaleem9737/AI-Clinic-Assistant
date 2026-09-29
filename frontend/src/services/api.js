import axios from "axios";

// Set in frontend/.env (see .env.example). Includes the /api/v1 prefix.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;
if (!API_BASE_URL) {
  throw new Error("VITE_API_BASE_URL is not set. Copy frontend/.env.example to frontend/.env.");
}

const api = axios.create({
  baseURL: API_BASE_URL,
});

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

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let isRefreshing = false;
let refreshQueue = [];

const processQueue = (error, token = null) => {
  refreshQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  refreshQueue = [];
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Only handle 401s, and only retry once per request
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (originalRequest.url.includes("/auth/login") || originalRequest.url.includes("/auth/refresh")) {
        // Don't try to refresh if the login/refresh call itself failed
        return Promise.reject(error);
      }

      if (isRefreshing) {
        // Another request already triggered a refresh — wait for it
        return new Promise((resolve, reject) => {
          refreshQueue.push({ resolve, reject });
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return api(originalRequest);
          })
          .catch((err) => Promise.reject(err));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      const refreshToken = localStorage.getItem("refresh_token");

      if (!refreshToken) {
        isRefreshing = false;
        localStorage.removeItem("token");
        localStorage.removeItem("refresh_token");
        window.location.href = "/login";
        return Promise.reject(error);
      }

      try {
        const res = await axios.post(`${API_BASE_URL}/auth/refresh`, {
          refresh_token: refreshToken,
        });

        const newAccessToken = res.data.access_token;
        localStorage.setItem("token", newAccessToken);

        api.defaults.headers.Authorization = `Bearer ${newAccessToken}`;
        originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;

        processQueue(null, newAccessToken);
        isRefreshing = false;

        return api(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        isRefreshing = false;

        localStorage.removeItem("token");
        localStorage.removeItem("refresh_token");
        window.location.href = "/login";

        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

export default api;