import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getErrorMessage } from "../../services/api";
import { createDoctor, deactivateDoctor, getDoctor, getDoctorCareer, updateDoctor } from "../../services/doctorService";
import { ACCOUNT_FIELDS, experienceLabel, fromDoctor, PROFILE_FIELDS, professionalPayload, validateDoctor } from "../../utils/adminDoctors";
import { doctorName, formatFee } from "../../utils/format";
import Alert from "../Alert";
import Avatar from "../Avatar";
import ConfirmDialog from "../ConfirmDialog";
import FormField from "../FormField";

function Input({ id, label, error, form, setForm, field, ...rest }) {
  return (
    <FormField id={id} label={label} error={error}>
      <input
        id={id}
        value={form[field]}
        onChange={(e) => setForm({ ...form, [field]: e.target.value })}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        {...rest}
      />
    </FormField>
  );
}

/**
 * Add Doctor (a new login with the doctor role and a verified profile, by an
 * administrator) or Edit Doctor (professional details only). Credential
 * documents belong to self-registered applications; see Applications.
 */
export function DoctorFormDialog({ doctor, departments, onClose, onSaved }) {
  const creating = !doctor;
  const [form, setForm] = useState(() => (creating ? { ...ACCOUNT_FIELDS, ...PROFILE_FIELDS } : fromDoctor(doctor)));
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const p = { form, setForm };

  const save = async () => {
    const found = validateDoctor(form, { creating });
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError("");
    try {
      const professional = professionalPayload(form);
      if (creating) {
        const res = await createDoctor({
          account: { name: form.name.trim(), email: form.email.trim(), password: form.password },
          ...professional,
        });
        let note = "";
        if (form.active === "false") {
          try {
            await deactivateDoctor(res.data.id);
            note = " The profile is inactive.";
          } catch (err) {
            note = ` It could not be set inactive: ${getErrorMessage(err)}`;
          }
        }
        onSaved(`Added ${doctorName(res.data)}.${note}`);
      } else {
        const res = await updateDoctor(doctor.id, professional);
        onSaved(`Saved ${doctorName(res.data)}.`);
      }
    } catch (err) {
      const code = err?.response?.data?.error?.code;
      if (code === "EMAIL_TAKEN") setErrors({ email: "An account with this email already exists." });
      else if (code === "LICENSE_TAKEN" || code === "LICENSE_NUMBER_TAKEN") setErrors({ license_number: "Another doctor holds this license number." });
      else setError(getErrorMessage(err, "Could not save the doctor"));
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      title={creating ? "Add Doctor" : `Edit ${doctorName(doctor)}`}
      confirmLabel={creating ? "Add Doctor" : "Save changes"}
      busy={busy}
      error={error}
      onConfirm={save}
      onCancel={onClose}
      className="wide-dialog"
    >
      {creating && (
        <fieldset className="form-section">
          <legend>Account</legend>
          <div className="dept-form-row">
            <Input id="doc-name" label="Full name" error={errors.name} field="name" maxLength={100} {...p} />
            <Input id="doc-email" label="Email" error={errors.email} field="email" type="email" autoComplete="off" {...p} />
            <Input id="doc-password" label="Temporary password" error={errors.password} field="password" type="password" autoComplete="new-password" {...p} />
            <Input id="doc-confirm" label="Confirm password" error={errors.confirm} field="confirm" type="password" autoComplete="new-password" {...p} />
            <FormField id="doc-status" label="Status">
              <select id="doc-status" value={form.active} onChange={(e) => setForm({ ...form, active: e.target.value })}>
                <option value="true">Active</option>
                <option value="false">Inactive</option>
              </select>
            </FormField>
          </div>
          <p className="muted small">Share the temporary password privately; it is never emailed.</p>
        </fieldset>
      )}
      <fieldset className="form-section">
        <legend>Professional details</legend>
        <div className="dept-form-row">
          <Input id="doc-title" label="Title" field="title" maxLength={20} {...p} />
          <Input id="doc-specialization" label="Specialization" error={errors.specialization} field="specialization" maxLength={150} {...p} />
          <FormField id="doc-department" label="Department" error={errors.department_id}>
            <select
              id="doc-department"
              value={form.department_id}
              onChange={(e) => setForm({ ...form, department_id: e.target.value })}
              aria-invalid={errors.department_id ? true : undefined}
            >
              <option value="">Select department</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </FormField>
          <Input id="doc-license" label="License / registration no." error={errors.license_number} field="license_number" maxLength={50} {...p} />
          <Input id="doc-years" label="Years of experience" error={errors.years_of_experience} field="years_of_experience" type="number" min="0" max="80" {...p} />
          <Input id="doc-fee" label="Consultation fee" error={errors.consultation_fee} field="consultation_fee" type="number" min="0" step="0.01" {...p} />
          <Input id="doc-phone" label="Phone (internal)" error={errors.phone} field="phone" maxLength={30} {...p} />
          <Input id="doc-room" label="Room" field="room_number" maxLength={20} {...p} />
          <Input id="doc-languages" label="Languages" field="languages" maxLength={200} placeholder="e.g. English, Urdu" {...p} />
        </div>
        <Input id="doc-qualifications" label="Qualifications" field="qualifications" maxLength={500} placeholder="e.g. MBBS, FCPS (Cardiology)" {...p} />
        <FormField id="doc-bio" label="Professional biography">
          <textarea id="doc-bio" rows={3} maxLength={1000} value={form.bio} onChange={(e) => setForm({ ...form, bio: e.target.value })} />
        </FormField>
      </fieldset>
    </ConfirmDialog>
  );
}

/** View Profile: the full staff record and career history, read-only. */
export function DoctorProfileDialog({ doctor: listed, canEditCareer, onClose }) {
  const [doctor, setDoctor] = useState(listed);
  const [career, setCareer] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    getDoctor(listed.id)
      .then((res) => live && setDoctor(res.data))
      .catch((err) => live && setError(getErrorMessage(err, "Could not load the latest details")));
    if (canEditCareer)
      getDoctorCareer(listed.id)
        .then((res) => live && setCareer(res.data))
        .catch(() => live && setCareer({ experience: [], education: [] }));
    return () => {
      live = false;
    };
  }, [listed.id, canEditCareer]);

  const rows = [
    ["Email", doctor.email],
    ["Phone", doctor.phone],
    ["Department", doctor.department_name],
    ["Specialization", doctor.specialization],
    ["Experience", experienceLabel(doctor.years_of_experience)],
    ["License no.", doctor.license_number],
    ["Qualifications", doctor.qualifications],
    ["Languages", doctor.languages],
    ["Consultation fee", doctor.consultation_fee == null ? null : formatFee(doctor.consultation_fee)],
    ["Room", doctor.room_number],
    ["Upcoming", doctor.upcoming_appointments == null ? null : `${doctor.upcoming_appointments} appointments`],
  ];
  return (
    <ConfirmDialog title="Doctor profile" confirmLabel="Close" cancelLabel="Back" onConfirm={onClose} onCancel={onClose} className="wide-dialog">
      <Alert>{error}</Alert>
      <div className="user-detail-head">
        <Avatar name={doctor.name} role="doctor" src={doctor.photo_url} size={72} alt={`Photo of ${doctor.name}`} />
        <div>
          <strong>{doctorName(doctor)}</strong>
          <div>
            <span className={`badge ${doctor.is_active ? "ok" : "danger"}`}>{doctor.is_active ? "Active" : "Inactive"}</span>{" "}
            {doctor.is_verified && <span className="badge info">License on file</span>}
          </div>
        </div>
      </div>
      <dl className="user-detail-list">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value || <span className="muted">Not provided</span>}</dd>
          </div>
        ))}
      </dl>
      {doctor.bio && <p>{doctor.bio}</p>}
      {career && (
        <>
          <h3 className="dept-subhead">Experience</h3>
          {career.experience.length === 0 ? (
            <p className="muted">None recorded.</p>
          ) : (
            <ul className="career-list">
              {career.experience.map((x, i) => (
                <li key={i}>
                  <strong>{x.title}</strong>, {x.organization} <span className="muted">({x.start_year}–{x.end_year ?? "present"})</span>
                </li>
              ))}
            </ul>
          )}
          <h3 className="dept-subhead">Education</h3>
          {career.education.length === 0 ? (
            <p className="muted">None recorded.</p>
          ) : (
            <ul className="career-list">
              {career.education.map((x, i) => (
                <li key={i}>
                  <strong>{x.qualification}</strong>, {x.institution} {x.end_year && <span className="muted">({x.end_year})</span>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {doctor.is_active && (
        <p>
          <Link to={`/doctors/${doctor.id}`}>Open public profile</Link>
        </p>
      )}
    </ConfirmDialog>
  );
}

/** Manage Department: move the doctor to another active department. */
export function DoctorDepartmentDialog({ doctor, departments, onClose, onSaved }) {
  const [target, setTarget] = useState(doctor.department_id);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (target === doctor.department_id) return onClose();
    setBusy(true);
    setError("");
    try {
      const res = await updateDoctor(doctor.id, { department_id: target });
      onSaved(`${doctorName(res.data)} moved to ${res.data.department_name}.`);
    } catch (err) {
      setError(getErrorMessage(err, "Could not change the department"));
      setBusy(false);
    }
  };
  return (
    <ConfirmDialog title="Manage department" confirmLabel="Save department" busy={busy} error={error} onConfirm={save} onCancel={onClose}>
      <p>
        {doctorName(doctor)} is in <strong>{doctor.department_name}</strong>. Their schedule and appointments stay as they are.
      </p>
      <FormField id="doc-move" label="Department">
        <select id="doc-move" value={target} onChange={(e) => setTarget(e.target.value)}>
          {!departments.some((d) => d.id === doctor.department_id) && <option value={doctor.department_id}>{doctor.department_name} (inactive)</option>}
          {departments.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </FormField>
    </ConfirmDialog>
  );
}
