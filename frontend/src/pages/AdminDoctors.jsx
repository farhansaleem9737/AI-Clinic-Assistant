import { ArrowUpDown, ChevronDown, ChevronUp, CircleAlert, CircleCheck, Plus, Search, SearchX, Stethoscope } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import ActionMenu from "../components/ActionMenu";
import Alert from "../components/Alert";
import Avatar from "../components/Avatar";
import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import NumberedPager from "../components/NumberedPager";
import ApplicationsPanel from "../components/doctors/ApplicationsPanel";
import { DoctorDepartmentDialog, DoctorFormDialog, DoctorProfileDialog } from "../components/doctors/DoctorDialogs";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { getPublicDepartments, listDepartments } from "../services/departmentService";
import { activateDoctor, deactivateDoctor, getDoctor, listAllSpecializations, listDoctors } from "../services/doctorService";
import { COLUMN_LABELS, experienceLabel, sortOf, toggleSort } from "../utils/adminDoctors";
import { doctorName } from "../utils/format";

const PAGE_SIZE = 10;
const SEARCH_DELAY_MS = 350;

function SortHeader({ sort, column, onSort }) {
  const state = sortOf(sort, column);
  const Icon = state === "ascending" ? ChevronUp : state === "descending" ? ChevronDown : ArrowUpDown;
  return (
    <th scope="col" aria-sort={state}>
      <button type="button" className="sort-button" onClick={() => onSort(toggleSort(sort, column))}>
        {COLUMN_LABELS[column]} <Icon size={15} aria-hidden="true" />
      </button>
    </th>
  );
}

/**
 * Admin > Doctors (D90): approved doctor profiles with search (name, email,
 * phone, specialization, department), department / specialization / status
 * filters, server-side sorting and paging, and add / edit / schedule /
 * department / status actions. Self-registered applicants are reviewed in
 * Doctor Applications below; they are not doctors until approved.
 */
export default function AdminDoctors() {
  const { can } = useAuth();
  const navigate = useNavigate();
  // `?department=` arrives from Departments (a department's doctor count).
  const [searchParams] = useSearchParams();
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [departmentId, setDepartmentId] = useState(() => searchParams.get("department") ?? "");
  const [specialization, setSpecialization] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("name_asc");
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState(null);
  const [loadedKey, setLoadedKey] = useState(null);
  const [error, setError] = useState("");
  const [allDepartments, setAllDepartments] = useState([]); // filter: inactive included
  const [activeDepartments, setActiveDepartments] = useState([]); // assignment: active only
  const [specializations, setSpecializations] = useState([]);
  const [notice, setNotice] = useState("");
  const [dialog, setDialog] = useState(null);
  const [upcoming, setUpcoming] = useState(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  useEffect(() => {
    if (can("department:manage"))
      listDepartments({ page_size: 100 })
        .then((res) => setAllDepartments(res.data.items))
        .catch(() => {});
    getPublicDepartments()
      .then((res) => {
        setActiveDepartments(res.data.items);
        if (!can("department:manage")) setAllDepartments(res.data.items);
      })
      .catch(() => {});
  }, [can, attempt]);
  useEffect(() => {
    listAllSpecializations()
      .then((res) => setSpecializations(res.data))
      .catch(() => setSpecializations([]));
  }, [attempt]);

  const params = { page, page_size: PAGE_SIZE, sort };
  if (q.trim()) params.q = q.trim();
  if (departmentId) params.department_id = departmentId;
  if (specialization) params.specialization = specialization;
  if (status) params.is_active = status === "active";
  const requestKey = `${JSON.stringify(params)}#${attempt}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    const [query] = requestKey.split("#");
    listDoctors(JSON.parse(query))
      .then((res) => {
        if (cancelled) return;
        setData(res.data);
        setError("");
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err, "Could not load doctors")))
      .finally(() => !cancelled && setLoadedKey(requestKey));
    return () => {
      cancelled = true;
    };
  }, [requestKey]);

  const refresh = () => setAttempt((n) => n + 1);
  const filter = (apply) => {
    apply();
    setPage(1);
  };
  const onSearch = (value) => {
    setTyped(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => filter(() => setQ(value)), SEARCH_DELAY_MS);
  };
  const clearFilters = () => {
    clearTimeout(timer.current);
    setTyped("");
    filter(() => {
      setQ("");
      setDepartmentId("");
      setSpecialization("");
      setStatus("");
    });
  };

  const open = (kind, doctor) => {
    setNotice("");
    setActionError("");
    setUpcoming(null);
    setDialog({ kind, doctor });
    if (kind === "status" && doctor.is_active)
      getDoctor(doctor.id)
        .then((res) => setUpcoming(res.data.upcoming_appointments ?? 0))
        .catch(() => setUpcoming(-1));
  };
  const done = (text) => {
    setDialog(null);
    setBusy(false);
    setNotice(text);
    refresh();
  };

  const changeStatus = async () => {
    const { doctor } = dialog;
    setBusy(true);
    setActionError("");
    try {
      await (doctor.is_active ? deactivateDoctor(doctor.id) : activateDoctor(doctor.id));
      done(`${doctorName(doctor)} is now ${doctor.is_active ? "inactive" : "active"}.`);
    } catch (err) {
      setActionError(getErrorMessage(err, "Could not change the doctor's status"));
      setBusy(false);
    }
  };

  const actionsFor = (d) =>
    [
      { label: "View Profile", onSelect: () => open("view", d) },
      can("doctor:update") && { label: "Edit Doctor", onSelect: () => open("edit", d) },
      can("schedule:manage_any") && { label: "Manage Schedule", onSelect: () => navigate(`/schedule?doctor=${d.id}`) },
      can("doctor:update") && { label: "Manage Department", onSelect: () => open("department", d) },
      can("doctor:deactivate") && {
        label: d.is_active ? "Deactivate Doctor" : "Activate Doctor",
        danger: d.is_active,
        onSelect: () => open("status", d),
      },
    ].filter(Boolean);

  const items = data?.items ?? [];
  const filtered = Boolean(q.trim() || departmentId || specialization || status);
  const blockedByAppointments = dialog?.kind === "status" && dialog.doctor.is_active && upcoming > 0;

  return (
    <div className="patients-page doctors-admin-page">
      <header className="patients-head">
        <div className="schedule-head">
          <h1>Doctors</h1>
          <p className="muted">Manage clinic doctors, their details and schedules.</p>
        </div>
        {can("doctor:create") && (
          <button type="button" className="add-patient" onClick={() => open("add")}>
            <Plus size={20} aria-hidden="true" /> Add Doctor
          </button>
        )}
      </header>

      <div className="card users-toolbar">
        <div className="appt-search patients-search">
          <Search size={20} aria-hidden="true" />
          <input
            type="search"
            aria-label="Search doctors by name, email or phone"
            placeholder="Search doctors by name, email or phone..."
            value={typed}
            maxLength={100}
            onChange={(e) => onSearch(e.target.value)}
          />
        </div>
        <label className="patients-filter">
          <span className="sr-only">Department</span>
          <select value={departmentId} onChange={(e) => filter(() => setDepartmentId(e.target.value))}>
            <option value="">All Departments</option>
            {allDepartments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
                {d.is_active === false ? " (inactive)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="patients-filter">
          <span className="sr-only">Specialization</span>
          <select value={specialization} onChange={(e) => filter(() => setSpecialization(e.target.value))}>
            <option value="">All Specializations</option>
            {specializations.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="patients-filter">
          <span className="sr-only">Status</span>
          <select value={status} onChange={(e) => filter(() => setStatus(e.target.value))}>
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
        {filtered && (
          <button type="button" className="link-button" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </div>

      <div aria-live="polite">
        <Alert kind="success">{notice}</Alert>
      </div>

      <section className="card patients-card" aria-label="Doctors list" aria-busy={loading}>
        {error ? (
          <div role="alert" className="appt-error">
            <p>{error}</p>
            <button type="button" className="secondary" onClick={refresh}>
              Try again
            </button>
          </div>
        ) : loading && !data ? (
          <div role="status" aria-label="Loading doctors">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton appt-skeleton" />
            ))}
          </div>
        ) : items.length === 0 ? (
          filtered ? (
            <EmptyState
              icon={SearchX}
              action={
                <button type="button" className="secondary" onClick={clearFilters}>
                  Clear search and filters
                </button>
              }
            >
              No doctors match your search or filters.
            </EmptyState>
          ) : (
            <EmptyState icon={Stethoscope}>No doctors yet. Add one, or approve an application below.</EmptyState>
          )
        ) : (
          <>
            <div className="appt-table-wrap">
              <table className="patients-table users-table">
                <thead>
                  <tr>
                    {Object.keys(COLUMN_LABELS).map((column) => (
                      <SortHeader key={column} sort={sort} column={column} onSort={(s) => filter(() => setSort(s))} />
                    ))}
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((d) => (
                    <tr key={d.id}>
                      <td data-label="Doctor">
                        <div className="appt-patient">
                          <Avatar name={d.name} role="doctor" src={d.photo_url} size={44} alt={`Photo of ${doctorName(d)}`} />
                          <div>
                            <button type="button" className="link-button patient-name" onClick={() => open("view", d)}>
                              {doctorName(d)}
                            </button>
                            <span className="muted small">{d.email}</span>
                          </div>
                        </div>
                      </td>
                      <td data-label="Department">{d.department_name}</td>
                      <td data-label="Specialization">{d.specialization}</td>
                      <td data-label="Experience">{experienceLabel(d.years_of_experience)}</td>
                      <td data-label="Status">
                        {d.is_active ? (
                          <span className="badge ok with-icon">
                            <CircleCheck size={14} aria-hidden="true" /> Active
                          </span>
                        ) : (
                          <span className="badge danger with-icon">
                            <CircleAlert size={14} aria-hidden="true" /> Inactive
                          </span>
                        )}
                      </td>
                      <td className="row-menu">
                        <ActionMenu label={`Actions for ${doctorName(d)}`} items={actionsFor(d)} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <NumberedPager page={page} pageSize={PAGE_SIZE} total={data.total} noun="doctors" onChange={setPage} />
          </>
        )}
      </section>

      {can("doctor_application:review") && <ApplicationsPanel onDecided={(text) => done(text)} />}

      {(dialog?.kind === "add" || dialog?.kind === "edit") && (
        <DoctorFormDialog
          doctor={dialog.kind === "edit" ? dialog.doctor : null}
          departments={activeDepartments}
          onClose={() => setDialog(null)}
          onSaved={done}
        />
      )}
      {dialog?.kind === "view" && (
        <DoctorProfileDialog doctor={dialog.doctor} canEditCareer={can("doctor:update")} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === "department" && (
        <DoctorDepartmentDialog doctor={dialog.doctor} departments={activeDepartments} onClose={() => setDialog(null)} onSaved={done} />
      )}
      {dialog?.kind === "status" && (
        <ConfirmDialog
          title={dialog.doctor.is_active ? "Deactivate doctor?" : "Activate doctor?"}
          confirmLabel={dialog.doctor.is_active ? "Deactivate" : "Activate"}
          danger={dialog.doctor.is_active}
          busy={busy || (dialog.doctor.is_active && upcoming === null) || blockedByAppointments}
          error={actionError}
          onConfirm={changeStatus}
          onCancel={() => setDialog(null)}
        >
          {dialog.doctor.is_active ? (
            <>
              <p>
                {doctorName(dialog.doctor)} will be hidden from the directory and cannot be booked. Their records and past appointments
                are kept.
              </p>
              {upcoming === null && <p role="status">Checking upcoming appointments…</p>}
              {blockedByAppointments && (
                <Alert kind="warn">
                  {upcoming} upcoming appointment{upcoming === 1 ? "" : "s"}. Reschedule or cancel {upcoming === 1 ? "it" : "them"} in
                  Appointments first; nothing is cancelled automatically.
                </Alert>
              )}
            </>
          ) : (
            <p>{doctorName(dialog.doctor)} will be listed again and can be booked when their schedule has free slots.</p>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}
