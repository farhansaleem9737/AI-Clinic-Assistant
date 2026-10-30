import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getErrorMessage } from "../../services/api";
import { createDepartment, getDepartment, getPublicDepartments, updateDepartment } from "../../services/departmentService";
import { listDoctors, updateDoctor } from "../../services/doctorService";
import { COLOR_KEYS, doctorLabel, ICON_KEYS, ICON_LABELS, timezoneLabel, timezoneOptions, validateDepartment } from "../../utils/departments";
import Alert from "../Alert";
import Avatar from "../Avatar";
import ConfirmDialog from "../ConfirmDialog";
import FormField from "../FormField";
import DepartmentIcon from "./DepartmentIcon";

const when = (iso) => new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));

/** Add or edit a department. `department` = edit; otherwise create. */
export function DepartmentFormDialog({ department, defaultTimezone, onClose, onSaved }) {
  const editing = Boolean(department);
  const [form, setForm] = useState(() => ({
    name: department?.name ?? "",
    description: department?.description ?? "",
    timezone: department?.timezone ?? defaultTimezone,
    icon: department?.icon ?? "",
    color: department?.color ?? "",
    is_active: department?.is_active ?? true,
  }));
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const zones = timezoneOptions();
  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const save = async () => {
    const found = validateDepartment(form);
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError("");
    const body = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      timezone: form.timezone,
      icon: form.icon || null,
      color: form.color || null,
    };
    try {
      const res = editing ? await updateDepartment(department.id, body) : await createDepartment({ ...body, is_active: form.is_active });
      onSaved(res.data);
    } catch (err) {
      const code = err?.response?.data?.error?.code;
      if (code === "DEPARTMENT_EXISTS") setErrors({ name: "A department with this name already exists." });
      else setError(getErrorMessage(err, "Could not save the department"));
      setBusy(false);
    }
  };

  const fieldError = (name) => (errors[name] ? { "aria-invalid": true, "aria-describedby": `dept-${name}-error` } : {});
  return (
    <ConfirmDialog
      title={editing ? "Edit Department" : "Add Department"}
      confirmLabel={editing ? "Save changes" : "Add Department"}
      busy={busy}
      error={error}
      onConfirm={save}
      onCancel={onClose}
      className="wide-dialog"
    >
      <div className="dept-preview">
        <DepartmentIcon department={{ name: form.name, icon: form.icon || null, color: form.color || null }} size={48} />
        <span className="muted small">Preview</span>
      </div>
      <FormField id="dept-name" label="Department name" error={errors.name}>
        <input id="dept-name" value={form.name} maxLength={100} onChange={set("name")} {...fieldError("name")} />
      </FormField>
      <FormField id="dept-description" label="Description (optional)" error={errors.description}>
        <textarea id="dept-description" rows={2} maxLength={500} value={form.description} onChange={set("description")} {...fieldError("description")} />
      </FormField>
      <FormField id="dept-timezone" label="Timezone" error={errors.timezone}>
        <select id="dept-timezone" value={form.timezone} onChange={set("timezone")} {...fieldError("timezone")}>
          {zones.map((z) => (
            <option key={z} value={z}>
              {timezoneLabel(z)} · {z}
            </option>
          ))}
        </select>
      </FormField>
      <div className="dept-form-row">
        <FormField id="dept-icon" label="Icon (optional)">
          <select id="dept-icon" value={form.icon} onChange={set("icon")}>
            <option value="">Automatic</option>
            {ICON_KEYS.map((k) => (
              <option key={k} value={k}>
                {ICON_LABELS[k]}
              </option>
            ))}
          </select>
        </FormField>
        <FormField id="dept-color" label="Icon colour (optional)">
          <select id="dept-color" value={form.color} onChange={set("color")}>
            <option value="">Automatic</option>
            {COLOR_KEYS.map((k) => (
              <option key={k} value={k}>
                {k[0].toUpperCase() + k.slice(1)}
              </option>
            ))}
          </select>
        </FormField>
        {!editing && (
          <FormField id="dept-status" label="Status">
            <select id="dept-status" value={String(form.is_active)} onChange={(e) => setForm({ ...form, is_active: e.target.value === "true" })}>
              <option value="true">Active</option>
              <option value="false">Inactive</option>
            </select>
          </FormField>
        )}
      </div>
      {editing && <p className="muted small">Status is changed with Activate / Deactivate in the actions menu.</p>}
    </ConfirmDialog>
  );
}

function useDepartmentDetail(id, attempt = 0) {
  const [state, setState] = useState({ detail: null, error: "" });
  useEffect(() => {
    let live = true;
    getDepartment(id)
      .then((res) => live && setState({ detail: res.data, error: "" }))
      .catch((err) => live && setState({ detail: null, error: getErrorMessage(err, "Could not load the department") }));
    return () => {
      live = false;
    };
  }, [id, attempt]);
  return state;
}

export function DepartmentDetailsDialog({ department, onClose }) {
  const { detail, error } = useDepartmentDetail(department.id);
  const d = detail ?? department;
  return (
    <ConfirmDialog title="Department details" confirmLabel="Close" cancelLabel="Back" onConfirm={onClose} onCancel={onClose} className="wide-dialog">
      <Alert>{error}</Alert>
      <div className="user-detail-head">
        <DepartmentIcon department={d} size={56} />
        <strong>{d.name}</strong>
        <span className={`badge ${d.is_active ? "ok" : "danger"}`}>{d.is_active ? "Active" : "Inactive"}</span>
      </div>
      <dl className="user-detail-list">
        <div>
          <dt>Description</dt>
          <dd>{d.description || <span className="muted">None</span>}</dd>
        </div>
        <div>
          <dt>Timezone</dt>
          <dd>
            {timezoneLabel(d.timezone)} <span className="muted">({d.timezone})</span>
          </dd>
        </div>
        <div>
          <dt>Doctors</dt>
          <dd>{d.doctor_count} practising</dd>
        </div>
        {detail && (
          <div>
            <dt>Upcoming</dt>
            <dd>{detail.upcoming_appointments} appointments</dd>
          </div>
        )}
        <div>
          <dt>Created</dt>
          <dd>{when(d.created_at)}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{when(d.updated_at)}</dd>
        </div>
      </dl>
      {!detail && !error && <p role="status">Loading doctors…</p>}
      {detail && (
        <ul className="dept-doctor-list" aria-label="Doctors in this department">
          {detail.doctors.length === 0 && <li className="muted">No doctors in this department.</li>}
          {detail.doctors.map((doc) => (
            <li key={doc.id}>
              <Avatar name={doc.name} role="doctor" src={doc.photo_url} size={36} />
              <span>
                <strong>{doctorLabel(doc)}</strong>
                <span className="muted small"> {doc.specialization}</span>
              </span>
              {!doc.is_active && <span className="badge danger">Inactive</span>}
            </li>
          ))}
        </ul>
      )}
    </ConfirmDialog>
  );
}

/**
 * Manage Doctors. A doctor belongs to exactly one department (D89), so
 * "adding" moves a doctor here from their current department and "removing"
 * moves them to another active one. Both go through PATCH /doctors/{id}.
 */
export function ManageDoctorsDialog({ department, onClose, onChanged }) {
  const [attempt, setAttempt] = useState(0);
  const { detail, error } = useDepartmentDetail(department.id, attempt);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [targets, setTargets] = useState([]);
  const [moving, setMoving] = useState(null); // doctor being moved out
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    getPublicDepartments()
      .then((res) => setTargets(res.data.items.filter((d) => d.id !== department.id)))
      .catch(() => setTargets([]));
  }, [department.id]);

  const search = async (e) => {
    e.preventDefault();
    setActionError("");
    try {
      const res = await listDoctors({ q: query.trim() || undefined, page_size: 20 });
      setResults(res.data.items.filter((d) => d.department_id !== department.id));
    } catch (err) {
      setActionError(getErrorMessage(err, "Could not search doctors"));
    }
  };

  const move = async (doctor, departmentId, message) => {
    setBusy(true);
    setActionError("");
    setNotice("");
    try {
      await updateDoctor(doctor.id, { department_id: departmentId });
      setNotice(message);
      setMoving(null);
      setTarget("");
      setResults((r) => r?.filter((d) => d.id !== doctor.id) ?? r);
      setAttempt((n) => n + 1);
      onChanged();
    } catch (err) {
      setActionError(getErrorMessage(err, "Could not move the doctor"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog title={`Manage doctors: ${department.name}`} confirmLabel="Done" cancelLabel="Close" onConfirm={onClose} onCancel={onClose} className="wide-dialog">
      <Alert>{error || actionError}</Alert>
      <Alert kind="success">{notice}</Alert>
      {!department.is_active && <Alert kind="warn">This department is inactive: doctors cannot be moved into it until it is activated.</Alert>}
      <h3 className="dept-subhead">Assigned doctors</h3>
      {!detail && !error && <p role="status">Loading doctors…</p>}
      {detail && (
        <ul className="dept-doctor-list" aria-label="Assigned doctors">
          {detail.doctors.length === 0 && <li className="muted">No doctors assigned yet.</li>}
          {detail.doctors.map((doc) => (
            <li key={doc.id}>
              <Avatar name={doc.name} role="doctor" src={doc.photo_url} size={36} />
              <span>
                <strong>{doctorLabel(doc)}</strong>
                <span className="muted small"> {doc.specialization}</span>
              </span>
              {!doc.is_active && <span className="badge danger">Inactive</span>}
              {moving?.id === doc.id ? (
                <span className="dept-move">
                  <label>
                    <span className="sr-only">Move {doc.name} to</span>
                    <select value={target} onChange={(e) => setTarget(e.target.value)}>
                      <option value="">Move to…</option>
                      {targets.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button type="button" className="small-button" disabled={!target || busy}
                    onClick={() => move(doc, target, `${doc.name} moved to ${targets.find((t) => t.id === target)?.name}.`)}>
                    Move
                  </button>
                  <button type="button" className="secondary small-button" onClick={() => setMoving(null)}>
                    Cancel
                  </button>
                </span>
              ) : (
                <button type="button" className="secondary small-button" aria-label={`Remove ${doc.name} from ${department.name}`}
                  onClick={() => { setTarget(""); setMoving(doc); }}>
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {department.is_active && (
        <>
          <h3 className="dept-subhead">Add doctors</h3>
          <form className="dept-doctor-search" role="search" onSubmit={search}>
            <Search size={18} aria-hidden="true" />
            <input type="search" aria-label="Search doctors to add" placeholder="Search doctors by name…" value={query} onChange={(e) => setQuery(e.target.value)} />
            <button type="submit" className="secondary small-button">Search</button>
          </form>
          {results && (
            <ul className="dept-doctor-list" aria-label="Doctors you can add">
              {results.length === 0 && <li className="muted">No doctors from other departments match.</li>}
              {results.map((doc) => (
                <li key={doc.id}>
                  <Avatar name={doc.name} role="doctor" src={doc.photo_url} size={36} />
                  <span>
                    <strong>{doctorLabel(doc)}</strong>
                    <span className="muted small"> now in {doc.department_name}</span>
                  </span>
                  <button type="button" className="small-button" disabled={busy} aria-label={`Add ${doc.name} to ${department.name}`}
                    onClick={() => move(doc, department.id, `${doc.name} moved to ${department.name}.`)}>
                    Add
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <p className="muted small">
        A doctor works in one department. <Link to={`/admin/doctors?department=${department.id}`}>Open in Doctors</Link>
      </p>
    </ConfirmDialog>
  );
}
