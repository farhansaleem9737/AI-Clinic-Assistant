// Client-side checks are for convenience only; the backend validates again
// and is the authority. These mirror its rules so messages appear early.

export const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// The backend accepts passwords of 8 to 128 characters.
export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 128;

// The account's display name ("first last") must fit 100 characters.
export const FULL_NAME_MAX = 100;

/**
 * Split a full name for the backend, which stores given and family name
 * separately: the last word is the family name, everything before it the
 * given name(s). Any script is accepted; nothing is restricted to ASCII.
 * Returns null when there are not at least two words.
 */
export function splitFullName(fullName) {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length < 2) return null;
  const lastName = parts.pop();
  return { first_name: parts.join(" "), last_name: lastName };
}

export function todayIso() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

// Props that tie a control to the error message rendered by its FormField.
export function errorProps(id, error) {
  return error ? { "aria-invalid": true, "aria-describedby": `${id}-error` } : {};
}

// Date-of-birth rules shared with the backend: not in the future, at most
// 120 years ago, and for doctors and staff at least 18 years ago.
export const MAX_AGE_YEARS = 120;
export const ADULT_AGE_YEARS = 18;

// The ISO date `years` years before today (29 February falls back to the 28th).
export function isoYearsAgo(years) {
  const [y, m, d] = todayIso().split("-").map(Number);
  const day = m === 2 && d === 29 ? 28 : d;
  return `${y - years}-${String(m).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export function birthDateError(value, { minAge = 0 } = {}) {
  if (!value) return "Enter your date of birth.";
  if (value > todayIso()) return "Date of birth cannot be in the future.";
  if (value < isoYearsAgo(MAX_AGE_YEARS)) return "Enter a valid date of birth.";
  if (minAge && value > isoYearsAgo(minAge)) return `You must be at least ${minAge} years old.`;
  return "";
}

// Shown in every gender select; the values are the backend's.
export const GENDER_OPTIONS = [
  { value: "female", label: "Female" },
  { value: "male", label: "Male" },
  { value: "intersex", label: "Intersex" },
  { value: "unknown", label: "Prefer not to say" },
];
