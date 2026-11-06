// Rules for the patient's own personal and contact forms (D111). The backend
// checks everything again and is the authority.
import { COUNTRIES, dialFor } from "./locations";
import { EMAIL_PATTERN, FULL_NAME_MAX, birthDateError, splitFullName } from "./validation";

export const BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"];
export const MARITAL_STATUSES = [
  { value: "single", label: "Single" },
  { value: "married", label: "Married" },
  { value: "divorced", label: "Divorced" },
  { value: "widowed", label: "Widowed" },
];

const CNIC = /^\d{5}-?\d{7}-?\d$/;
const NATIONAL_ID = /^[A-Za-z0-9][A-Za-z0-9 /-]{3,29}$/;

/** A Pakistani CNIC is checked (13 digits); another country's ID only for its characters. */
export function nationalIdError(value, country) {
  if (!value) return "";
  if ((!country || country === "PK") && CNIC.test(value)) return "";
  if (country === "PK" || (!country && /^[\d-]+$/.test(value))) return "Enter the 13-digit CNIC as 12345-1234567-1.";
  return NATIONAL_ID.test(value) ? "" : "Use 4 to 30 letters, digits, spaces, dashes or slashes.";
}

export function personalErrors(form) {
  const errors = {};
  const name = form.full_name.trim();
  if (!name) errors.full_name = "Enter your full name.";
  else if (!splitFullName(name)) errors.full_name = "Enter your first and last name.";
  else if (name.length > FULL_NAME_MAX) errors.full_name = `Use at most ${FULL_NAME_MAX} characters.`;
  const dob = birthDateError(form.date_of_birth);
  if (dob) errors.date_of_birth = dob;
  if (form.national_id_editing) {
    const id = nationalIdError(form.national_id.trim(), form.country);
    if (id) errors.national_id = id;
    else if (!form.national_id.trim()) errors.national_id = "Enter the new ID, or keep the saved one.";
  }
  return errors;
}

// ---- phone numbers: a calling code and the national number --------------------------

/**
 * Splits a saved number for the form. "+92 3001234567" → { dial: "92", number: "3001234567" }.
 * A number saved without a calling code is shown as it is, under the country's
 * code, and never rewritten unless the patient edits it.
 */
export function splitPhone(phone, country) {
  const value = (phone ?? "").trim();
  if (value.startsWith("+")) {
    const digits = value.slice(1).replace(/[^\d]/g, "");
    const match = [...COUNTRIES].sort((a, b) => b.dial.length - a.dial.length).find((c) => digits.startsWith(c.dial));
    if (match) return { dial: match.dial, number: value.slice(1 + match.dial.length).trim() || digits.slice(match.dial.length) };
  }
  return { dial: dialFor(country) ?? "92", number: value };
}

/** "+92 3001234567": the national number without its leading trunk 0. */
export function joinPhone(dial, number) {
  const trimmed = number.trim();
  if (trimmed.startsWith("+")) return trimmed.replace(/\s+/g, " ");
  const digits = trimmed.replace(/[^\d]/g, "").replace(/^0+/, "");
  return `+${dial} ${digits}`;
}

export function phoneError(dial, number) {
  const trimmed = number.trim();
  if (!trimmed) return "Enter your phone number.";
  if (!/^\+?[\d ()\-.]+$/.test(trimmed)) return "Use digits only (spaces and dashes are fine).";
  const digits = trimmed.replace(/[^\d]/g, "").replace(/^0+/, "");
  if (dial === "92" && !trimmed.startsWith("+") && (digits.length < 9 || digits.length > 10)) return "A Pakistani number has 10 digits after +92, e.g. 3001234567.";
  if (digits.length < 6 || digits.length > 14) return "Enter a valid phone number.";
  return "";
}

/** `phoneChanged`: a number saved earlier in another format is not held against other edits. */
export function contactErrors(form, { phoneChanged = true } = {}) {
  const errors = {};
  const phone = phoneError(form.dial, form.number);
  if (phone && (phoneChanged || !form.number.trim())) errors.number = phone;
  if (!form.email.trim()) errors.email = "Enter your email address.";
  else if (!EMAIL_PATTERN.test(form.email.trim())) errors.email = "Enter a valid email address.";
  if (!form.address.trim()) errors.address = "Enter your street address or area.";
  if (!form.city.trim()) errors.city = "Enter your city.";
  if (!form.province.trim()) errors.province = "Choose your province or state.";
  if (!form.country) errors.country = "Choose your country.";
  return errors;
}
