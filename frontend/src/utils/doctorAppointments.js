import { addDays } from "./datetime";

// The doctor's My Appointments views (D79). "day" is the selected date
// (Today by default); upcoming and past are relative to the real today.
export const VIEWS = ["day", "upcoming", "past"];
export const DOCTOR_PAGE_SIZE = 10;

/**
 * List parameters for a view. Dates are calendar dates in the doctor's
 * timezone, which the API applies; the search text is never put in the URL.
 */
export function doctorListParams({ view, day, today, status, q, page }) {
  const params = { page, page_size: DOCTOR_PAGE_SIZE };
  if (view === "upcoming") params.date_from = addDays(today, 1);
  else if (view === "past") {
    params.date_to = addDays(today, -1);
    params.newest_first = true;
  } else {
    params.date_from = day;
    params.date_to = day;
  }
  if (status) params.status = [status];
  if (q.trim()) params.q = q.trim();
  return params;
}

export function countParams({ day, status, q }) {
  const params = {};
  if (day) params.day = day;
  if (status) params.status = [status];
  if (q.trim()) params.q = q.trim();
  return params;
}

// Valid "YYYY-MM-DD" from the URL, or null.
export function readDay(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value ?? "") && !Number.isNaN(Date.parse(`${value}T00:00:00Z`)) ? value : null;
}

// "Wed, Apr 23, 2026" / "Apr 23, 2026" / "Wednesday" for a calendar date.
const format = (isoDate, options) =>
  new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" }).format(new Date(`${isoDate}T00:00:00Z`));
export const shortDay = (isoDate) => format(isoDate, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
export const mediumDay = (isoDate) => format(isoDate, { month: "short", day: "numeric", year: "numeric" });
export const weekday = (isoDate) => format(isoDate, { weekday: "long" });
