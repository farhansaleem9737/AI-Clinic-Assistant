import { useCallback, useEffect, useState } from "react";
import Alert from "../components/Alert";
import Pager from "../components/Pager";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { getPublicDepartments } from "../services/departmentService";
import {
  activateDoctor,
  createDoctor,
  deactivateDoctor,
  listDoctors,
  updateDoctor,
} from "../services/doctorService";
import { listUsers } from "../services/userService";
import { cleanParams, doctorName, formatFee } from "../utils/format";

const PAGE_SIZE = 20;
const PROFILE_FIELDS = {
  department_id: "",
  title: "Dr.",
  specialization: "",
  license_number: "",
  qualifications: "",
  years_of_experience: 0,
  consultation_fee: "",
  phone: "",
  room_number: "",
  bio: "",
};
const EMPTY_FORM = { mode: "account", user_id: "", name: "", email: "", password: "", ...PROFILE_FIELDS };

// Empty strings become null; the fee stays a decimal string (never a float).
function profilePayload(values) {
  const payload = {};
  for (const key of Object.keys(PROFILE_FIELDS)) {
    const value = values[key];
    payload[key] = value === "" ? null : value;
  }
  payload.years_of_experience = Math.max(0, Number(values.years_of_experience) || 0);
  return payload;
}

function ProfileFields({ values, onChange, departments }) {
  const field = (name) => ({ value: values[name] ?? "", onChange: (e) => onChange({ ...values, [name]: e.target.value }) });
  return (
    <>
      <label>
        Department
        <select {...field("department_id")} required>
          <option value="">Select department</option>
          {departments.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <div className="row">
        <label>
          Title
          <input {...field("title")} style={{ width: 80 }} />
        </label>
        <label style={{ flex: 1 }}>
          Specialization
          <input {...field("specialization")} required />
        </label>
      </div>
      <div className="row">
        <label>
          License number
          <input {...field("license_number")} />
        </label>
        <label>
          Years of experience
          <input type="number" min="0" max="80" {...field("years_of_experience")} style={{ width: 100 }} />
        </label>
        <label>
          Consultation fee
          <input type="number" min="0" step="0.01" {...field("consultation_fee")} style={{ width: 120 }} />
        </label>
      </div>
      <div className="row">
        <label>
          Phone (internal)
          <input {...field("phone")} />
        </label>
        <label>
          Room
          <input {...field("room_number")} style={{ width: 100 }} />
        </label>
      </div>
      <label>
        Qualifications (shown on the public profile)
        <input {...field("qualifications")} placeholder="e.g. MBBS, FCPS (Cardiology)" maxLength={500} />
      </label>
      <label>
        Bio
        <textarea {...field("bio")} />
      </label>
    </>
  );
}

export default function AdminDoctors() {
  const { can } = useAuth();
  const [departments, setDepartments] = useState([]);
  const [doctorUsers, setDoctorUsers] = useState([]);
  const [filters, setFilters] = useState({ q: "", department_id: "", is_active: "" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [form, setForm] = useState(EMPTY_FORM);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(() => {
    listDoctors(cleanParams({ ...filters, page, page_size: PAGE_SIZE }))
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, "Failed to load doctors")));
  }, [filters, page]);

  useEffect(load, [load]);
  useEffect(() => {
    getPublicDepartments()
      .then((res) => setDepartments(res.data.items))
      .catch(() => {});
    if (can("user:read")) {
      listUsers({ role: "doctor", is_active: true, page_size: 100 })
        .then((res) => setDoctorUsers(res.data.items))
        .catch(() => {});
    }
  }, [can]);

  const run = async (action, success) => {
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(success);
      load();
      return true;
    } catch (err) {
      setError(getErrorMessage(err));
      return false;
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    const body = profilePayload(form);
    if (form.mode === "account") body.account = { name: form.name, email: form.email, password: form.password };
    else body.user_id = form.user_id;
    if (await run(() => createDoctor(body), "Doctor created")) setForm(EMPTY_FORM);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    if (await run(() => updateDoctor(editing.id, profilePayload(editing)), "Doctor updated")) setEditing(null);
  };

  const setFilter = (field) => (e) => {
    setPage(1);
    setFilters({ ...filters, [field]: e.target.value });
  };

  return (
    <div>
      <h2>Manage doctors</h2>
      <Alert>{error}</Alert>
      <Alert kind="success">{notice}</Alert>

      {editing ? (
        <form className="card stack" onSubmit={handleSave}>
          <h3>Edit {doctorName(editing)}</h3>
          <ProfileFields values={editing} onChange={setEditing} departments={departments} />
          <div className="row">
            <button type="submit">Save</button>
            <button type="button" className="secondary" onClick={() => setEditing(null)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <details className="card">
          <summary>Add a doctor</summary>
          <form className="stack" onSubmit={handleCreate} style={{ marginTop: "0.75rem" }}>
            <div className="row">
              <label className="row" style={{ flexDirection: "row" }}>
                <input type="radio" checked={form.mode === "account"} onChange={() => setForm({ ...form, mode: "account" })} />
                Create a new login
              </label>
              {can("user:read") && (
                <label className="row" style={{ flexDirection: "row" }}>
                  <input type="radio" checked={form.mode === "existing"} onChange={() => setForm({ ...form, mode: "existing" })} />
                  Use an existing doctor account
                </label>
              )}
            </div>
            {form.mode === "account" ? (
              <>
                <label>
                  Full name
                  <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
                </label>
                <label>
                  Email
                  <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
                </label>
                <label>
                  Initial password (min 8)
                  <input
                    type="password"
                    minLength={8}
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    required
                  />
                </label>
              </>
            ) : (
              <label>
                Account (users with the doctor role)
                <select value={form.user_id} onChange={(e) => setForm({ ...form, user_id: e.target.value })} required>
                  <option value="">Select a user</option>
                  {doctorUsers.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name} — {u.email}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <ProfileFields values={form} onChange={setForm} departments={departments} />
            <button type="submit">Create doctor</button>
          </form>
        </details>
      )}

      <div className="filters">
        <label>
          Name
          <input value={filters.q} onChange={setFilter("q")} />
        </label>
        <label>
          Department
          <select value={filters.department_id} onChange={setFilter("department_id")}>
            <option value="">All</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select value={filters.is_active} onChange={setFilter("is_active")}>
            <option value="">Any</option>
            <option value="true">Active</option>
            <option value="false">Inactive</option>
          </select>
        </label>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Doctor</th>
              <th>Department</th>
              <th>License</th>
              <th>Room</th>
              <th>Fee</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.items.map((d) => (
              <tr key={d.id}>
                <td>
                  {doctorName(d)}
                  <div className="muted small">
                    {d.specialization} · {d.email}
                  </div>
                </td>
                <td>{d.department_name}</td>
                <td>{d.license_number ?? "—"}</td>
                <td>{d.room_number ?? "—"}</td>
                <td>{formatFee(d.consultation_fee)}</td>
                <td>
                  <span className={`badge ${d.is_active ? "ok" : "danger"}`}>{d.is_active ? "active" : "inactive"}</span>
                </td>
                <td className="row">
                  {can("doctor:update") && (
                    <button className="secondary" onClick={() => setEditing({ ...d, consultation_fee: d.consultation_fee ?? "" })}>
                      Edit
                    </button>
                  )}
                  {can("doctor:deactivate") &&
                    (d.is_active ? (
                      <button className="danger" onClick={() => run(() => deactivateDoctor(d.id), "Doctor deactivated")}>
                        Deactivate
                      </button>
                    ) : (
                      <button className="secondary" onClick={() => run(() => activateDoctor(d.id), "Doctor activated")}>
                        Activate
                      </button>
                    ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
    </div>
  );
}
