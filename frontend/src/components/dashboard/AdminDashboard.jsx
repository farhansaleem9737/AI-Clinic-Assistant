import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Building2,
  CalendarDays,
  Info,
  ChevronRight,
  Minus,
  Sparkles,
  Stethoscope,
  UserRound,
  Users,
  Zap,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useFetch } from "../../hooks/useFetch";
import { getErrorMessage } from "../../services/api";
import { changeAppointmentStatus, listAppointments } from "../../services/appointmentService";
import { getAdminDashboard } from "../../services/dashboardService";
import { roleLabel } from "../../routes/navigation";
import { CANCELLATION_REASONS } from "../../utils/appointments";
import { formatSlotTime } from "../../utils/datetime";
import { doctorName } from "../../utils/format";
import ActionMenu from "../ActionMenu";
import Alert from "../Alert";
import Avatar from "../Avatar";
import ConfirmDialog from "../ConfirmDialog";
import DateSelect from "../DateSelect";
import EmptyState from "../EmptyState";
import StatusBadge from "../StatusBadge";
import PreviewNote from "./PreviewNote";

const KPIS = {
  users: { label: "Total Users", icon: Users, tone: "blue" },
  doctors: { label: "Doctors", icon: Stethoscope, tone: "purple" },
  patients: { label: "Patients", icon: UserRound, tone: "green" },
  appointments: { label: "Appointments", icon: CalendarDays, tone: "amber" },
  departments: { label: "Departments", icon: Building2, tone: "red" },
};
const ACTIONS = [
  { to: "/admin/users", title: "Manage Users", text: "View and manage all system users including doctors, receptionists and patients.", icon: Users, tone: "blue" },
  { to: "/admin/doctors", title: "Manage Doctors", text: "Add, edit and manage doctor profiles, schedules and availability.", icon: Stethoscope, tone: "purple" },
  { to: "/admin/departments", title: "Manage Departments", text: "Create and manage clinic departments and specializations.", icon: Building2, tone: "green" },
  { to: "/appointments", title: "View Appointments", text: "Monitor and manage all appointments.", icon: CalendarDays, tone: "amber" },
];
const monthName = (isoDate) => new Intl.DateTimeFormat("en-US", { month: "long", timeZone: "UTC" }).format(new Date(`${isoDate}T00:00:00Z`));
const stamp = (iso) => new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
const calendarDate = (iso, timeZone) => new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone }).format(new Date(iso));

function Trend({ kpi, comparedTo }) {
  const since = `vs end of ${monthName(comparedTo)}`;
  if (kpi.trend === "new") {
    return (
      <span className="kpi-trend new">
        <Sparkles size={14} aria-hidden="true" /> New <small>{since}</small>
      </span>
    );
  }
  const Icon = kpi.trend === "up" ? ArrowUp : kpi.trend === "down" ? ArrowDown : Minus;
  const words = kpi.trend === "up" ? "up" : kpi.trend === "down" ? "down" : "no change";
  return (
    <span className={`kpi-trend ${kpi.trend}`}>
      <Icon size={14} aria-hidden="true" />
      <span className="sr-only">{words} </span>
      {Math.abs(kpi.change_percent)}% <small>{since}</small>
    </span>
  );
}

function KpiCard({ kpi, comparedTo }) {
  const { label, icon: Icon, tone } = KPIS[kpi.key];
  return (
    <div className="card stat-card kpi-card">
      <div className={`tile ${tone}`}>
        <Icon size={28} aria-hidden="true" />
      </div>
      <div className="body">
        <div className="label">{label}</div>
        <div className="value">{kpi.total}</div>
        <Trend kpi={kpi} comparedTo={comparedTo} />
      </div>
    </div>
  );
}

function RecentAppointments({ day, onChanged }) {
  const [attempt, setAttempt] = useState(0);
  const [cancelling, setCancelling] = useState(null);
  const [reason, setReason] = useState("clinic_decision");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const list = useFetch(() => listAppointments({ date_from: day, date_to: day, page_size: 5 }), [day, attempt]);
  const items = list.data?.items ?? [];

  const cancel = async () => {
    setBusy(true);
    setError("");
    try {
      await changeAppointmentStatus(cancelling.id, { status: "cancelled", cancellation_reason: reason });
      setCancelling(null);
      setAttempt((n) => n + 1);
      onChanged();
    } catch (err) {
      setError(getErrorMessage(err, "Could not cancel the appointment"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card admin-card" aria-labelledby="admin-appts-title">
      <div className="pd-card-head">
        <CalendarDays className="pd-icon" size={28} aria-hidden="true" />
        <h2 id="admin-appts-title">Recent Appointments</h2>
        <Link to={`/appointments?date=${day}`} className="button secondary view-all">
          View All <ChevronRight size={16} aria-hidden="true" />
        </Link>
      </div>
      {list.error ? (
        <div className="section-error">
          <Alert>{list.error}</Alert>
          <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </div>
      ) : !list.data ? (
        <div role="status" aria-label="Loading appointments">
          <div className="skeleton appt-skeleton" />
          <div className="skeleton appt-skeleton" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState icon={CalendarDays}>No appointments on {calendarDate(`${day}T12:00:00Z`)}.</EmptyState>
      ) : (
        <div className="appt-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th scope="col">Date &amp; Time</th>
                <th scope="col">Patient</th>
                <th scope="col">Doctor</th>
                <th scope="col">Department</th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => {
                const when = `${calendarDate(a.starts_at, a.timezone)} ${formatSlotTime(a.starts_at, a.timezone)}`;
                const menu = [
                  { label: "View Appointment", to: `/appointments/${a.id}` },
                  { label: "View Patient", to: `/patients/${a.patient.id}` },
                  { label: "View Doctor", to: `/doctors/${a.doctor.id}` },
                  a.can_reschedule && { label: "Reschedule Appointment", to: `/appointments/${a.id}?reschedule=1` },
                  a.allowed_transitions.includes("cancelled") && {
                    label: "Cancel Appointment",
                    danger: true,
                    onSelect: () => {
                      setError("");
                      setCancelling(a);
                    },
                  },
                ].filter(Boolean);
                return (
                  <tr key={a.id}>
                    <td data-label="Date & Time">
                      <strong>{calendarDate(a.starts_at, a.timezone)}</strong>
                      <span className="muted small">{formatSlotTime(a.starts_at, a.timezone)}</span>
                    </td>
                    <td data-label="Patient">
                      <div className="appt-patient">
                        <Avatar name={a.patient.name} role="patient" src={a.patient.photo_url} size={38} />
                        <div>
                          <strong>{a.patient.name}</strong>
                          <span className="muted small">{a.patient.mrn}</span>
                        </div>
                      </div>
                    </td>
                    <td data-label="Doctor">{doctorName(a.doctor)}</td>
                    <td data-label="Department">{a.doctor.department_name}</td>
                    <td data-label="Status">
                      <StatusBadge status={a.status} icon />
                    </td>
                    <td className="row-menu">
                      <ActionMenu label={`Actions for ${a.patient.name}, ${when}`} items={menu} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <PreviewNote shown={items.length} total={list.data.total} noun={`appointments on ${calendarDate(`${day}T12:00:00Z`)}`} to={`/appointments?date=${day}`} />
        </div>
      )}
      {cancelling && (
        <ConfirmDialog
          title="Cancel appointment?"
          confirmLabel="Cancel appointment"
          cancelLabel="Keep appointment"
          danger
          busy={busy}
          error={error}
          onConfirm={cancel}
          onCancel={() => setCancelling(null)}
        >
          <p>
            {cancelling.patient.name} with {doctorName(cancelling.doctor)}, {calendarDate(cancelling.starts_at, cancelling.timezone)}{" "}
            {formatSlotTime(cancelling.starts_at, cancelling.timezone)}.
          </p>
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
        </ConfirmDialog>
      )}
    </section>
  );
}

function RecentUsers({ users, timezone }) {
  return (
    <section className="card admin-card" aria-labelledby="admin-users-title">
      <div className="pd-card-head">
        <Users className="pd-icon" size={28} aria-hidden="true" />
        <h2 id="admin-users-title">Recent Users</h2>
        <Link to="/admin/users" className="button secondary view-all">
          View All <ChevronRight size={16} aria-hidden="true" />
        </Link>
      </div>
      {users.length === 0 ? (
        <EmptyState icon={Users}>No user accounts yet.</EmptyState>
      ) : (
        <div className="appt-table-wrap">
          <table className="admin-table admin-users-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Role</th>
                <th scope="col">Email</th>
                <th scope="col">Status</th>
                <th scope="col">Joined On</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td data-label="Name">
                    <div className="appt-patient">
                      <Avatar name={u.name} role={u.roles.includes("doctor") ? "doctor" : "patient"} size={38} />
                      <strong className="truncate" title={u.name}>
                        {u.name}
                      </strong>
                    </div>
                  </td>
                  <td data-label="Role">{roleLabel(u.roles)}</td>
                  <td data-label="Email">
                    <span className="truncate" title={u.email}>
                      {u.email}
                    </span>
                  </td>
                  <td data-label="Status">
                    <span className={`badge ${u.is_active ? "ok" : "danger"}`}>{u.is_active ? "Active" : "Inactive"}</span>
                  </td>
                  <td data-label="Joined On">{calendarDate(u.created_at, timezone)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * The administrator's dashboard (D85): cumulative clinic totals as of the
 * chosen date with change since the end of the previous month, that day's
 * appointments, the newest accounts and shortcuts to the management pages.
 */
export default function AdminDashboard() {
  const [day, setDay] = useState(null); // null: today, decided by the server
  const [version, setVersion] = useState(0);
  // `fetched_at`: when this browser received the figures (shown as "Last updated").
  const dashboard = useFetch(
    () => getAdminDashboard(day ?? undefined).then((res) => ({ ...res, data: { ...res.data, fetched_at: new Date().toISOString() } })),
    [day, version]
  );
  const data = dashboard.data;

  return (
    <div className="admin-dashboard">
      <header className="ds-head admin-head">
        <div className="schedule-head">
          <h1>Admin Dashboard</h1>
          <p className="muted">Clinic operations overview.</p>
        </div>
        <DateSelect value={data?.date ?? day} onChange={setDay} label="Dashboard date" />
      </header>

      {dashboard.error ? (
        <div className="card" role="alert">
          <p>{dashboard.error}</p>
          <button type="button" className="secondary" onClick={() => setVersion((n) => n + 1)}>
            Try again
          </button>
        </div>
      ) : !data ? (
        <div className="kpi-grid" role="status" aria-label="Loading dashboard">
          {Object.keys(KPIS).map((key) => (
            <div key={key} className="card skeleton" style={{ height: 120, margin: 0 }} />
          ))}
        </div>
      ) : (
        <>
          <div className="kpi-grid">
            {data.kpis.map((kpi) => (
              <KpiCard key={kpi.key} kpi={kpi} comparedTo={data.compared_to} />
            ))}
          </div>
          <div className="card admin-strip">
            <Info size={20} aria-hidden="true" className="admin-strip-icon" />
            <p>
              Total <strong>{data.kpis.reduce((sum, k) => sum + k.total, 0)}</strong> records across these five totals, created up to{" "}
              {calendarDate(`${data.date}T12:00:00Z`, "UTC")}.{" "}
              <span className="muted">Change is measured against the end of {monthName(data.compared_to)}.</span>
            </p>
            <span className="muted small admin-strip-time">Last updated: {stamp(data.fetched_at)}</span>
          </div>
          <div className="admin-pair">
            <RecentAppointments day={data.date} onChanged={() => setVersion((n) => n + 1)} />
            <RecentUsers users={data.recent_users} timezone={data.timezone} />
          </div>
        </>
      )}

      <section className="card admin-actions" aria-labelledby="admin-actions-title">
        <div className="pd-card-head">
          <Zap className="pd-icon admin-zap" size={28} aria-hidden="true" />
          <h2 id="admin-actions-title">Quick Management Actions</h2>
        </div>
        <div className="admin-action-grid">
          {ACTIONS.map(({ to, title, text, icon: Icon, tone }) => (
            <Link key={to} to={to} className="admin-action">
              <span className={`tile ${tone}`}>
                <Icon size={26} aria-hidden="true" />
              </span>
              <span className="admin-action-text">
                <strong>{title}</strong>
                <span className="muted small">{text}</span>
              </span>
              <ArrowRight size={18} aria-hidden="true" />
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
