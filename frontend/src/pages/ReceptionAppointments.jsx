import { ArrowDown, ArrowUp, ArrowUpDown, CalendarDays, Plus, RotateCcw, Search, SearchX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import ActionMenu from "../components/ActionMenu";
import Alert from "../components/Alert";
import Avatar from "../components/Avatar";
import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import NumberedPager from "../components/NumberedPager";
import DateRangeFilter from "../components/patients/DateRangeFilter";
import StatusBadge from "../components/StatusBadge";
import { useAuth } from "../context/useAuth";
import { useFetch } from "../hooks/useFetch";
import { getErrorMessage } from "../services/api";
import { changeAppointmentStatus, countAppointments, listAppointments } from "../services/appointmentService";
import { getPublicDepartments, listDepartments } from "../services/departmentService";
import { listDoctors } from "../services/doctorService";
import { CANCELLATION_REASONS, CONFIRM_ACTIONS, MENU_ACTIONS, STATUS_LABELS } from "../utils/appointments";
import { formatSlotTime } from "../utils/datetime";
import { readDay } from "../utils/doctorAppointments";
import { isAdmin } from "../routes/navigation";
import { doctorName } from "../utils/format";
import { ageFromDateOfBirth, SEX_LABELS } from "../utils/patient";

const PAGE_SIZE = 10;
const SEARCH_DELAY_MS = 350;
const TABS = [
  { key: "all", label: "All" },
  { key: "today", label: "Today" },
  { key: "upcoming", label: "Upcoming" },
  { key: "past", label: "Past" },
];
const SORTABLE = [
  { key: "time", label: "Date & Time" },
  { key: "patient", label: "Patient" },
  { key: "doctor", label: "Doctor" },
  { key: "department", label: "Department" },
  { key: "status", label: "Status" },
];
const EMPTY = {
  all: "No appointments yet.",
  today: "No appointments today.",
  upcoming: "No upcoming appointments.",
  past: "No past appointments.",
};
const longDate = (iso, timeZone) =>
  new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone }).format(new Date(iso));
const shortDate = (iso, timeZone) =>
  new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone }).format(new Date(iso));

function SortHeader({ column, sort, onSort }) {
  const [active, direction] = sort ? sort.split("_") : [];
  const on = active === column.key;
  const Icon = on ? (direction === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  return (
    <th scope="col" aria-sort={on ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        className="sort-button"
        onClick={() => onSort(`${column.key}_${on && direction === "asc" ? "desc" : "asc"}`)}
      >
        {column.label} <Icon size={14} aria-hidden="true" />
      </button>
    </th>
  );
}

/**
 * Staff appointments (D84): All / Today / Upcoming / Past with real counts,
 * search over patient, doctor and reason, date / doctor / department /
 * status filters, server-side sorting and paging, and per row the actions
 * the state machine allows. The URL keeps everything except the search text.
 */
export default function ReceptionAppointments() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.key === params.get("tab")) ? params.get("tab") : "all";
  // A range (D92). `?date=` from the dashboards still means that one day.
  const date = readDay(params.get("date"));
  const from = readDay(params.get("from")) || date || "";
  const to = readDay(params.get("to")) || date || "";
  const doctorId = params.get("doctor") ?? "";
  const departmentId = params.get("department") ?? "";
  const status = STATUS_LABELS[params.get("status")] ? params.get("status") : "";
  const sort = params.get("sort") ?? "";
  const patientId = params.get("patient") ?? "";
  const page = Math.max(1, Number(params.get("page")) || 1);

  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const [attempt, setAttempt] = useState(0);
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(null);
  const [reason, setReason] = useState("patient_request");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  const update = (changes, { keepPage = false } = {}) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, String(v));
      else next.delete(k);
    }
    if (!keepPage) next.delete("page");
    setParams(next, { replace: true });
  };

  const doctors = useFetch(() => listDoctors({ page_size: 100, sort: "name_asc" }), []);
  // Administrators also filter by inactive departments (past appointments keep theirs).
  const departments = useFetch(() => (can("department:manage") ? listDepartments({ page_size: 100 }) : getPublicDepartments()), []);

  // Everything but the tab: what the counts and every tab share.
  const filters = {};
  if (q.trim()) filters.q = q.trim();
  if (doctorId) filters.doctor_id = doctorId;
  if (departmentId) filters.department_id = departmentId;
  if (status) filters.status = [status];
  if (patientId) filters.patient_id = patientId;
  const dated = {};
  if (from) dated.date_from = from;
  if (to) dated.date_to = to;
  const counts = useFetch(
    () => countAppointments({ ...filters, ...dated, include_today: true }),
    [JSON.stringify(filters), from, to, attempt]
  );
  const today = counts.data?.today_date;

  const listParams = { ...filters, page, page_size: PAGE_SIZE };
  if (sort) listParams.sort = sort;
  if (tab === "today") Object.assign(listParams, today ? { date_from: today, date_to: today } : {});
  else Object.assign(listParams, dated);
  if (tab === "upcoming") listParams.scope = "upcoming";
  if (tab === "past") {
    listParams.scope = "past";
    if (!sort) listParams.newest_first = true;
  }
  const waitingForToday = tab === "today" && !today;
  const list = useFetch(() => listAppointments(listParams), [JSON.stringify(listParams), attempt], { enabled: !waitingForToday });

  const onSearch = (value) => {
    setTyped(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setQ(value);
      update({});
    }, SEARCH_DELAY_MS);
  };
  const clearFilters = () => {
    clearTimeout(timer.current);
    setTyped("");
    setQ("");
    update({ date: "", from: "", to: "", doctor: "", department: "", status: "", patient: "", sort: "" });
  };

  const run = async (appointment, target) => {
    setBusy(true);
    setActionError("");
    try {
      await changeAppointmentStatus(appointment.id, {
        status: target,
        ...(target === "cancelled" ? { cancellation_reason: reason } : {}),
      });
      setPending(null);
      setNotice(`${appointment.patient.name}: ${STATUS_LABELS[target].toLowerCase()}.`);
      setAttempt((n) => n + 1);
    } catch (err) {
      const message = getErrorMessage(err, "Could not update the appointment");
      setNotice("");
      setActionError(message);
    } finally {
      setBusy(false);
    }
  };
  const onAction = (appointment, target) => {
    setNotice("");
    setActionError("");
    if (CONFIRM_ACTIONS[target]) {
      setReason("patient_request");
      setPending({ appointment, status: target });
    } else run(appointment, target);
  };

  const countFor = (key) => {
    if (!counts.data) return null;
    return key === "today" ? counts.data.today : counts.data[key];
  };
  const items = list.data?.items ?? [];
  const filtered = Boolean(q.trim() || from || to || doctorId || departmentId || status || patientId);
  const admin = isAdmin(can);

  const actionsFor = (a) => {
    const label = `${a.patient.name}, ${shortDate(a.starts_at, a.timezone)} ${formatSlotTime(a.starts_at, a.timezone)}`;
    return {
      label,
      items: [
        { label: "View Appointment", to: `/appointments/${a.id}` },
        (can("patient:read_any") || can("patient:read_assigned")) && { label: "View Patient", to: `/patients/${a.patient.id}` },
        { label: "View Doctor", to: `/doctors/${a.doctor.id}` },
        ...a.allowed_transitions
          .filter((s) => MENU_ACTIONS[s])
          .map((s) => ({ label: MENU_ACTIONS[s], onSelect: () => onAction(a, s), danger: s === "cancelled" || s === "no_show" })),
        a.can_reschedule && { label: "Reschedule Appointment", to: `/appointments/${a.id}?reschedule=1` },
      ].filter(Boolean),
    };
  };

  return (
    <div className="reception-appointments">
      <header className="patients-head">
        <div className="schedule-head">
          <h1>Appointments</h1>
          <p className="muted">View and manage clinic appointments.</p>
        </div>
        {can("appointment:create") && (
          <Link to={`/appointments/book${patientId ? `?patient=${patientId}` : ""}`} className="button add-patient">
            <Plus size={20} aria-hidden="true" /> {admin ? "Add Appointment" : "Book Appointment"}
          </Link>
        )}
      </header>

      <div className="card ra-toolbar ra-filter-card">
        <div className="appt-search ra-search">
          <Search size={20} aria-hidden="true" />
          <input
            type="search"
            aria-label="Search by patient name, doctor name or MRN"
            placeholder="Search by patient name, doctor name or MRN..."
            value={typed}
            maxLength={100}
            onChange={(e) => onSearch(e.target.value)}
          />
        </div>
        <DateRangeFilter
          label="Appointment dates"
          from={from}
          to={to}
          onChange={(range) => update({ date: "", from: range.from, to: range.to, tab: tab === "today" ? "all" : tab })}
        />
        <label className="patients-filter">
          <span className="sr-only">Doctor</span>
          <select value={doctorId} onChange={(e) => update({ doctor: e.target.value })}>
            <option value="">All Doctors</option>
            {(doctors.data?.items ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {doctorName(d)}
                {d.is_active === false ? " (inactive)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="patients-filter">
          <span className="sr-only">Department</span>
          <select value={departmentId} onChange={(e) => update({ department: e.target.value })}>
            <option value="">All Departments</option>
            {(departments.data?.items ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
                {d.is_active === false ? " (inactive)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="patients-filter">
          <span className="sr-only">Status</span>
          <select value={status} onChange={(e) => update({ status: e.target.value })}>
            <option value="">All Statuses</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="secondary ra-clear" onClick={clearFilters} disabled={!filtered && !sort}>
          <RotateCcw size={16} aria-hidden="true" /> Clear Filters
        </button>
      </div>
      {patientId && (
        <p className="ra-chip">
          Showing one patient&apos;s appointments.{" "}
          <button type="button" className="link-button" onClick={() => update({ patient: "" })}>
            Show all patients
          </button>
        </p>
      )}

      <div className="appt-tabs ra-tabs" role="tablist" aria-label="Appointment views">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            aria-controls="ra-panel"
            className={tab === t.key ? "active" : ""}
            onClick={() => update({ tab: t.key === "all" ? "" : t.key })}
          >
            {t.label}
            {countFor(t.key) != null && ` (${countFor(t.key)})`}
          </button>
        ))}
      </div>
      {tab === "today" && (from || to) && <p className="muted small">Today shows today&apos;s appointments; the date filter applies to the other tabs.</p>}

      <div aria-live="polite">
        <Alert kind="success">{notice}</Alert>
        {!pending && <Alert>{actionError}</Alert>}
      </div>

      <section className="card patients-card" id="ra-panel" role="tabpanel" aria-label="Appointments" aria-busy={list.loading}>
        {list.error || counts.error ? (
          <div role="alert" className="appt-error">
            <p>{list.error || counts.error}</p>
            <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </button>
          </div>
        ) : !list.data ? (
          <div role="status" aria-label="Loading appointments">
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
              No appointments match your search or filters.
            </EmptyState>
          ) : (
            <EmptyState icon={CalendarDays}>{EMPTY[tab]}</EmptyState>
          )
        ) : (
          <>
            <div className="appt-table-wrap">
              <table className="patients-table ra-table">
                <thead>
                  <tr>
                    {SORTABLE.map((column) => (
                      <SortHeader key={column.key} column={column} sort={sort} onSort={(value) => update({ sort: value })} />
                    ))}
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((a) => {
                    const age = ageFromDateOfBirth(a.patient.date_of_birth);
                    const sex = a.patient.sex_at_birth && a.patient.sex_at_birth !== "unknown" ? SEX_LABELS[a.patient.sex_at_birth] : null;
                    const menu = actionsFor(a);
                    return (
                      <tr key={a.id}>
                        <td data-label="Date & Time">
                          <time dateTime={a.starts_at} className="appt-when">
                            <strong>{longDate(a.starts_at, a.timezone)}</strong>
                            <span className="muted small">{formatSlotTime(a.starts_at, a.timezone)}</span>
                          </time>
                        </td>
                        <td data-label="Patient">
                          <div className="appt-patient">
                            <Avatar name={a.patient.name} role="patient" src={a.patient.photo_url} size={42} />
                            <div>
                              <strong>{a.patient.name}</strong>
                              <span className="muted small">
                                {[a.patient.mrn, age != null && `${age} years`, sex].filter(Boolean).join(" · ")}
                              </span>
                            </div>
                          </div>
                        </td>
                        <td data-label="Doctor">
                          <div className="appt-patient">
                            <Avatar name={a.doctor.name} role="doctor" src={a.doctor.photo_url} size={42} />
                            <div>
                              <strong>{doctorName(a.doctor)}</strong>
                              <span className="muted small">{a.doctor.specialization}</span>
                            </div>
                          </div>
                        </td>
                        <td data-label="Department">{a.doctor.department_name || <span className="muted">Not recorded</span>}</td>
                        <td data-label="Status">
                          <StatusBadge status={a.status} icon />
                        </td>
                        <td className="row-menu">
                          <ActionMenu label={`Actions for ${menu.label}`} items={menu.items} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <NumberedPager page={page} pageSize={PAGE_SIZE} total={list.data.total} noun="appointments" onChange={(p) => update({ page: p }, { keepPage: true })} />
          </>
        )}
      </section>

      {pending && (
        <ConfirmDialog
          title={CONFIRM_ACTIONS[pending.status].title}
          confirmLabel={CONFIRM_ACTIONS[pending.status].label}
          cancelLabel="Keep appointment"
          danger={CONFIRM_ACTIONS[pending.status].danger}
          busy={busy}
          error={actionError}
          onConfirm={() => run(pending.appointment, pending.status)}
          onCancel={() => setPending(null)}
        >
          <p>
            {pending.appointment.patient.name} with {doctorName(pending.appointment.doctor)},{" "}
            {shortDate(pending.appointment.starts_at, pending.appointment.timezone)}{" "}
            {formatSlotTime(pending.appointment.starts_at, pending.appointment.timezone)}.
          </p>
          {pending.status === "cancelled" && (
            <label className="edit-field">
              Reason
              <select value={reason} onChange={(e) => setReason(e.target.value)}>
                {Object.entries(CANCELLATION_REASONS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}
