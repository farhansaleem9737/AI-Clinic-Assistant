// Month arithmetic on plain "YYYY-MM" / "YYYY-MM-DD" strings, done in UTC so
// the browser timezone can never shift a date across midnight.

const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;

export function addMonths(month, delta) {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}`;
}

export function monthLabel(month) {
  const [y, m] = month.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric", timeZone: "UTC" }).format(
    new Date(Date.UTC(y, m - 1, 1))
  );
}

export function monthBounds(month) {
  const [y, m] = month.split("-").map(Number);
  return { first: `${month}-01`, last: iso(new Date(Date.UTC(y, m, 0))) };
}

// Whole weeks of days, Sunday first, covering the month.
export function monthGrid(month) {
  const [y, m] = month.split("-").map(Number);
  const first = new Date(Date.UTC(y, m - 1, 1));
  const start = new Date(first);
  start.setUTCDate(1 - first.getUTCDay());
  const weeks = Math.ceil((first.getUTCDay() + new Date(Date.UTC(y, m, 0)).getUTCDate()) / 7);
  return Array.from({ length: weeks * 7 }, (_, i) => {
    const d = new Date(start);
    d.setUTCDate(start.getUTCDate() + i);
    return { date: iso(d), inMonth: d.getUTCMonth() === m - 1 };
  });
}

// "Thursday, October 1, 2026" for a "YYYY-MM-DD" date (no timezone shift).
export function longDate(isoDate) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "full", timeZone: "UTC" }).format(new Date(`${isoDate}T00:00:00Z`));
}
