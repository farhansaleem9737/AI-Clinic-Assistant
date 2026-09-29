import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Alert from "../components/Alert";
import Pager from "../components/Pager";
import PatientFields from "../components/PatientFields";
import { EMPTY_PATIENT, patientPayload } from "../utils/patient";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { listPatients, registerPatient } from "../services/patientService";
import { cleanParams } from "../utils/format";

const PAGE_SIZE = 20;

// Front-desk patient search and walk-in registration.
export default function Patients() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [filters, setFilters] = useState({ q: "", date_of_birth: "", is_active: "" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [form, setForm] = useState(EMPTY_PATIENT);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    listPatients(cleanParams({ ...filters, page, page_size: PAGE_SIZE }))
      .then((res) => setData(res.data))
      .catch((err) => setError(getErrorMessage(err, "Failed to load patients")));
  }, [filters, page]);

  useEffect(load, [load]);

  const handleRegister = async (e) => {
    e.preventDefault();
    setError("");
    try {
      const res = await registerPatient(patientPayload(form));
      navigate(`/patients/${res.data.id}`);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const setFilter = (field) => (e) => {
    setPage(1);
    setFilters({ ...filters, [field]: e.target.value });
  };

  return (
    <div>
      <h2>Patients</h2>
      <Alert>{error}</Alert>

      {can("patient:create") && (
        <details className="card">
          <summary>Register a walk-in patient</summary>
          <form className="stack" onSubmit={handleRegister} style={{ marginTop: "0.75rem" }}>
            <PatientFields values={form} onChange={setForm} />
            <button type="submit">Register patient</button>
          </form>
        </details>
      )}

      <div className="filters">
        <label>
          Search
          <input placeholder="Name, MRN, phone or email" value={filters.q} onChange={setFilter("q")} />
        </label>
        <label>
          Date of birth
          <input type="date" value={filters.date_of_birth} onChange={setFilter("date_of_birth")} />
        </label>
        <label>
          Status
          <select value={filters.is_active} onChange={setFilter("is_active")}>
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
              <th>MRN</th>
              <th>Name</th>
              <th>Date of birth</th>
              <th>Phone</th>
              <th>Portal login</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((p) => (
              <tr key={p.id}>
                <td>
                  <Link to={`/patients/${p.id}`}>{p.mrn}</Link>
                </td>
                <td>
                  {p.first_name} {p.last_name}
                </td>
                <td>{p.date_of_birth}</td>
                <td>{p.phone ?? "—"}</td>
                <td>{p.has_account ? "yes" : "no"}</td>
                <td>
                  <span className={`badge ${p.is_active ? "ok" : "danger"}`}>{p.is_active ? "active" : "deactivated"}</span>
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
