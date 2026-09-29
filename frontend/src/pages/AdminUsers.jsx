import { useCallback, useEffect, useState } from "react";
import Alert from "../components/Alert";
import Pager from "../components/Pager";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import {
  activateUser,
  createUser,
  deactivateUser,
  listRoles,
  listUsers,
  setUserRoles,
} from "../services/userService";

const EMPTY_FORM = { name: "", email: "", password: "", roles: [] };
const PAGE_SIZE = 20;

function RoleCheckboxes({ roles, selected, onChange }) {
  const toggle = (code) =>
    onChange(selected.includes(code) ? selected.filter((c) => c !== code) : [...selected, code]);
  return (
    <div className="row">
      {roles.map((r) => (
        <label key={r.code} className="row" style={{ flexDirection: "row" }}>
          <input type="checkbox" checked={selected.includes(r.code)} onChange={() => toggle(r.code)} />
          {r.name}
        </label>
      ))}
    </div>
  );
}

export default function AdminUsers() {
  const { user: me, can } = useAuth();
  const [roles, setRoles] = useState([]);
  const [filters, setFilters] = useState({ q: "", role: "", is_active: "" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [form, setForm] = useState(EMPTY_FORM);
  const [editing, setEditing] = useState(null); // {id, roles}
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(() => {
    const params = { page, page_size: PAGE_SIZE };
    if (filters.q) params.q = filters.q;
    if (filters.role) params.role = filters.role;
    if (filters.is_active !== "") params.is_active = filters.is_active;
    listUsers(params)
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, "Failed to load users")));
  }, [filters, page]);

  useEffect(load, [load]);
  useEffect(() => {
    listRoles()
      .then((res) => setRoles(res.data))
      .catch(() => {});
  }, []);

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
    if (await run(() => createUser(form), `Created ${form.email}`)) setForm(EMPTY_FORM);
  };

  const saveRoles = async () => {
    if (await run(() => setUserRoles(editing.id, editing.roles), "Roles updated")) setEditing(null);
  };

  return (
    <div>
      <h2>Users</h2>
      <Alert>{error}</Alert>
      <Alert kind="success">{notice}</Alert>

      {can("user:create") && (
        <details className="card">
          <summary>Create staff account</summary>
          <form className="stack" onSubmit={handleCreate} style={{ marginTop: "0.75rem" }}>
            <label>
              Full name
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </label>
            <label>
              Email
              <input
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                required
              />
            </label>
            <label>
              Initial password (min 8 characters)
              <input
                type="password"
                minLength={8}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required
              />
            </label>
            <RoleCheckboxes roles={roles} selected={form.roles} onChange={(r) => setForm({ ...form, roles: r })} />
            <button type="submit" disabled={form.roles.length === 0}>
              Create account
            </button>
          </form>
        </details>
      )}

      <div className="filters">
        <label>
          Search
          <input
            placeholder="Name or email"
            value={filters.q}
            onChange={(e) => {
              setPage(1);
              setFilters({ ...filters, q: e.target.value });
            }}
          />
        </label>
        <label>
          Role
          <select
            value={filters.role}
            onChange={(e) => {
              setPage(1);
              setFilters({ ...filters, role: e.target.value });
            }}
          >
            <option value="">Any</option>
            {roles.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            value={filters.is_active}
            onChange={(e) => {
              setPage(1);
              setFilters({ ...filters, is_active: e.target.value });
            }}
          >
            <option value="">Any</option>
            <option value="true">Active</option>
            <option value="false">Deactivated</option>
          </select>
        </label>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Roles</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.items.map((u) => (
              <tr key={u.id}>
                <td>{u.name}</td>
                <td>{u.email}</td>
                <td>
                  {editing?.id === u.id ? (
                    <div className="stack">
                      <RoleCheckboxes
                        roles={roles}
                        selected={editing.roles}
                        onChange={(r) => setEditing({ ...editing, roles: r })}
                      />
                      <div className="row">
                        <button onClick={saveRoles} disabled={editing.roles.length === 0}>
                          Save
                        </button>
                        <button className="secondary" onClick={() => setEditing(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    u.roles.map((r) => (
                      <span key={r} className="badge">
                        {r}
                      </span>
                    ))
                  )}
                </td>
                <td>
                  <span className={`badge ${u.is_active ? "ok" : "danger"}`}>
                    {u.is_active ? "active" : "deactivated"}
                  </span>
                </td>
                <td className="row">
                  {can("user:assign_role") && editing?.id !== u.id && (
                    <button className="secondary" onClick={() => setEditing({ id: u.id, roles: u.roles })}>
                      Roles
                    </button>
                  )}
                  {can("user:deactivate") &&
                    u.id !== me.id &&
                    (u.is_active ? (
                      <button className="danger" onClick={() => run(() => deactivateUser(u.id), "User deactivated")}>
                        Deactivate
                      </button>
                    ) : (
                      <button className="secondary" onClick={() => run(() => activateUser(u.id), "User activated")}>
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
