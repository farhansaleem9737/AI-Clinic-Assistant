import { CalendarDays, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getErrorMessage } from "../../services/api";
import { changeAppointmentStatus, countAppointments, listAppointments } from "../../services/appointmentService";
import { CANCELLATION_REASONS, CONFIRM_ACTIONS, MENU_ACTIONS, STATUS_LABELS } from "../../utils/appointments";
import { dayParts, formatSlotTime } from "../../utils/datetime";
import { doctorName } from "../../utils/format";
import ActionMenu from "../ActionMenu";
import Alert from "../Alert";
import Avatar from "../Avatar";
import ConfirmDialog from "../ConfirmDialog";
import EmptyState from "../EmptyState";
import StatusBadge from "../StatusBadge";

const PREVIEW = 5;
const TABS = [
  { key: "upcoming", label: "Upcoming Appointments", empty: "No upcoming appointments." },
  { key: "past", label: "Recent Appointments", empty: "No past appointments yet." },
];
const longDate = (iso, timeZone) =>
  new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone }).format(new Date(iso));

function Row({ appointment: a, onAction }) {
  const day = dayParts(a.starts_at, a.timezone);
  const when = `${longDate(a.starts_at, a.timezone)}, ${formatSlotTime(a.starts_at, a.timezone)}`;
  const name = doctorName(a.doctor);
  const items = [
    { label: "View Appointment", to: `/appointments/${a.id}` },
    ...a.allowed_transitions
      .filter((s) => MENU_ACTIONS[s])
      .map((s) => ({ label: MENU_ACTIONS[s], onSelect: () => onAction(a, s), danger: s === "cancelled" || s === "no_show" })),
    a.can_reschedule && { label: "Reschedule", to: `/appointments/${a.id}?reschedule=1` },
  ].filter(Boolean);
  return (
    <tr>
      <td data-label="Date & Time">
        <div className="pa-when">
          <span className="pa-day" aria-hidden="true">
            <span>{day.month}</span>
            <strong>{String(day.day).padStart(2, "0")}</strong>
          </span>
          <span>
            <strong>{longDate(a.starts_at, a.timezone)}</strong>
            <span className="muted small">
              <time dateTime={a.starts_at}>{formatSlotTime(a.starts_at, a.timezone)}</time>
            </span>
          </span>
        </div>
      </td>
      <td data-label="Doctor">
        <div className="appt-patient">
          <Avatar name={a.doctor.name} role="doctor" src={a.doctor.photo_url} size={44} />
          <div>
            <strong>{name}</strong>
            <span className="muted small">{a.doctor.specialization}</span>
          </div>
        </div>
      </td>
      <td data-label="Reason / Type">
        <span className="appt-reason">{a.reason || <span className="muted">No reason given</span>}</span>
        <span className="muted small">{a.doctor.department_name}</span>
      </td>
      <td data-label="Status">
        <StatusBadge status={a.status} icon />
      </td>
      <td className="appt-actions">
        <Link to={`/appointments/${a.id}`} className="button secondary view-button">
          View<span className="sr-only">: {name}, {when}</span> <ChevronRight size={16} aria-hidden="true" />
        </Link>
        <ActionMenu label={`Actions for the appointment with ${name}, ${when}`} items={items} />
      </td>
    </tr>
  );
}

/**
 * One patient's appointments (D81): Upcoming and Recent with real counts,
 * the five nearest of each, and the actions the state machine allows the
 * caller. "View All" opens the appointment list filtered by this patient.
 */
export default function PatientAppointmentsCard({ patientId, id }) {
  const [tab, setTab] = useState("upcoming");
  const [counts, setCounts] = useState(null);
  const [lists, setLists] = useState({});
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [pending, setPending] = useState(null);
  const [reason, setReason] = useState("patient_request");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    const filter = { patient_id: patientId };
    Promise.all([
      countAppointments(filter),
      listAppointments({ ...filter, scope: "upcoming", page_size: PREVIEW }),
      listAppointments({ ...filter, scope: "past", newest_first: true, page_size: PREVIEW }),
    ])
      .then(([c, upcoming, past]) => {
        if (cancelled) return;
        setCounts(c.data);
        setLists({ upcoming: upcoming.data.items, past: past.data.items });
        setError("");
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err, "Could not load the appointments")));
    return () => {
      cancelled = true;
    };
  }, [patientId, attempt]);

  const run = async (appointment, status) => {
    setBusy(true);
    setActionError("");
    try {
      await changeAppointmentStatus(appointment.id, {
        status,
        ...(status === "cancelled" ? { cancellation_reason: reason } : {}),
      });
      setPending(null);
      setNotice(`The appointment is now ${STATUS_LABELS[status].toLowerCase()}.`);
      setAttempt((n) => n + 1);
    } catch (err) {
      const message = getErrorMessage(err, "Could not update the appointment");
      if (pending) setActionError(message);
      else setError(message);
    } finally {
      setBusy(false);
    }
  };
  const onAction = (appointment, status) => {
    setNotice("");
    setActionError("");
    if (CONFIRM_ACTIONS[status]) {
      setReason("patient_request");
      setPending({ appointment, status });
    } else run(appointment, status);
  };

  const items = lists[tab] ?? [];
  const current = TABS.find((t) => t.key === tab);
  return (
    <section className="card pd-card pd-appointments" id={id} aria-labelledby="pd-appointments-title">
      <div className="pd-card-head">
        <CalendarDays className="pd-icon" size={30} aria-hidden="true" />
        <h2 id="pd-appointments-title" tabIndex={-1}>
          Appointments
        </h2>
        <Link to={`/appointments?patient=${patientId}`} className="button secondary view-all">
          View All <ChevronRight size={16} aria-hidden="true" />
        </Link>
      </div>

      <div className="pd-subtabs" role="tablist" aria-label="Appointment lists">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            aria-controls="pd-appointments-panel"
            className={tab === t.key ? "active" : ""}
            onClick={() => setTab(t.key)}
          >
            {t.label}
            {counts && ` (${t.key === "upcoming" ? counts.upcoming : counts.past})`}
          </button>
        ))}
      </div>
      <div aria-live="polite">
        <Alert kind="success">{notice}</Alert>
      </div>

      <div id="pd-appointments-panel" role="tabpanel">
        {error ? (
          <div role="alert" className="appt-error">
            <p>{error}</p>
            <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </button>
          </div>
        ) : !counts ? (
          <div role="status" aria-label="Loading appointments">
            <div className="skeleton appt-skeleton" />
            <div className="skeleton appt-skeleton" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState icon={CalendarDays}>{current.empty}</EmptyState>
        ) : (
          <div className="appt-table-wrap">
            <table className="appt-table pd-table">
              <thead>
                <tr>
                  <th scope="col">Date &amp; Time</th>
                  <th scope="col">Doctor</th>
                  <th scope="col">Reason / Type</th>
                  <th scope="col">Status</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((a) => (
                  <Row key={a.id} appointment={a} onAction={onAction} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

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
            {doctorName(pending.appointment.doctor)}, {longDate(pending.appointment.starts_at, pending.appointment.timezone)}{" "}
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
    </section>
  );
}
