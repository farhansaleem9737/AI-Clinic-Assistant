import { QueryClient } from "@tanstack/react-query";

// Server data the app has already loaded, in memory only (never stored in the
// browser), for the signed-in user. A page opened again shows it at once and
// refreshes it in the background once it is older than its category allows.
// One client for the whole app, created once (D107).

const SECOND = 1000;
const MINUTE = 60 * SECOND;

// How long loaded data counts as fresh, by the first part of a query name
// ("appointments/list" → appointments). Unnamed queries are not cached.
export const FRESHNESS = {
  departments: 5 * MINUTE, // reference data, rarely changes
  specializations: 5 * MINUTE,
  doctors: 2 * MINUTE, // directory and profiles
  settings: 5 * MINUTE,
  dashboard: 30 * SECOND,
  appointments: 30 * SECOND,
  patients: 30 * SECOND,
  users: 30 * SECOND,
  profile: MINUTE, // the signed-in user's own patient or doctor profile
  schedule: 30 * SECOND,
  availability: 0, // shown while it re-checks; booking re-checks on the server too
};
// Unused data is dropped after this (memory bound).
const KEEP_UNUSED = 5 * MINUTE;

const category = (name) => String(name).split("/")[0];
export const freshnessOf = (name) => FRESHNESS[category(name)] ?? 0;

// Repeat a failed read once when the server or the network failed (a dropped
// database connection answers 500); never for an answer like 403 or 404.
const transient = (error) => !error?.response || error.response.status >= 500;

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failures, error) => failures < 1 && transient(error),
      retryDelay: 800,
      gcTime: KEEP_UNUSED,
      refetchOnWindowFocus: false,
    },
  },
});

// Whose data the cache holds. Query keys start with it, and a different user
// (sign-out, another account) empties the cache first.
let owner = null;
export const cacheOwner = () => owner;
export function setCacheOwner(userId) {
  const next = userId ?? null;
  if (next === owner) return;
  owner = next;
  queryClient.clear();
}

// What a successful change makes out of date, by the API path it was sent to.
// Only marked stale: the page on screen refreshes now, others when next opened.
const AFFECTS = {
  appointments: ["appointments", "dashboard", "availability", "schedule", "patients"],
  schedules: ["schedule", "availability", "dashboard"],
  "schedule-exceptions": ["schedule", "availability", "dashboard"],
  doctors: ["doctors", "schedule", "availability", "dashboard", "departments", "specializations", "profile"],
  departments: ["departments", "doctors", "specializations", "dashboard"],
  patients: ["patients", "profile", "appointments", "dashboard"],
  users: ["users", "doctors", "patients", "dashboard"],
  admin: ["users", "dashboard"],
  settings: ["settings", "dashboard"],
  notifications: [],
  auth: [],
};

/** After a successful POST/PUT/PATCH/DELETE to `url`, mark the affected data stale. */
export function invalidateAfterChange(url) {
  const path = String(url ?? "").replace(/^https?:\/\/[^/]+/, "").replace(/^\/api\/v\d+/, "").split("?")[0];
  const first = path.split("/").filter(Boolean)[0];
  // The assistant changes clinic data only when the user confirms its proposal.
  if (first === "ai" && !path.endsWith("/decision")) return;
  const affected = AFFECTS[first];
  if (affected && affected.length === 0) return;
  queryClient.invalidateQueries({
    // Unknown paths (e.g. a confirmed assistant booking) refresh everything cached.
    predicate: (query) => !affected || affected.includes(category(query.queryKey[1])),
  });
}
