import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Alert from "../components/Alert";
import Pager from "../components/Pager";
import StatusBadge from "../components/StatusBadge";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { listAppointments } from "../services/appointmentService";
import { getPublicDepartments } from "../services/departmentService";
import { listDoctors } from "../services/doctorService";
import { ACTIVE_STATUSES, STATUS_LABELS } from "../utils/appointments";
import { formatDateTime } from "../utils/datetime";
import { cleanParams, doctorName } from "../utils/format";

const PAGE_SIZE = 20;

// One list for every role. The API returns only what the caller may see
// (own / as the doctor / all); the extra filters below are for staff.
export default function Appointments() {
  const { can } = useAuth();
  const isStaff = can("appointment:read_any");
  const [searchParams] = useSearchParams();
  const [filters, setFilters] = useState({
    status: "active",
    date_from: "",
    date_to: "",
    doctor_id: "",
    department_id: "",
    patient_id: searchParams.get("patient") ?? "",
  });
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [doctors, setDoctors] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isStaff) return;
    getPublicDepartments()
      .then((res) => setDepartments(res.data.items))
      .catch(() => {});
    listDoctors({ page_size: 100 })
      .then((res) => setDoctors(res.data.items))
      .catch(() => {});
  }, [isStaff]);

  const load = useCallback(() => {
    const { status, ...rest } = filters;
    const params = cleanParams({ ...rest, page, page_size: PAGE_SIZE });
    if (status === "active") params.status = ACTIVE_STATUSES;
    else if (status === "past") params.newest_first = true;
    else if (status) params.status = [status];
    listAppointments(params)
      .then((res) => {
        setData(res.data);
        setError("");
      })
      .catch((err) => setError(getErrorMessage(err, "Failed to load appointments")));
  }, [filters, page]);

  useEffect(load, [load]);

  const set = (field) => (e) => {
    setPage(1);
    setFilters({ ...filters, [field]: e.target.value });
  };

  return (
    <div>
      <div className="spread">
        <h2>{isStaff ? "Appointments" : "My appointments"}</h2>
        {(can("appointment:create") || can("appointment:create_own")) && (
          <Link to="/appointments/book">
            <button>Book appointment</button>
          </Link>
        )}
      </div>

      <div className="filters">
        <label>
          Status
          <select value={filters.status} onChange={set("status")}>
            <option value="active">Upcoming / active</option>
            <option value="past">All (newest first)</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          From
          <input type="date" value={filters.date_from} onChange={set("date_from")} />
        </label>
        <label>
          To
          <input type="date" value={filters.date_to} onChange={set("date_to")} />
        </label>
        {isStaff && (
          <>
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
              Doctor
              <select value={filters.doctor_id} onChange={set("doctor_id")}>
                <option value="">All</option>
                {doctors.map((d) => (
                  <option key={d.id} value={d.id}>
                    {doctorName(d)}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
        {filters.patient_id && (
          <button className="secondary" onClick={() => setFilters({ ...filters, patient_id: "" })}>
            Clear patient filter
          </button>
        )}
      </div>

      <Alert>{error}</Alert>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Patient</th>
              <th>Doctor</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.items.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No appointments.
                </td>
              </tr>
            )}
            {data.items.map((a) => (
              <tr key={a.id}>
                <td>{formatDateTime(a.starts_at, a.timezone)}</td>
                <td>
                  {a.patient.name}
                  <div className="muted small">{a.patient.mrn}</div>
                </td>
                <td>
                  {doctorName(a.doctor)}
                  <div className="muted small">{a.doctor.department_name}</div>
                </td>
                <td>
                  <StatusBadge status={a.status} />
                </td>
                <td>
                  <Link to={`/appointments/${a.id}`}>Open</Link>
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
