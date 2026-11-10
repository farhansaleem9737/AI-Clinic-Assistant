import { ClipboardPlus, Pencil, Pill, Plus, ShieldAlert, Stethoscope, Trash2 } from "lucide-react";
import { useState } from "react";
import Alert from "../Alert";
import ConfirmDialog from "../ConfirmDialog";
import { useFetch } from "../../hooks/useFetch";
import { useRealtimeEvent, useRealtimeWatch } from "../../hooks/useRealtime";
import { getErrorMessage } from "../../services/api";
import { addHealthRecord, getHealthRecords, removeHealthRecord, updateHealthRecord } from "../../services/healthRecordService";
import { shortDate } from "../../utils/medical";

const SEVERITY = { mild: "Mild", moderate: "Moderate", severe: "Severe", unknown: "Severity not known" };
const DIAGNOSIS_STATUS = { active: "Active", resolved: "Resolved" };
const MEDICATION_STATUS = { active: "Taking now", stopped: "Stopped" };
const options = (labels) => Object.entries(labels).map(([value, label]) => ({ value, label }));

// What each kind shows and asks for. `viewer` is "patient" (their own record)
// or "clinician" (a treating doctor); it only changes the wording.
const KINDS = {
  allergies: {
    title: "Allergies",
    one: "allergy",
    icon: ShieldAlert,
    tone: "red",
    fields: [
      { name: "substance", label: "Allergic to", required: true, missing: "Enter what you are allergic to.", max: 120, placeholder: "e.g. Penicillin, peanuts, latex" },
      { name: "reaction", label: "Reaction", max: 200, placeholder: "e.g. Rash, swelling, trouble breathing" },
      { name: "severity", label: "Severity", type: "select", options: options(SEVERITY), initial: "unknown" },
    ],
    primary: (e) => e.substance,
    badge: (e) => ({ text: SEVERITY[e.severity], tone: `sev-${e.severity}` }),
    details: (e) => [e.reaction && `Reaction: ${e.reaction}`],
    empty: {
      patient: "Add any allergies you know of, such as to medicines, foods or latex. Your doctor sees them before treating you.",
      clinician: "Nothing reported by the patient or recorded by a doctor. Ask the patient about allergies at the visit.",
    },
  },
  diagnoses: {
    title: "Diagnoses",
    one: "diagnosis",
    icon: Stethoscope,
    tone: "purple",
    fields: [
      { name: "condition", label: "Condition", required: true, max: 200, placeholder: "e.g. Type 2 diabetes" },
      { name: "status", label: "Status", type: "select", options: options(DIAGNOSIS_STATUS), initial: "active", half: true },
      { name: "diagnosed_on", label: "Diagnosed on", type: "date", half: true },
      { name: "notes", label: "Notes", type: "textarea", max: 1000 },
    ],
    primary: (e) => e.condition,
    badge: (e) => ({ text: DIAGNOSIS_STATUS[e.status], tone: e.status === "active" ? "st-active" : "st-done" }),
    details: (e) => [e.diagnosed_on && `Diagnosed ${shortDate(e.diagnosed_on)}`, e.notes],
    empty: {
      patient: "Your doctor adds diagnoses to your record after a consultation. Findings in uploaded reports are not treated as diagnoses.",
      clinician: "No diagnoses recorded for this patient yet.",
    },
  },
  medications: {
    title: "Medications",
    one: "medication",
    icon: Pill,
    tone: "green",
    fields: [
      { name: "name", label: "Medicine", required: true, missing: "Enter the name of the medicine.", max: 200, placeholder: "e.g. Metformin" },
      { name: "dosage", label: "Dose", max: 100, placeholder: "e.g. 500 mg", half: true },
      { name: "frequency", label: "How often", max: 100, placeholder: "e.g. Twice a day", half: true },
      { name: "start_date", label: "Started", type: "date", half: true },
      { name: "end_date", label: "Until", type: "date", half: true },
      { name: "status", label: "Status", type: "select", options: options(MEDICATION_STATUS), initial: "active" },
      { name: "instructions", label: "Instructions", type: "textarea", max: 500, placeholder: "e.g. Take after meals" },
    ],
    primary: (e) => e.name,
    badge: (e) => ({ text: MEDICATION_STATUS[e.status], tone: e.status === "active" ? "st-active" : "st-done" }),
    details: (e) => [
      [e.dosage, e.frequency].filter(Boolean).join(" · "),
      (e.start_date || e.end_date) &&
        [e.start_date && `From ${shortDate(e.start_date)}`, e.end_date && `until ${shortDate(e.end_date)}`].filter(Boolean).join(" "),
      e.instructions,
    ],
    empty: {
      patient: "Medicines your doctor records appear here. You can also add medicines you take from elsewhere, so your doctor knows about them.",
      clinician: "No medications recorded for this patient yet.",
    },
  },
};

function sourceText(entry) {
  if (entry.source === "patient") return entry.recorded_by_me ? "Reported by you" : "Reported by the patient";
  return entry.recorded_by_me ? "Recorded by you" : `Recorded by ${entry.recorded_by ?? "a doctor"}`;
}

function EntryDialog({ kind, patientId, entry, onClose, onSaved }) {
  const { fields, one } = KINDS[kind];
  const [form, setForm] = useState(() =>
    Object.fromEntries(fields.map((f) => [f.name, entry?.[f.name] ?? f.initial ?? ""]))
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (name) => (e) => setForm({ ...form, [name]: e.target.value });

  const submit = async () => {
    const missing = fields.find((f) => f.required && !String(form[f.name]).trim());
    if (missing) return setError(missing.missing ?? `Enter the ${missing.label.toLowerCase()}.`);
    // Empty optional fields are sent as null.
    const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === "" ? null : v]));
    setBusy(true);
    setError("");
    try {
      const res = entry
        ? await updateHealthRecord(patientId, kind, entry.id, body)
        : await addHealthRecord(patientId, kind, body);
      onSaved(res.data);
    } catch (err) {
      setError(getErrorMessage(err, `The ${one} could not be saved.`));
      setBusy(false);
    }
  };

  const control = (f) => {
    const common = { value: form[f.name], disabled: busy, onChange: set(f.name) };
    if (f.type === "select")
      return (
        <select {...common}>
          {f.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      );
    if (f.type === "textarea") return <textarea {...common} rows={3} maxLength={f.max} placeholder={f.placeholder} />;
    return <input {...common} type={f.type ?? "text"} maxLength={f.max} placeholder={f.placeholder} required={f.required} />;
  };

  return (
    <ConfirmDialog
      title={entry ? `Edit ${one}` : `Add ${one === "allergy" ? "an" : "a"} ${one}`}
      confirmLabel="Save"
      busy={busy}
      error={error}
      onConfirm={submit}
      onCancel={onClose}
      className="hr-dialog"
    >
      <div className="med-upload-form hr-form">
        {fields.map((f) => (
          <label key={f.name} className={f.half ? "half" : undefined}>
            <span>
              {f.label}
              {!f.required && f.type !== "select" && <small className="muted"> (optional)</small>}
            </span>
            {control(f)}
          </label>
        ))}
      </div>
    </ConfirmDialog>
  );
}

/**
 * One kind of entry in a patient's record: the list, and adding, editing and
 * removing where the API allows it (`canAdd`, each entry's `can_edit`).
 */
export function HealthRecordSection({ kind, patientId, entries, canAdd, viewer, onChanged, headingLevel = 2 }) {
  const { title, one, icon: Icon, primary, badge, details, empty } = KINDS[kind];
  const [dialog, setDialog] = useState(null); // { mode: "edit" | "remove", entry }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const Heading = `h${headingLevel}`;

  const finish = (text) => {
    setDialog(null);
    onChanged(text);
  };
  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      await removeHealthRecord(patientId, kind, dialog.entry.id);
      setBusy(false);
      finish(`“${primary(dialog.entry)}” was removed.`);
    } catch (err) {
      setError(getErrorMessage(err, `The ${one} could not be removed.`));
      setBusy(false);
    }
  };

  return (
    <section className="hr-section" aria-label={title}>
      <div className="med-docs-head">
        <Heading className="hr-title">
          <Icon size={20} aria-hidden="true" /> {title} <span className="muted">({entries.length})</span>
        </Heading>
        {canAdd && (
          <button type="button" className="secondary" onClick={() => setDialog({ mode: "edit", entry: null })}>
            <Plus size={18} aria-hidden="true" /> Add {one}
          </button>
        )}
      </div>
      {entries.length === 0 ? (
        <div className="hr-empty">
          <p>
            <strong>No {title.toLowerCase()} recorded</strong>
          </p>
          <p className="muted">{empty[viewer]}</p>
        </div>
      ) : (
        <ul className="hr-list">
          {entries.map((e) => {
            const b = badge(e);
            return (
              <li key={e.id} className="hr-row">
                <div className="hr-main">
                  <div className="hr-name">
                    <strong>{primary(e)}</strong>
                    <span className={`hr-badge ${b.tone}`}>{b.text}</span>
                  </div>
                  {details(e)
                    .filter(Boolean)
                    .map((line, i) => (
                      <span key={i} className="hr-detail">
                        {line}
                      </span>
                    ))}
                  <small className={`hr-source ${e.source}`}>
                    {sourceText(e)} · {shortDate(e.created_at)}
                  </small>
                </div>
                {e.can_edit && (
                  <div className="med-doc-actions">
                    <button type="button" className="icon-button" aria-label={`Edit ${primary(e)}`} onClick={() => setDialog({ mode: "edit", entry: e })}>
                      <Pencil size={17} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="icon-button hr-remove"
                      aria-label={`Remove ${primary(e)}`}
                      onClick={() => {
                        setError("");
                        setDialog({ mode: "remove", entry: e });
                      }}
                    >
                      <Trash2 size={17} aria-hidden="true" />
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {dialog?.mode === "edit" && (
        <EntryDialog
          kind={kind}
          patientId={patientId}
          entry={dialog.entry}
          onClose={() => setDialog(null)}
          onSaved={(entry) => finish(`“${primary(entry)}” was ${dialog.entry ? "updated" : "added"}.`)}
        />
      )}
      {dialog?.mode === "remove" && (
        <ConfirmDialog
          title={`Remove this ${one}?`}
          confirmLabel="Remove"
          danger
          busy={busy}
          error={error}
          onConfirm={remove}
          onCancel={() => setDialog(null)}
        >
          <p>
            “{primary(dialog.entry)}” will no longer be shown in the record. Remove it only if it was added by mistake
            {kind === "allergies" ? " or is not an allergy." : kind === "medications" ? "; a medicine no longer taken can be marked Stopped instead." : "; a condition that has passed can be marked Resolved instead."}
          </p>
        </ConfirmDialog>
      )}
    </section>
  );
}

/**
 * A patient's allergies, diagnoses and medications for a treating doctor, on
 * the patient's page: all three at once, allergies first (checked before
 * anything is prescribed).
 */
export function PatientHealthRecords({ patientId }) {
  const [version, setVersion] = useState(0);
  const [notice, setNotice] = useState("");
  const { data, error, reload } = useFetch(() => getHealthRecords(patientId), [patientId], {
    refresh: version,
    errorMessage: "Could not load the patient's health records",
  });
  // Live (D122): the patient adds an allergy, or another doctor a diagnosis, while this page is open.
  useRealtimeWatch(patientId);
  useRealtimeEvent(["health_record."], (event) => {
    if (!event.payload || event.payload.patient_id === patientId) reload();
  });
  return (
    <section className="card hr-card" aria-labelledby="hr-card-title">
      <h2 id="hr-card-title" className="hr-card-title" tabIndex={-1}>
        <ClipboardPlus size={22} aria-hidden="true" /> Clinical Record
      </h2>
      <div aria-live="polite">
        <Alert kind="success">{notice}</Alert>
      </div>
      {error ? (
        <div className="med-state" role="alert">
          <p>{error}</p>
          <button type="button" className="secondary" onClick={() => setVersion((v) => v + 1)}>
            Try again
          </button>
        </div>
      ) : !data ? (
        <div className="med-state" role="status" aria-label="Loading health records">
          <div className="skeleton" style={{ height: 64 }} />
          <div className="skeleton" style={{ height: 64 }} />
        </div>
      ) : (
        ["allergies", "diagnoses", "medications"].map((kind) => (
          <HealthRecordSection
            key={kind}
            kind={kind}
            patientId={patientId}
            entries={data[kind]}
            canAdd={data[`can_add_${kind}`]}
            viewer="clinician"
            headingLevel={3}
            onChanged={(text) => {
              setNotice(text);
              setVersion((v) => v + 1);
            }}
          />
        ))
      )}
    </section>
  );
}
