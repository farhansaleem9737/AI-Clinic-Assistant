// Appointment times come from the API as UTC instants. They are shown in the
// clinic department's timezone (sent with each appointment/availability
// response), so a patient abroad still sees the clinic's local time.

export function formatDateTime(iso, timeZone) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone }).format(new Date(iso));
}

export function formatTime(iso, timeZone) {
  return new Intl.DateTimeFormat(undefined, { timeStyle: "short", timeZone }).format(new Date(iso));
}

// "Wednesday, October 7, 2026" for an instant, in the given timezone.
export function formatLongDate(iso, timeZone) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "full", timeZone }).format(new Date(iso));
}

// "Jan 1, 1990" for a calendar date ("YYYY-MM-DD", e.g. a birthday). Read in
// UTC so the browser's timezone can never move it to the previous day.
export function formatCalendarDate(isoDate) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${isoDate}T00:00:00Z`));
}

// "YYYY-MM-DD" of an instant in a given timezone.
export function isoDateIn(value, timeZone) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    value instanceof Date ? value : new Date(value)
  );
  return parts; // en-CA formats as YYYY-MM-DD
}

export function addDays(isoDate, days) {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function formatDayHeading(isoDate) {
  return new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(
    new Date(`${isoDate}T00:00:00Z`)
  );
}

// <input type="datetime-local"> gives wall-clock time without a zone; it is
// interpreted in the browser's timezone and sent as a UTC instant.
export function localInputToIso(value) {
  return new Date(value).toISOString();
}

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

// { month: "Oct", day: "5", weekday: "Mon" } for an instant, in the given timezone.
export function dayParts(iso, timeZone) {
  const parts = new Intl.DateTimeFormat("en", { month: "short", day: "numeric", weekday: "short", timeZone }).formatToParts(
    new Date(iso)
  );
  const get = (type) => parts.find((p) => p.type === type)?.value;
  return { month: get("month"), day: get("day"), weekday: get("weekday") };
}
