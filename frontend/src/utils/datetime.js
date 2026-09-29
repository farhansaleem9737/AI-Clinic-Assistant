// Appointment times come from the API as UTC instants. They are shown in the
// clinic department's timezone (sent with each appointment/availability
// response), so a patient abroad still sees the clinic's local time.

export function formatDateTime(iso, timeZone) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone }).format(new Date(iso));
}

export function formatTime(iso, timeZone) {
  return new Intl.DateTimeFormat(undefined, { timeStyle: "short", timeZone }).format(new Date(iso));
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
