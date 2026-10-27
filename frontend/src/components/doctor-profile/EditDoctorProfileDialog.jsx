import { useState } from "react";
import { getErrorMessage } from "../../services/api";
import { updateMyDoctorProfile } from "../../services/doctorService";
import { doctorName, formatFee } from "../../utils/format";
import ConfirmDialog from "../ConfirmDialog";

const BIO_MAX = 1000;
const FIELDS = ["years_of_experience", "languages", "qualifications", "phone", "bio"];

// The API's 422 details -> { field: message } for the fields in this form.
function fieldErrors(err) {
  const errors = err?.response?.data?.error?.details?.errors ?? [];
  return Object.fromEntries(
    errors.map((e) => [e.loc?.at(-1), e.msg]).filter(([field]) => FIELDS.includes(field))
  );
}

// Label, input, then a hint or an error, linked to the input by
// aria-describedby so they are read after (not as part of) the field's name.
function Field({ id, label, error, hint, children }) {
  return (
    <div className="edit-field">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && !error && (
        <small className="muted" id={`${id}-hint`}>
          {hint}
        </small>
      )}
      {error && (
        <small className="field-error" id={`${id}-error`} role="alert">
          {error}
        </small>
      )}
    </div>
  );
}

/**
 * The doctor edits what they own on their profile. Name, specialization,
 * department, fee, license number and room are managed by the clinic
 * administration: shown read-only here, and ignored by the API if sent.
 */
export default function EditDoctorProfileDialog({ profile, onSaved, onClose }) {
  const [form, setForm] = useState({
    years_of_experience: String(profile.years_of_experience ?? 0),
    languages: profile.languages ?? "",
    qualifications: profile.qualifications ?? "",
    phone: profile.phone ?? "",
    bio: profile.bio ?? "",
  });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const bind = (field) => ({
    id: `edit-${field}`,
    value: form[field],
    onChange: (e) => setForm({ ...form, [field]: e.target.value }),
    "aria-invalid": errors[field] ? true : undefined,
    "aria-describedby": errors[field] ? `edit-${field}-error` : `edit-${field}-hint`,
    disabled: busy,
  });

  const save = async () => {
    const years = Number(form.years_of_experience);
    if (form.years_of_experience.trim() === "" || !Number.isInteger(years) || years < 0 || years > 80) {
      setErrors({ years_of_experience: "Enter a whole number of years from 0 to 80." });
      return;
    }
    setBusy(true);
    setErrors({});
    setError("");
    try {
      const res = await updateMyDoctorProfile({
        years_of_experience: years,
        languages: form.languages.trim() || null,
        qualifications: form.qualifications.trim() || null,
        phone: form.phone.trim() || null,
        bio: form.bio.trim() || null,
      });
      onSaved(res.data);
    } catch (err) {
      setErrors(fieldErrors(err));
      setError(getErrorMessage(err, "Could not save your profile"));
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      title="Edit profile"
      confirmLabel="Save changes"
      busy={busy}
      error={error}
      onConfirm={save}
      onCancel={onClose}
      className="wide-dialog"
    >
      <div className="edit-grid">
        <Field id="edit-years_of_experience" label="Years of experience" error={errors.years_of_experience}>
          <input type="number" min={0} max={80} step={1} inputMode="numeric" {...bind("years_of_experience")} required />
        </Field>
        <Field id="edit-languages" label="Languages" error={errors.languages} hint="e.g. English, Urdu">
          <input maxLength={200} {...bind("languages")} />
        </Field>
        <Field id="edit-qualifications" label="Qualifications" error={errors.qualifications} hint="e.g. MBBS, FCPS (Cardiology)">
          <input maxLength={500} {...bind("qualifications")} />
        </Field>
        <Field id="edit-phone" label="Phone (internal only)" error={errors.phone}>
          <input maxLength={30} {...bind("phone")} />
        </Field>
        <Field
          id="edit-bio"
          label="Professional biography"
          error={errors.bio}
          hint={`${form.bio.length}/${BIO_MAX} · leave a blank line between paragraphs`}
        >
          <textarea rows={6} maxLength={BIO_MAX} {...bind("bio")} />
        </Field>
      </div>

      <div className="readonly-box">
        <p className="readonly-title">Managed by the clinic administration</p>
        <dl>
          <div>
            <dt>Name</dt>
            <dd>{doctorName(profile)}</dd>
          </div>
          <div>
            <dt>Specialization</dt>
            <dd>{profile.specialization}</dd>
          </div>
          <div>
            <dt>Department</dt>
            <dd>{profile.department_name}</dd>
          </div>
          <div>
            <dt>Consultation fee</dt>
            <dd>{profile.consultation_fee == null ? "Not set" : formatFee(profile.consultation_fee)}</dd>
          </div>
          <div>
            <dt>License number</dt>
            <dd>{profile.license_number ?? "Not on file"}</dd>
          </div>
        </dl>
        <p className="muted small">Contact the clinic administration to change these.</p>
      </div>
    </ConfirmDialog>
  );
}
