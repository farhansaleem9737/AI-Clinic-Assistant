import { useState } from "react";
import { getErrorMessage } from "../../services/api";
import { removePatientPhoto, updatePatient, uploadPatientPhoto } from "../../services/patientService";
import { CONTACT_METHODS, EDITABLE_PATIENT_FIELDS, patientFullName, SEX_LABELS, SEX_OPTIONS } from "../../utils/patient";
import { EMAIL_PATTERN, todayIso } from "../../utils/validation";
import ConfirmDialog from "../ConfirmDialog";
import PhotoUploader from "../PhotoUploader";

const PHONE_PATTERN = /^\+?[0-9(][0-9 ()\-.]{3,28}$/;

function validate(form) {
  const errors = {};
  if (!form.first_name.trim()) errors.first_name = "Enter the first name.";
  if (!form.last_name.trim()) errors.last_name = "Enter the last name.";
  if (!form.date_of_birth) errors.date_of_birth = "Enter the date of birth.";
  else if (form.date_of_birth > todayIso()) errors.date_of_birth = "The date of birth cannot be in the future.";
  if (form.email.trim() && !EMAIL_PATTERN.test(form.email.trim())) errors.email = "Enter a valid email address.";
  for (const field of ["phone", "emergency_contact_phone"])
    if (form[field].trim() && !PHONE_PATTERN.test(form[field].trim()))
      errors[field] = "Use digits, spaces, dashes or brackets, with an optional leading +.";
  return errors;
}

function serverErrors(err) {
  const fields = {};
  for (const item of err?.response?.data?.error?.details?.errors ?? []) {
    const field = item.loc?.at(-1);
    if (EDITABLE_PATIENT_FIELDS.includes(field)) fields[field] = "Check this value.";
  }
  return fields;
}

/**
 * Staff edit of a patient's identity and contact details (patient:update).
 * MRN, registration date, login and clinical data are not editable here;
 * the API ignores them if sent. The photo is saved as soon as it is chosen.
 */
export default function EditPatientDialog({ patient, onSaved, onPhotoChanged, onClose }) {
  const [form, setForm] = useState(() =>
    Object.fromEntries(EDITABLE_PATIENT_FIELDS.map((f) => [f, patient[f] ?? (f === "sex_at_birth" ? "unknown" : "")]))
  );
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const name = patientFullName(patient);

  const bind = (field) => ({
    id: `edit-patient-${field}`,
    value: form[field],
    onChange: (e) => {
      setForm({ ...form, [field]: e.target.value });
      setErrors({ ...errors, [field]: undefined });
    },
    "aria-invalid": errors[field] ? true : undefined,
    "aria-describedby": errors[field] ? `edit-patient-${field}-error` : undefined,
    disabled: busy,
  });
  const field = (key, label, input) => (
    <div className="edit-field">
      <label htmlFor={`edit-patient-${key}`}>{label}</label>
      {input}
      {errors[key] && (
        <small className="field-error" id={`edit-patient-${key}-error`}>
          {errors[key]}
        </small>
      )}
    </div>
  );

  const save = async () => {
    const found = validate(form);
    setErrors(found);
    setError("");
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      // Blank optional fields are sent as null so clearing a field clears it.
      const payload = Object.fromEntries(
        Object.entries(form).map(([k, v]) => [k, typeof v === "string" ? v.trim() || null : v])
      );
      const res = await updatePatient(patient.id, payload);
      onSaved(res.data);
    } catch (err) {
      setErrors(serverErrors(err));
      setError(getErrorMessage(err, "Could not save the changes"));
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      title="Edit patient"
      confirmLabel="Save changes"
      busy={busy}
      error={error}
      onConfirm={save}
      onCancel={onClose}
      className="wide-dialog"
    >
      <h3 className="edit-section-title">Personal information</h3>
      <div className="edit-grid">
        {field("first_name", "First name", <input maxLength={100} required {...bind("first_name")} />)}
        {field("last_name", "Last name", <input maxLength={100} required {...bind("last_name")} />)}
        {field("date_of_birth", "Date of birth", <input type="date" min="1900-01-01" max={todayIso()} required {...bind("date_of_birth")} />)}
        {field(
          "sex_at_birth",
          "Gender",
          <select {...bind("sex_at_birth")}>
            {SEX_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {SEX_LABELS[s]}
              </option>
            ))}
          </select>
        )}
      </div>

      <h3 className="edit-section-title">Contact information</h3>
      <div className="edit-grid">
        {field("phone", "Phone", <input type="tel" maxLength={30} {...bind("phone")} />)}
        {field("email", "Email", <input type="email" maxLength={255} {...bind("email")} />)}
        {field("preferred_contact_method", "Preferred contact method", (
          <select {...bind("preferred_contact_method")}>
            <option value="">Not set</option>
            {Object.entries(CONTACT_METHODS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        ))}
        {field("preferred_language", "Preferred language", <input maxLength={35} {...bind("preferred_language")} />)}
        {field("emergency_contact_name", "Emergency contact", <input maxLength={100} {...bind("emergency_contact_name")} />)}
        {field("emergency_contact_relationship", "Relationship", <input maxLength={50} placeholder="e.g. Spouse" {...bind("emergency_contact_relationship")} />)}
        {field("emergency_contact_phone", "Emergency phone", <input type="tel" maxLength={30} {...bind("emergency_contact_phone")} />)}
        {field("address", "Address", <textarea rows={3} maxLength={500} {...bind("address")} />)}
      </div>

      <h3 className="edit-section-title">Photo</h3>
      <PhotoUploader
        name={name}
        role="patient"
        photoUrl={patient.photo_url}
        onUpload={async (file) => onPhotoChanged((await uploadPatientPhoto(patient.id, file)).data)}
        onRemove={async () => onPhotoChanged((await removePatientPhoto(patient.id)).data)}
      />
      <p className="muted small">The MRN and registration date cannot be changed. Photo changes are saved straight away.</p>
    </ConfirmDialog>
  );
}
