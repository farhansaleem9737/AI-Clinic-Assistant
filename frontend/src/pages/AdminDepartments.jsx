import { useCallback, useEffect, useState } from "react";
import Alert from "../components/Alert";
import Pager from "../components/Pager";
import { getErrorMessage } from "../services/api";
import {
  activateDepartment,
  createDepartment,
  deactivateDepartment,
  listDepartments,
  updateDepartment,
} from "../services/departmentService";

const EMPTY = { name: "", description: "", timezone: "" };
const PAGE_SIZE = 20;

export default function AdminDepartments() {
  const [data, setData] = useState({ items: [], total: 0 });
  const [page, setPage] = useState(1);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState(null); // department being edited
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(() => {
    listDepartments({ page, page_size: PAGE_SIZE })
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, "Failed to load departments")));
  }, [page]);

  useEffect(load, [load]);

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

  const withoutBlanks = (values) => ({
    name: values.name,
    description: values.description || null,
    ...(values.timezone ? { timezone: values.timezone } : {}),
  });

  const handleCreate = async (e) => {
    e.preventDefault();
    if (await run(() => createDepartment(withoutBlanks(form)), "Department created")) setForm(EMPTY);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    if (await run(() => updateDepartment(editing.id, withoutBlanks(editing)), "Department updated")) setEditing(null);
  };

  return (
    <div>
      <h2>Departments</h2>
      <Alert>{error}</Alert>
      <Alert kind="success">{notice}</Alert>

      <form className="card stack" onSubmit={editing ? handleSave : handleCreate}>
        <h3>{editing ? `Edit ${editing.name}` : "New department"}</h3>
        {(() => {
          const values = editing ?? form;
          const setValues = editing ? setEditing : setForm;
          return (
            <>
              <label>
                Name
                <input value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} required />
              </label>
              <label>
                Description
                <input
                  value={values.description ?? ""}
                  onChange={(e) => setValues({ ...values, description: e.target.value })}
                />
              </label>
              <label>
                Timezone (IANA, blank = clinic default)
                <input
                  placeholder="e.g. Asia/Karachi"
                  value={values.timezone ?? ""}
                  onChange={(e) => setValues({ ...values, timezone: e.target.value })}
                />
              </label>
            </>
          );
        })()}
        <div className="row">
          <button type="submit">{editing ? "Save" : "Create"}</button>
          {editing && (
            <button type="button" className="secondary" onClick={() => setEditing(null)}>
              Cancel
            </button>
          )}
        </div>
      </form>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Description</th>
              <th>Timezone</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.items.map((d) => (
              <tr key={d.id}>
                <td>{d.name}</td>
                <td>{d.description}</td>
                <td className="small">{d.timezone}</td>
                <td>
                  <span className={`badge ${d.is_active ? "ok" : "danger"}`}>{d.is_active ? "active" : "inactive"}</span>
                </td>
                <td className="row">
                  <button className="secondary" onClick={() => setEditing({ ...d })}>
                    Edit
                  </button>
                  {d.is_active ? (
                    <button className="danger" onClick={() => run(() => deactivateDepartment(d.id), "Department deactivated")}>
                      Deactivate
                    </button>
                  ) : (
                    <button className="secondary" onClick={() => run(() => activateDepartment(d.id), "Department activated")}>
                      Activate
                    </button>
                  )}
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
