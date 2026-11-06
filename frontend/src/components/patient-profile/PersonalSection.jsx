import { Calendar, Camera, Check, CircleCheck, CircleSlash, IdCard, Lock, UserSquare } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import Avatar from "../Avatar";
import ChangePasswordModal from "../ChangePasswordModal";
import ConfirmDialog from "../ConfirmDialog";
import FormField from "../FormField";
import { useUnsavedChanges } from "../../hooks/useUnsavedChanges";
import { getErrorMessage } from "../../services/api";
import { MAX_PHOTO_BYTES } from "../../services/files";
import { removeMyPatientPhoto, updateMyDetails, uploadMyPatientPhoto } from "../../services/patientService";
import { shortDate } from "../../utils/medical";
import { patientFullName } from "../../utils/patient";
import { BLOOD_GROUPS, MARITAL_STATUSES, personalErrors } from "../../utils/profileForms";
import { GENDER_OPTIONS, errorProps, splitFullName, todayIso } from "../../utils/validation";

const PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp"];

// The form's values from a saved profile; Cancel goes back to exactly these.
const fromProfile = (p) => ({
  full_name: patientFullName(p),
  date_of_birth: p.date_of_birth ?? "",
  sex_at_birth: p.sex_at_birth ?? "unknown",
  blood_group: p.blood_group ?? "",
  marital_status: p.marital_status ?? "",
  national_id: "",
  national_id_editing: false,
  national_id_remove: false,
  country: p.country ?? "",
});

/** Only what changed, in the API's shape (PATCH /patients/me leaves the rest as it is). */
function changes(form, profile) {
  const out = {};
  if (form.full_name.trim() !== patientFullName(profile)) Object.assign(out, splitFullName(form.full_name));
  if (form.date_of_birth !== profile.date_of_birth) out.date_of_birth = form.date_of_birth;
  if (form.sex_at_birth !== profile.sex_at_birth) out.sex_at_birth = form.sex_at_birth;
  if ((form.blood_group || null) !== (profile.blood_group ?? null)) out.blood_group = form.blood_group || null;
  if ((form.marital_status || null) !== (profile.marital_status ?? null)) out.marital_status = form.marital_status || null;
  if (form.national_id_remove) out.national_id = null;
  else if (form.national_id_editing && form.national_id.trim()) out.national_id = form.national_id.trim();
  return out;
}

/** The camera button: pick a picture, see it, then save it (the server checks and stores it). */
function AvatarEditor({ profile, onSaved }) {
  const input = useRef(null);
  const [pending, setPending] = useState(null); // { file, preview }
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => () => pending && URL.revokeObjectURL(pending.preview), [pending]);

  const choose = (file) => {
    setError("");
    if (!file) return;
    if (!PHOTO_TYPES.includes(file.type)) return setError("Choose a JPEG, PNG or WebP picture.");
    if (file.size > MAX_PHOTO_BYTES) return setError("The picture must be 5 MB or smaller.");
    setPending({ file, preview: URL.createObjectURL(file) });
  };
  const run = async (action) => {
    setBusy(true);
    setError("");
    try {
      onSaved((await action()).data);
      setPending(null);
    } catch (err) {
      setError(getErrorMessage(err, "The picture could not be saved."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pp-avatar">
      <Avatar name={patientFullName(profile)} src={profile.photo_url} size={132} />
      <button type="button" className="pp-camera" aria-label="Change profile picture" onClick={() => input.current?.click()} disabled={busy}>
        <Camera size={18} aria-hidden="true" />
      </button>
      <input ref={input} type="file" accept={PHOTO_TYPES.join(",")} hidden onChange={(e) => { choose(e.target.files?.[0]); e.target.value = ""; }} aria-label="Profile picture file" />
      {profile.photo_url && !pending && (
        <button type="button" className="link-button small" onClick={() => run(removeMyPatientPhoto)} disabled={busy}>
          Remove picture
        </button>
      )}
      {error && !pending && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      {pending && (
        <ConfirmDialog title="New profile picture" confirmLabel="Save picture" busy={busy} onConfirm={() => run(() => uploadMyPatientPhoto(pending.file))} onCancel={() => setPending(null)}>
          <img className="pp-preview" src={pending.preview} alt="Preview of the new profile picture" />
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}

function OverviewCard({ profile, status, memberSince, onSaved }) {
  return (
    <section className="card pp-overview" aria-label="Profile overview">
      <AvatarEditor profile={profile} onSaved={onSaved} />
      <h2>{patientFullName(profile)}</h2>
      <p className="muted">Patient</p>
      {status && (
        <span className={`pp-status ${status.active ? "active" : "inactive"}`}>
          {status.active ? <CircleCheck size={14} aria-hidden="true" /> : <CircleSlash size={14} aria-hidden="true" />}
          {status.active ? "Active" : "Inactive"}
        </span>
      )}
      <dl className="pp-facts">
        <div>
          <dt>
            <IdCard size={17} aria-hidden="true" /> MRN
          </dt>
          <dd>{profile.mrn}</dd>
        </div>
        <div>
          <dt>
            <Calendar size={17} aria-hidden="true" /> Member Since
          </dt>
          <dd>{memberSince ? shortDate(memberSince) : "—"}</dd>
        </div>
      </dl>
      <p className="muted small">Your medical record number is assigned by the clinic and cannot be changed.</p>
    </section>
  );
}

/**
 * Personal Information (D111): the overview (photo, MRN, member since) and the
 * basic details form. Only changed fields are sent; the screen shows them
 * only after the server saved them.
 */
export default function PersonalSection({ profile, status, memberSince, onSaved, onNotice }) {
  const [changingPassword, setChangingPassword] = useState(false);
  const initial = useMemo(() => fromProfile(profile), [profile]);
  const [form, setForm] = useState(initial);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = changes(form, profile);
  const dirty = Object.keys(pending).length > 0 || (form.national_id_editing && Boolean(form.national_id.trim()));
  useUnsavedChanges(dirty);
  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const cancel = () => {
    setForm(initial);
    setErrors({});
    setError("");
  };
  const save = async (e) => {
    e.preventDefault();
    if (busy || !dirty) return;
    const found = personalErrors(form);
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError("");
    try {
      const updated = (await updateMyDetails(pending)).data;
      onSaved(updated, "Your personal details were saved.");
      setForm(fromProfile(updated));
    } catch (err) {
      setError(getErrorMessage(err, "Your changes could not be saved. Please try again."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pp-layout">
      <OverviewCard profile={profile} status={status} memberSince={memberSince} onSaved={(updated) => onSaved(updated, "Your profile picture was updated.")} />
      <form className="card pp-form" onSubmit={save} noValidate aria-labelledby="basic-details-title">
        <h2 id="basic-details-title">
          <UserSquare size={22} aria-hidden="true" /> Basic Details
        </h2>
        <div className="pp-grid">
          <FormField id="pp-full-name" label="Full Name *" error={errors.full_name}>
            <input id="pp-full-name" value={form.full_name} maxLength={100} autoComplete="name" onChange={set("full_name")} {...errorProps("pp-full-name", errors.full_name)} />
          </FormField>
          <FormField id="pp-dob" label="Date of Birth *" error={errors.date_of_birth}>
            <input id="pp-dob" type="date" value={form.date_of_birth} max={todayIso()} onChange={set("date_of_birth")} {...errorProps("pp-dob", errors.date_of_birth)} />
          </FormField>
          <fieldset className="pp-gender">
            <legend>Gender *</legend>
            <div className="pp-radios">
              {GENDER_OPTIONS.map((o) => (
                <label key={o.value} className={form.sex_at_birth === o.value ? "selected" : ""}>
                  <input type="radio" name="sex_at_birth" value={o.value} checked={form.sex_at_birth === o.value} onChange={set("sex_at_birth")} />
                  {o.label}
                </label>
              ))}
            </div>
          </fieldset>
          <FormField id="pp-blood" label="Blood Group">
            <select id="pp-blood" value={form.blood_group} onChange={set("blood_group")}>
              <option value="">Not set</option>
              {BLOOD_GROUPS.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </FormField>
          <FormField id="pp-national-id" label="CNIC / National ID (Optional)" error={errors.national_id}>
            {form.national_id_editing ? (
              <input
                id="pp-national-id"
                value={form.national_id}
                maxLength={30}
                inputMode={!form.country || form.country === "PK" ? "numeric" : "text"}
                placeholder={!form.country || form.country === "PK" ? "12345-1234567-1" : "Your national ID"}
                autoComplete="off"
                onChange={set("national_id")}
                {...errorProps("pp-national-id", errors.national_id)}
              />
            ) : (
              <div className="pp-masked">
                <span id="pp-national-id" aria-label={profile.national_id_masked ? "Saved national ID, shown masked" : "No national ID saved"}>
                  {form.national_id_remove ? "Will be removed" : (profile.national_id_masked ?? "Not provided")}
                </span>
                <button type="button" className="link-button" onClick={() => setForm({ ...form, national_id_editing: true, national_id_remove: false })}>
                  {profile.national_id_masked ? "Change" : "Add"}
                </button>
                {profile.national_id_masked && !form.national_id_remove && (
                  <button type="button" className="link-button" onClick={() => setForm({ ...form, national_id_remove: true })}>
                    Remove
                  </button>
                )}
              </div>
            )}
          </FormField>
          <FormField id="pp-marital" label="Marital Status">
            <select id="pp-marital" value={form.marital_status} onChange={set("marital_status")}>
              <option value="">Not set</option>
              {MARITAL_STATUSES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </FormField>
        </div>
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        <div className="pp-actions">
          <button type="button" className="secondary pp-actions-start" onClick={() => setChangingPassword(true)}>
            <Lock size={17} aria-hidden="true" /> Change Password
          </button>
          <button type="button" className="secondary" onClick={cancel} disabled={busy || !dirty}>
            Cancel
          </button>
          <button type="submit" disabled={busy || !dirty} aria-busy={busy}>
            <Check size={17} aria-hidden="true" /> {busy ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </form>
      {changingPassword && <ChangePasswordModal onClose={() => setChangingPassword(false)} onChanged={onNotice} />}
    </div>
  );
}

