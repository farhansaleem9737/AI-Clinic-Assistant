import { Ban, Building2, Plus, Search, SearchX, Stethoscope, Users } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ActionMenu from "../components/ActionMenu";
import Alert from "../components/Alert";
import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import ErrorBoundary from "../components/ErrorBoundary";
import NumberedPager from "../components/NumberedPager";
import { DepartmentDetailsDialog, DepartmentFormDialog, ManageDoctorsDialog } from "../components/departments/DepartmentDialogs";
import DepartmentCard from "../components/departments/DepartmentCard";
import { getErrorMessage } from "../services/api";
import { activateDepartment, deactivateDepartment, getDepartment, getDepartmentSummary, listDepartments } from "../services/departmentService";
import { getClinicSettings } from "../services/workspaceService";

const PAGE_SIZE = 12; // three rows of four cards
const SEARCH_DELAY_MS = 350;
const STATS = [
  { key: "total", label: "Total Departments", icon: Building2, tone: "blue" },
  { key: "active", label: "Active Departments", icon: Users, tone: "green" },
  { key: "inactive", label: "Inactive Departments", icon: Ban, tone: "red" },
  { key: "doctors", label: "Total Doctors", icon: Stethoscope, tone: "purple" },
];

/**
 * Admin > Departments (D89, cards D93): clinic-wide totals, then a card per
 * department with its practising-doctor count and avatars; search, status
 * filter and paging on the server; add / edit / manage doctors /
 * activate-deactivate. Deactivating keeps doctors and
 * appointments; it stops new bookings (enforced by the API).
 */
export default function AdminDepartments() {
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [summary, setSummary] = useState(null);
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState(null);
  const [loadedKey, setLoadedKey] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dialog, setDialog] = useState(null);
  const [impact, setImpact] = useState(null); // detail of the department being deactivated
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [clinicZone, setClinicZone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  useEffect(() => {
    getClinicSettings()
      .then((res) => res.data?.operational?.timezone && setClinicZone(res.data.operational.timezone))
      .catch(() => {});
  }, []);

  // Clinic-wide: the search and status filter do not change these.
  useEffect(() => {
    let live = true;
    getDepartmentSummary()
      .then((res) => live && setSummary(res.data))
      .catch(() => live && setSummary({ failed: true }));
    return () => {
      live = false;
    };
  }, [attempt]);

  const params = { page, page_size: PAGE_SIZE, sort: "name" };
  if (q.trim()) params.q = q.trim();
  if (status) params.is_active = status === "active";
  const requestKey = `${JSON.stringify(params)}#${attempt}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    const [query] = requestKey.split("#");
    listDepartments(JSON.parse(query))
      .then((res) => {
        if (cancelled) return;
        setData(res.data);
        setError("");
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err, "Could not load departments")))
      .finally(() => !cancelled && setLoadedKey(requestKey));
    return () => {
      cancelled = true;
    };
  }, [requestKey]);

  const refresh = () => setAttempt((n) => n + 1);
  const onSearch = (value) => {
    setTyped(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setQ(value);
      setPage(1);
    }, SEARCH_DELAY_MS);
  };
  const clearFilters = () => {
    clearTimeout(timer.current);
    setTyped("");
    setQ("");
    setStatus("");
    setPage(1);
  };

  const open = (kind, department) => {
    setNotice("");
    setActionError("");
    setImpact(null);
    setDialog({ kind, department });
    if (kind === "status" && department.is_active) {
      getDepartment(department.id)
        .then((res) => setImpact(res.data))
        .catch(() => setImpact({ unknown: true }));
    }
  };
  const done = (text) => {
    setDialog(null);
    setBusy(false);
    setNotice(text);
    refresh();
  };

  const changeStatus = async () => {
    const { department } = dialog;
    setBusy(true);
    setActionError("");
    try {
      await (department.is_active ? deactivateDepartment(department.id) : activateDepartment(department.id));
      done(`${department.name} is now ${department.is_active ? "inactive" : "active"}.`);
    } catch (err) {
      setActionError(getErrorMessage(err, "Could not change the department's status"));
      setBusy(false);
    }
  };

  const actionsFor = (d) => [
    { label: "View Department", onSelect: () => open("view", d) },
    { label: "Edit Department", onSelect: () => open("edit", d) },
    { label: "Manage Doctors", onSelect: () => open("doctors", d) },
    { label: d.is_active ? "Deactivate Department" : "Activate Department", danger: d.is_active, onSelect: () => open("status", d) },
  ];

  const items = data?.items ?? [];
  const filtered = Boolean(q.trim() || status);

  return (
    <div className="patients-page departments-page">
      <header className="patients-head">
        <div className="dept-title">
          <span className="dept-title-icon" aria-hidden="true">
            <Building2 size={30} />
          </span>
          <div className="schedule-head">
            <h1>Departments</h1>
            <p className="muted">Manage clinic departments and their details.</p>
          </div>
        </div>
        <button type="button" className="add-patient" onClick={() => open("add")}>
          <Plus size={20} aria-hidden="true" /> Add Department
        </button>
      </header>

      <div className="card users-toolbar">
        <div className="appt-search patients-search">
          <Search size={20} aria-hidden="true" />
          <input
            type="search"
            aria-label="Search departments"
            placeholder="Search departments..."
            value={typed}
            maxLength={100}
            onChange={(e) => onSearch(e.target.value)}
          />
        </div>
        <label className="patients-filter">
          <span className="sr-only">Status</span>
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
      </div>

      <section className="dept-stats" aria-label="Department totals">
        {STATS.map(({ key, label, icon: Icon, tone }) => (
          <div key={key} className={`dept-stat dept-stat-${tone}`}>
            <span className="dept-stat-icon" aria-hidden="true">
              <Icon size={26} />
            </span>
            <div>
              <p>{label}</p>
              <strong aria-label={`${label}: ${summary && !summary.failed ? summary[key] : "unavailable"}`}>
                {summary === null ? <span className="skeleton dept-stat-skeleton" /> : summary.failed ? "—" : summary[key]}
              </strong>
            </div>
          </div>
        ))}
      </section>

      <div aria-live="polite">
        <Alert kind="success">{notice}</Alert>
      </div>

      <ErrorBoundary
        title="Unable to load departments"
        onRetry={() => {
          setData(null); // render the skeleton, not the data that failed, until the reload arrives
          refresh();
        }}
      >
      <section className="dept-grid-wrap" aria-label="Departments list" aria-busy={loading}>
        {error ? (
          <div role="alert" className="card appt-error">
            <p>{error}</p>
            <button type="button" className="secondary" onClick={refresh}>
              Try again
            </button>
          </div>
        ) : loading && !data ? (
          <div className="dept-grid" role="status" aria-label="Loading departments">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton dept-card-skeleton" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="card">
            {filtered ? (
              <EmptyState
                icon={SearchX}
                action={
                  <button type="button" className="secondary" onClick={clearFilters}>
                    Clear search and filters
                  </button>
                }
              >
                No departments match your search or filters.
              </EmptyState>
            ) : (
              <EmptyState icon={Building2}>No departments yet. Use Add Department to create the first one.</EmptyState>
            )}
          </div>
        ) : (
          <>
            <ul className="dept-grid">
              {items.map((d) => (
                <DepartmentCard
                  key={d.id}
                  department={d}
                  doctorsTo={`/admin/doctors?department=${d.id}`}
                  emptyDescription="No description provided."
                  onOpen={() => open("view", d)}
                  status={
                    <span className={`badge dept-status ${d.is_active ? "ok" : "danger"}`}>
                      <span className="dot" aria-hidden="true" /> {d.is_active ? "Active" : "Inactive"}
                    </span>
                  }
                  menu={<ActionMenu label={`Actions for ${d.name}`} items={actionsFor(d)} />}
                />
              ))}
            </ul>
            {data.total > PAGE_SIZE && (
              <div className="card dept-pager">
                <NumberedPager page={page} pageSize={PAGE_SIZE} total={data.total} noun="departments" onChange={setPage} />
              </div>
            )}
          </>
        )}
      </section>
      </ErrorBoundary>

      {(dialog?.kind === "add" || dialog?.kind === "edit") && (
        <DepartmentFormDialog
          department={dialog.kind === "edit" ? dialog.department : null}
          defaultTimezone={clinicZone}
          onClose={() => setDialog(null)}
          onSaved={(saved) => done(dialog.kind === "edit" ? `Saved ${saved.name}.` : `Added ${saved.name}.`)}
        />
      )}
      {dialog?.kind === "view" && <DepartmentDetailsDialog department={dialog.department} onClose={() => setDialog(null)} />}
      {dialog?.kind === "doctors" && (
        <ManageDoctorsDialog department={dialog.department} onClose={() => setDialog(null)} onChanged={refresh} />
      )}
      {dialog?.kind === "status" && (
        <ConfirmDialog
          title={dialog.department.is_active ? "Deactivate department?" : "Activate department?"}
          confirmLabel={dialog.department.is_active ? "Deactivate" : "Activate"}
          danger={dialog.department.is_active}
          busy={busy || (dialog.department.is_active && !impact)}
          error={actionError}
          onConfirm={changeStatus}
          onCancel={() => setDialog(null)}
        >
          {dialog.department.is_active ? (
            <>
              <p>
                {dialog.department.name} will be hidden from the public directory and its doctors will not take new bookings. Doctors
                stay assigned and nothing is deleted.
              </p>
              {!impact && <p role="status">Checking upcoming appointments…</p>}
              {impact && !impact.unknown && (
                <Alert kind={impact.upcoming_appointments ? "warn" : "success"}>
                  {impact.upcoming_appointments
                    ? `${impact.upcoming_appointments} upcoming appointment${impact.upcoming_appointments === 1 ? "" : "s"} will be kept as booked. Contact those patients if they need to move.`
                    : "There are no upcoming appointments."}{" "}
                  {impact.doctor_count} doctor{impact.doctor_count === 1 ? "" : "s"} assigned.
                </Alert>
              )}
              {impact?.unknown && <Alert kind="warn">Could not check upcoming appointments; any will be kept as booked.</Alert>}
            </>
          ) : (
            <p>{dialog.department.name} will be listed again and its doctors can take bookings.</p>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}
