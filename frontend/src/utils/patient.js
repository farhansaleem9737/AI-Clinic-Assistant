// Shared shape of the patient forms (see components/PatientFields.jsx).
export const SEX_OPTIONS = ["unknown", "female", "male", "intersex"];

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

// Blank optional fields are sent as null rather than "".
export function patientPayload(values, fields = Object.keys(EMPTY_PATIENT)) {
  return Object.fromEntries(fields.map((f) => [f, values[f] === "" ? null : values[f]]));
}
