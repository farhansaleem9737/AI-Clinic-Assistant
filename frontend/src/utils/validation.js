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
