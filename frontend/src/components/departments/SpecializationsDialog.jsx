import { Pencil, Plus, Search } from "lucide-react";
import { useState } from "react";
import { useFetch } from "../../hooks/useFetch";
import { getErrorMessage } from "../../services/api";
import { createSpecialization, listSpecializations, updateSpecialization } from "../../services/catalogService";
import { listDepartments } from "../../services/departmentService";
import Alert from "../Alert";
import ConfirmDialog from "../ConfirmDialog";

const EMPTY = { id: null, name: "", aliases: "", description: "", department_ids: [], is_active: true };
const toForm = (s) => ({ id: s.id, name: s.name, aliases: s.aliases.join(", "), description: s.description ?? "", department_ids: s.department_ids, is_active: s.is_active });

/**
 * The catalog's specializations (D118): of one department when `department`
 * is given, otherwise all, with search and a department filter. Add, edit,
 * assign to departments, retire or restore. Retiring never removes a
 * specialization from doctors who have it; it only hides it from new choices
 * and from the directory filters.
 */
export default function SpecializationsDialog({ department, onClose, onChanged }) {
  const [scope, setScope] = useState(department?.id ?? "");
  const [term, setTerm] = useState("");
  const [status, setStatus] = useState("");
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState(0);
  const departments = useFetch(() => listDepartments({ page_size: 100 }), [], { query: "departments/catalog-picker" });
  const list = useFetch(
    () => listSpecializations({ department_id: scope || undefined, is_active: status === "" ? undefined : status === "active" }),
    [scope, status],
    { query: "specializations/admin", refresh: attempt }
  );
  const allDepartments = departments.data?.items ?? [];
  const nameOf = (id) => allDepartments.find((d) => d.id === id)?.name ?? "Department";
  const needle = term.trim().toLowerCase();
  const rows = (list.data ?? []).filter(
    (s) => !needle || s.name.toLowerCase().includes(needle) || s.aliases.some((a) => a.includes(needle))
  );

  const startAdd = () => {
    setNotice("");
    setError("");
    setForm({ ...EMPTY, department_ids: scope ? [scope] : [] });
  };
  const toggleDepartment = (id) =>
    setForm((f) => ({ ...f, department_ids: f.department_ids.includes(id) ? f.department_ids.filter((x) => x !== id) : [...f.department_ids, id] }));

  const save = async (e) => {
    e?.preventDefault();
    if (!form.name.trim()) return setError("Enter the specialization's name.");
    if (!form.department_ids.length) return setError("Choose at least one department.");
    setBusy(true);
    setError("");
    const body = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      aliases: form.aliases.split(",").map((a) => a.trim()).filter(Boolean),
      department_ids: form.department_ids,
      is_active: form.is_active,
    };
    try {
      const saved = (await (form.id ? updateSpecialization(form.id, body) : createSpecialization(body))).data;
      setNotice(form.id ? `Saved ${saved.name}.` : `Added ${saved.name}.`);
      setForm(null);
      setAttempt((n) => n + 1);
      onChanged?.();
    } catch (err) {
      setError(getErrorMessage(err, "Could not save the specialization"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      title={department ? `Specializations in ${department.name}` : "Specializations"}
      confirmLabel="Done"
      cancelLabel="Close"
      busy={busy}
      onConfirm={onClose}
      onCancel={onClose}
      className="wide-dialog specializations-dialog"
    >
      <div className="spec-admin-toolbar">
        <div className="input-icon">
          <Search size={16} aria-hidden="true" />
          <input type="search" aria-label="Search specializations" placeholder="Search name or alias…" value={term} onChange={(e) => setTerm(e.target.value)} />
        </div>
        {!department && (
          <label>
            <span className="sr-only">Department</span>
            <select aria-label="Filter by department" value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="">All departments</option>
              {allDepartments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          <span className="sr-only">Status</span>
          <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Active and retired</option>
            <option value="active">Active</option>
            <option value="retired">Retired</option>
          </select>
        </label>
        <button type="button" className="small-button" onClick={startAdd}>
          <Plus size={15} aria-hidden="true" /> Add specialization
        </button>
      </div>

      <Alert kind="success">{notice}</Alert>

      {form && (
        <form className="spec-admin-form" onSubmit={save} aria-label={form.id ? `Edit ${form.name}` : "New specialization"}>
          <label>
            Name
            <input value={form.name} maxLength={120} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </label>
          <label>
            Other names (aliases)
            <input value={form.aliases} onChange={(e) => setForm({ ...form, aliases: e.target.value })} placeholder="e.g. cardiologist, heart specialist" />
            <small className="muted">Comma-separated. Used by search and the assistant; each alias belongs to one specialization.</small>
          </label>
          <label>
            Description
            <input value={form.description} maxLength={500} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </label>
          <fieldset className="spec-admin-departments">
            <legend>Departments</legend>
            {allDepartments.map((d) => (
              <label key={d.id} className="checkbox">
                <input type="checkbox" checked={form.department_ids.includes(d.id)} onChange={() => toggleDepartment(d.id)} /> {d.name}
              </label>
            ))}
          </fieldset>
          <label className="checkbox">
            <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Active (offered in filters and on doctor profiles)
          </label>
          <Alert>{error}</Alert>
          <div className="row">
            <button type="button" className="secondary" onClick={() => setForm(null)} disabled={busy}>
              Cancel
            </button>
            <button type="submit" disabled={busy}>
              {busy ? "Saving…" : form.id ? "Save specialization" : "Add specialization"}
            </button>
          </div>
        </form>
      )}

      {list.error ? (
        <Alert>{list.error}</Alert>
      ) : list.loading && !list.data ? (
        <div className="skeleton" style={{ height: 120 }} role="status" aria-label="Loading specializations" />
      ) : rows.length === 0 ? (
        <p className="muted">{needle ? `No specialization matches “${term.trim()}”.` : "No specializations here yet."}</p>
      ) : (
        <ul className="spec-admin-list" aria-label="Specializations">
          {rows.map((s) => (
            <li key={s.id} className={s.is_active ? "" : "retired"}>
              <div>
                <strong>{s.name}</strong>
                {!s.is_active && <span className="badge danger">Retired</span>}
                <p className="muted small">
                  {s.department_ids.map(nameOf).join(", ")} · {s.doctor_count} doctor{s.doctor_count === 1 ? "" : "s"}
                  {s.aliases.length ? ` · also: ${s.aliases.slice(0, 4).join(", ")}` : ""}
                </p>
              </div>
              <button type="button" className="secondary small-button" aria-label={`Edit ${s.name}`} onClick={() => { setNotice(""); setError(""); setForm(toForm(s)); }}>
                <Pencil size={14} aria-hidden="true" /> Edit
              </button>
            </li>
          ))}
        </ul>
      )}
    </ConfirmDialog>
  );
}
