// Shared shape of the patient forms (see components/PatientFields.jsx).
export const SEX_OPTIONS = ["unknown", "female", "male", "intersex"];
export const SEX_LABELS = { male: "Male", female: "Female", intersex: "Intersex", unknown: "Not recorded" };

export const EMPTY_PATIENT = {
  first_name: "",
  last_name: "",
  date_of_birth: "",
  sex_at_birth: "unknown",
  phone: "",
  email: "",
  address: "",
  preferred_language: "",
};

// What a patient may change about themselves (PATCH /patients/me). Name, date
// of birth and sex are corrected at reception (architecture §6).
export const CONTACT_FIELDS = ["phone", "email", "address", "preferred_language"];

// Blank optional fields are sent as null rather than "".
export function patientPayload(values, fields = Object.keys(EMPTY_PATIENT)) {
  return Object.fromEntries(fields.map((f) => [f, values[f] === "" ? null : values[f]]));
}

// "Ada Lovelace" from a patient record; empty parts are skipped.
export function patientFullName(patient) {
  return [patient?.first_name, patient?.last_name].filter(Boolean).join(" ");
}

// Whole years from a "YYYY-MM-DD" birth date to `today`. Compares calendar
// parts only, so a time zone can never move a birthday by a day.
export function ageFromDateOfBirth(isoDate, today = new Date()) {
  if (!isoDate) return null;
  const [year, month, day] = isoDate.split("-").map(Number);
  const currentMonth = today.getMonth() + 1;
  const hadBirthdayThisYear = currentMonth > month || (currentMonth === month && today.getDate() >= day);
  const age = today.getFullYear() - year - (hadBirthdayThisYear ? 0 : 1);
  return age >= 0 ? age : null;
}
