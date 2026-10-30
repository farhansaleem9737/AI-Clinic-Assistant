import { Building2, ServerCog } from "lucide-react";
import { useEffect, useState } from "react";
import Alert from "../components/Alert";
import { getErrorMessage } from "../services/api";
import { getClinicSettings, updateClinicSettings } from "../services/workspaceService";
import { EMAIL_PATTERN } from "../utils/validation";

const FIELDS = ["clinic_name", "contact_phone", "contact_email", "address"];
const PHONE_PATTERN = /^\+?[0-9(][0-9 ()\-.]{3,28}$/;
const formValues = (data) => Object.fromEntries(FIELDS.map((f) => [f, data[f] ?? ""]));

function validate(form) {
  const errors = {};
  if (form.contact_email.trim() && !EMAIL_PATTERN.test(form.contact_email.trim())) errors.contact_email = "Enter a valid email address.";
  if (form.contact_phone.trim() && !PHONE_PATTERN.test(form.contact_phone.trim()))
    errors.contact_phone = "Use digits, spaces, dashes or brackets, with an optional leading +.";
  return errors;
}

/**
 * Administrator settings (D86): the clinic's name and contact details,
 * stored in the database. Operational rules are server configuration and
 * are shown read-only, with why.
 */
export default function AdminSettings() {
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [errors, setErrors] = useState({});
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getClinicSettings()
      .then((res) => {
        if (cancelled) return;
        setData(res.data);
        setForm(formValues(res.data));
      })
      .catch((err) => !cancelled && setLoadError(getErrorMessage(err, "Could not load the settings")));
    return () => {
      cancelled = true;
    };
  }, []);

  const bind = (field) => ({
    id: `settings-${field}`,
    value: form[field],
    onChange: (e) => {
      setForm({ ...form, [field]: e.target.value });
      setErrors({ ...errors, [field]: undefined });
      setNotice("");
    },
    "aria-invalid": errors[field] ? true : undefined,
    "aria-describedby": errors[field] ? `settings-${field}-error` : undefined,
    disabled: saving,
  });
  const fieldError = (field) =>
    errors[field] && (
      <small className="field-error" id={`settings-${field}-error`}>
        {errors[field]}
      </small>
    );

  const save = async (e) => {
    e.preventDefault();
    const found = validate(form);
    setErrors(found);
    setSaveError("");
    if (Object.keys(found).length) return;
    setSaving(true);
    try {
      const res = await updateClinicSettings(Object.fromEntries(FIELDS.map((f) => [f, form[f].trim() || null])));
      setData(res.data);
      setForm(formValues(res.data));
      setNotice("Settings saved.");
    } catch (err) {
      setSaveError(getErrorMessage(err, "Could not save the settings"));
    } finally {
      setSaving(false);
    }
  };

  if (!form) {
    return (
      <div>
        <h1>Settings</h1>
        {loadError ? <Alert>{loadError}</Alert> : <div className="card skeleton" style={{ height: 260 }} role="status" aria-label="Loading settings" />}
      </div>
    );
  }

  const op = data.operational;
  return (
    <div className="admin-settings">
      <header className="schedule-head">
        <h1>Settings</h1>
        <p className="muted">The clinic&apos;s details and how scheduling is configured.</p>
      </header>
      <div className="pd-grid">
        <form className="card" onSubmit={save} noValidate aria-labelledby="settings-clinic-title">
          <div className="pd-card-head">
            <Building2 className="pd-icon" size={26} aria-hidden="true" />
            <h2 id="settings-clinic-title">Clinic Details</h2>
          </div>
          <Alert kind="success">{notice}</Alert>
          <Alert>{saveError}</Alert>
          <div className="settings-fields">
            <div className="edit-field">
              <label htmlFor="settings-clinic_name">Clinic name</label>
              <input maxLength={120} {...bind("clinic_name")} />
            </div>
            <div className="edit-field">
              <label htmlFor="settings-contact_phone">Contact phone</label>
              <input type="tel" maxLength={30} {...bind("contact_phone")} />
              {fieldError("contact_phone")}
            </div>
            <div className="edit-field">
              <label htmlFor="settings-contact_email">Contact email</label>
              <input type="email" maxLength={255} {...bind("contact_email")} />
              {fieldError("contact_email")}
            </div>
            <div className="edit-field">
              <label htmlFor="settings-address">Address</label>
              <textarea rows={3} maxLength={500} {...bind("address")} />
            </div>
          </div>
          <div className="row settings-actions">
            <button type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save settings"}
            </button>
            {data.updated_at && (
              <span className="muted small">
                Last saved {new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(data.updated_at))}
              </span>
            )}
          </div>
        </form>

        <section className="card info-card" aria-labelledby="settings-ops-title">
          <div className="section-head">
            <ServerCog className="icon" size={22} aria-hidden="true" />
            <h3 id="settings-ops-title">Scheduling (server configuration)</h3>
          </div>
          <dl className="info-list ruled">
            <div>
              <dt>Clinic timezone</dt>
              <dd>{op.timezone}</dd>
            </div>
            <div>
              <dt>Default slot length</dt>
              <dd>{op.default_slot_minutes} minutes</dd>
            </div>
            <div>
              <dt>Booking notice</dt>
              <dd>{op.booking_min_lead_minutes} minutes</dd>
            </div>
            <div>
              <dt>Book up to</dt>
              <dd>{op.booking_max_advance_days} days ahead</dd>
            </div>
            <div>
              <dt>Patient cancellation</dt>
              <dd>Up to {op.patient_cancellation_cutoff_minutes} minutes before</dd>
            </div>
          </dl>
          <p className="muted small info-footnote">
            These are set in the server&apos;s configuration (.env) because changing them affects existing bookings. Each
            doctor&apos;s own slot length is set on their weekly schedule.
          </p>
        </section>
      </div>
    </div>
  );
}
