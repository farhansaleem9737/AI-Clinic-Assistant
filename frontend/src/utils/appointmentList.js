// The patient's Appointments page keeps its state in the URL (tab, search,
// status, date range, page), so refresh, back/forward and links all work.
// These helpers translate between the URL and the API.

import { STATUS_LABELS } from "./appointments";

export const PAGE_SIZE = 10;
export const TABS = [
  { id: "upcoming", label: "Upcoming" },
  { id: "past", label: "Past" },
  { id: "all", label: "All" },
];
const TAB_IDS = TABS.map((t) => t.id);
const DATE = /^\d{4}-\d{2}-\d{2}$/;

export const EMPTY_FILTERS = { q: "", status: "", from: "", to: "" };

export function readListState(searchParams) {
  const page = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const tab = searchParams.get("tab");
  const status = searchParams.get("status") ?? "";
  const date = (key) => (DATE.test(searchParams.get(key) ?? "") ? searchParams.get(key) : "");
  return {
    tab: TAB_IDS.includes(tab) ? tab : "upcoming",
    filters: {
      q: searchParams.get("q") ?? "",
      status: status in STATUS_LABELS ? status : "",
      from: date("from"),
      to: date("to"),
    },
    page: Number.isInteger(page) && page > 0 ? page : 1,
  };
}

// Defaults are left out so URLs stay short.
export function listSearchParams({ tab, filters, page }) {
  const params = {};
  if (tab !== "upcoming") params.tab = tab;
  for (const [key, value] of Object.entries(filters)) if (value) params[key] = value;
  if (page > 1) params.page = String(page);
  return params;
}

export const hasFilters = (filters) => Object.values(filters).some(Boolean);
export const rangeIsValid = ({ from, to }) => !from || !to || from <= to;

// Filters as the API names them (shared by the list and its tab counts).
export function filterParams({ q, status, from, to }) {
  const params = {};
  if (q.trim()) params.q = q.trim();
  if (status) params.status = status;
  if (from) params.date_from = from;
  if (to) params.date_to = to;
  return params;
}

// Upcoming lists the soonest first; past and all the most recent first.
export function listParams({ tab, filters, page }) {
  return {
    ...filterParams(filters),
    scope: tab,
    newest_first: tab !== "upcoming",
    page,
    page_size: PAGE_SIZE,
  };
}
