// Helpers for Admin > Doctors (D90).
import { EMAIL_PATTERN } from "./validation";

// Column -> [ascending, descending] sort values of GET /doctors.
export const SORTS = {
  name: ["name_asc", "name_desc"],
  department: ["department_asc", "department_desc"],
  specialization: ["specialization_asc", "specialization_desc"],
  experience: ["experience_asc", "experience_desc"],
  status: ["status_asc", "status_desc"],
};
export const COLUMN_LABELS = { name: "Doctor", department: "Department", specialization: "Specialization", experience: "Experience", status: "Status" };

export function sortOf(sort, column) {
  const [asc, desc] = SORTS[column];
  return sort === asc ? "ascending" : sort === desc ? "descending" : "none";
}
export const toggleSort = (sort, column) => (sort === SORTS[column][0] ? SORTS[column][1] : SORTS[column][0]);

export const experienceLabel = (years) => `${years} year${years === 1 ? "" : "s"}`;

export const PROFILE_FIELDS = {
  title: "Dr.",
  specialization: "",
  department_id: "",
  license_number: "",
  years_of_experience: "0",
  qualifications: "",
  consultation_fee: "",
  languages: "",
  phone: "",
  room_number: "",
  bio: "",
};
export const ACCOUNT_FIELDS = { name: "", email: "", password: "", confirm: "", active: "true" };

const PHONE = /^\+?[0-9 ()-]{7,20}$/;

export function validateDoctor(form, { creating }) {
  const errors = {};
  if (creating) {
    if (!form.name.trim()) errors.name = "Enter the doctor's full name.";
    if (!EMAIL_PATTERN.test(form.email.trim())) errors.email = "Enter a valid email address.";
    if (form.password.length < 8) errors.password = "Use at least 8 characters.";
    else if (form.confirm !== form.password) errors.confirm = "The passwords do not match.";
  }
  if (!form.specialization.trim()) errors.specialization = "Enter the specialization.";
  if (!form.department_id) errors.department_id = "Choose a department.";
  const years = Number(form.years_of_experience);
  if (form.years_of_experience === "" || !Number.isInteger(years) || years < 0 || years > 80)
    errors.years_of_experience = "Enter whole years between 0 and 80.";
  if (form.consultation_fee !== "" && !(Number(form.consultation_fee) >= 0)) errors.consultation_fee = "The fee cannot be negative.";
  if (form.phone.trim() && !PHONE.test(form.phone.trim())) errors.phone = "Enter a valid phone number.";
  return errors;
}

/** The professional part of the payload: blanks become null, the fee stays a decimal string. */
export function professionalPayload(form) {
  const payload = {};
  for (const key of Object.keys(PROFILE_FIELDS)) {
    const value = typeof form[key] === "string" ? form[key].trim() : form[key];
    payload[key] = value === "" ? null : value;
  }
  payload.years_of_experience = Number(form.years_of_experience);
  return payload;
}

export const fromDoctor = (doctor) =>
  Object.fromEntries(
    Object.keys(PROFILE_FIELDS).map((key) => [key, doctor[key] == null ? "" : String(doctor[key])])
  );
