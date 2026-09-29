import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Alert from "../components/Alert";
import Pager from "../components/Pager";
import { getErrorMessage } from "../services/api";
import { getPublicDepartments } from "../services/departmentService";
import { getPublicDoctors } from "../services/doctorService";
import { cleanParams, doctorName, formatFee } from "../utils/format";

const PAGE_SIZE = 12;
const EMPTY_FILTERS = { q: "", department_id: "", specialization: "", min_experience: "", fee_min: "", fee_max: "" };

// Public directory. Every filter is applied by the API in SQL.
export default function Doctors() {
  const [departments, setDepartments] = useState([]);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [error, setError] = useState("");

  useEffect(() => {
    getPublicDepartments()
      .then((res) => setDepartments(res.data.items))
      .catch(() => {});
  }, []);

  useEffect(() => {
    getPublicDoctors(cleanParams({ ...filters, page, page_size: PAGE_SIZE }))
      .then((res) => {
        setData(res.data);
        setError("");
      })
      .catch((err) => setError(getErrorMessage(err, "Failed to load doctors")));
  }, [filters, page]);

  const set = (field) => (e) => {
    setPage(1);
    setFilters({ ...filters, [field]: e.target.value });
  };

  return (
    <div>
      <h2>Our doctors</h2>
      <div className="filters">
        <label>
          Name
          <input value={filters.q} onChange={set("q")} placeholder="Search by name" />
        </label>
        <label>
          Department
          <select value={filters.department_id} onChange={set("department_id")}>
            <option value="">All</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Specialization
          <input value={filters.specialization} onChange={set("specialization")} />
        </label>
        <label>
          Min. years
          <input type="number" min="0" value={filters.min_experience} onChange={set("min_experience")} style={{ width: 90 }} />
        </label>
        <label>
          Fee from
          <input type="number" min="0" step="0.01" value={filters.fee_min} onChange={set("fee_min")} style={{ width: 100 }} />
        </label>
        <label>
          to
          <input type="number" min="0" step="0.01" value={filters.fee_max} onChange={set("fee_max")} style={{ width: 100 }} />
        </label>
        <button className="secondary" onClick={() => setFilters(EMPTY_FILTERS)}>
          Clear
        </button>
      </div>

      <Alert>{error}</Alert>
      {data.items.length === 0 && !error && <p className="muted">No doctors match these filters.</p>}

      <div className="grid">
        {data.items.map((doc) => (
          <div key={doc.id} className="card">
            <h3>
              <Link to={`/doctors/${doc.id}`}>{doctorName(doc)}</Link>
            </h3>
            <p className="muted small">
              {doc.specialization} · {doc.department_name}
            </p>
            <p className="small">{doc.years_of_experience} years experience</p>
            <p className="small">Fee: {formatFee(doc.consultation_fee)}</p>
          </div>
        ))}
      </div>
      <Pager page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
    </div>
  );
}
