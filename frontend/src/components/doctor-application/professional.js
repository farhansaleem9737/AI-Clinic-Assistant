import { getErrorMessage } from "../../services/api";
import { CREDENTIAL_TYPES, uploadApplicationDocument } from "../../services/doctorApplicationService";
import { formatBytes, MAX_DOCUMENT_BYTES } from "../../services/files";

export const PROFESSIONAL_FIELDS = [
  "license_number",
  "registration_authority",
  "specialization",
  "department_id",
  "years_of_experience",
  "qualifications",
  "institution",
  "bio",
  "consultation_fee",
  "languages",
];

export const EMPTY_PROFESSIONAL = Object.fromEntries(PROFESSIONAL_FIELDS.map((f) => [f, ""]));

// Every field is optional; only values that were given are checked.
export function validateProfessional(values) {
  const errors = {};
  const years = values.years_of_experience.trim();
  if (years && !/^\d{1,2}$/.test(years)) errors.years_of_experience = "Enter whole years from 0 to 80.";
  else if (years && Number(years) > 80) errors.years_of_experience = "Enter whole years from 0 to 80.";
  const fee = values.consultation_fee.trim();
  if (fee && !/^\d{1,8}(\.\d{1,2})?$/.test(fee)) errors.consultation_fee = "Enter an amount such as 1500 or 1500.50.";
  return errors;
}

/**
 * What to send. For registration (`clearBlanks` false) an empty box is left
 * out; on the application page it is sent as null, so clearing a field clears it.
 * The fee stays a decimal string, never a float.
 */
export function professionalPayload(values, { clearBlanks = false } = {}) {
  const payload = {};
  for (const field of PROFESSIONAL_FIELDS) {
    const value = String(values[field] ?? "").trim();
    if (!value) {
      if (clearBlanks) payload[field] = null;
      continue;
    }
    payload[field] = field === "years_of_experience" ? Number(value) : value;
  }
  return payload;
}

export function professionalValues(application) {
  return Object.fromEntries(PROFESSIONAL_FIELDS.map((f) => [f, application[f] == null ? "" : String(application[f])]));
}

// The API's 422 details -> { field: message } for the professional fields.
export function professionalServerErrors(err) {
  const fields = {};
  for (const item of err?.response?.data?.error?.details?.errors ?? []) {
    const field = item.loc?.at(-1);
    if (PROFESSIONAL_FIELDS.includes(field)) fields[field] = "Check this value.";
  }
  if (err?.response?.data?.error?.code === "DEPARTMENT_UNAVAILABLE")
    fields.department_id = "Choose one of the listed departments.";
  return fields;
}

const ACCEPTED_TYPES = ["application/pdf", "image/jpeg", "image/png"];
const ACCEPTED_EXTENSIONS = /\.(pdf|jpe?g|png)$/i;
export const CREDENTIAL_ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";
export const CREDENTIAL_HINT = `PDF, JPG, JPEG or PNG, up to ${formatBytes(MAX_DOCUMENT_BYTES)}.`;

// A quick message before uploading; the API checks the real content again.
export function credentialFileError(file) {
  if (!ACCEPTED_TYPES.includes(file.type) && !ACCEPTED_EXTENSIONS.test(file.name))
    return "Choose a PDF, JPG, JPEG or PNG file.";
  if (file.size === 0) return "This file is empty.";
  if (file.size > MAX_DOCUMENT_BYTES) return `The file must be ${formatBytes(MAX_DOCUMENT_BYTES)} or smaller.`;
  return null;
}

/**
 * Upload the chosen credentials one after another. `files` maps a credential
 * type to a File (or null). Returns one result per file; a failure does not
 * stop the others, and nothing is reported as uploaded unless the API said so.
 */
export async function uploadCredentials(files, onProgress = () => {}) {
  const results = [];
  for (const { value: type, label } of CREDENTIAL_TYPES) {
    const file = files[type];
    if (!file) continue;
    try {
      await uploadApplicationDocument(file, type, (percent) => onProgress(type, percent));
      results.push({ type, label, ok: true });
    } catch (err) {
      const unavailable = err?.response?.status === 503;
      results.push({
        type,
        label,
        ok: false,
        message: unavailable
          ? "Document storage is not available right now."
          : getErrorMessage(err, "The file could not be uploaded."),
      });
    }
  }
  return results;
}
