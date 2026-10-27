import {
  ArrowRight,
  BadgeCheck,
  BriefcaseMedical,
  Building2,
  CalendarDays,
  CalendarPlus,
  CalendarSync,
  ChevronRight,
  CircleX,
  Clock,
  MapPin,
  Phone,
  Stethoscope,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import Alert from "../components/Alert";
import AppointmentTabs from "../components/appointments/AppointmentTabs";
import Avatar from "../components/Avatar";
import Breadcrumb from "../components/Breadcrumb";
import ConfirmDialog from "../components/ConfirmDialog";
import SlotPicker from "../components/SlotPicker";
import StatusBadge from "../components/StatusBadge";
import { useAuth } from "../context/useAuth";
import { useFetch } from "../hooks/useFetch";
import { HOME_PATH } from "../routes/navigation";
import { getErrorMessage } from "../services/api";
import {
  changeAppointmentStatus,
  getAppointment,
  getAppointmentHistory,
  rescheduleAppointment,
  updateAppointment,
} from "../services/appointmentService";
import { ACTION_LABELS, CANCELLATION_REASONS, STATUS_LABELS } from "../utils/appointments";
import { formatDateTime, formatLongDate, formatTime } from "../utils/datetime";
import { doctorName } from "../utils/format";
import { appointmentLocation, canAddToCalendar, downloadAppointmentIcs } from "../utils/ics";
import { SUPPORT_EMAIL, SUPPORT_PHONE, telHref } from "../utils/support";
import NotFound from "./NotFound";

// Statuses from which the clinic still allows changes (appointment_state.PRE_CHECK_IN).
const CHANGEABLE = ["requested", "scheduled", "confirmed"];

const DONE_TEXT = {
  confirmed: "Thank you, your attendance is confirmed.",
  checked_in: "The patient is checked in.",
  in_progress: "The consultation has started.",
  completed: "The appointment is completed.",
  no_show: "Recorded as a no-show.",
  scheduled: "The appointment is scheduled.",
};

// Why an action the API does not allow right now is unavailable.
function blockedReason(appointment) {
  if (!CHANGEABLE.includes(appointment.status)) {
    return `This appointment is ${STATUS_LABELS[appointment.status].toLowerCase()} and can no longer be changed.`;
  }
  return "Changes are no longer possible online. Please contact the clinic.";
}

function QuickAction({ icon: Icon, label, hint, onClick, to, href, disabled, danger }) {
  const content = (
    <>
      <Icon className="icon" size={20} aria-hidden="true" />
      <span className="label">
        {label}
        {hint && <small>{hint}</small>}
      </span>
      {!disabled && <ChevronRight className="chevron" size={18} aria-hidden="true" />}
    </>
  );
  const className = `quick-item${danger ? " danger" : ""}`;
  if (to) {
    return (
      <Link to={to} className={className}>
        {content}
      </Link>
    );
  }
  if (href) {
    return (
      <a href={href} className={className}>
        {content}
      </a>
    );
  }
  return (
    <button type="button" className={className} onClick={onClick} disabled={disabled}>
      {content}
    </button>
  );
}

function contactAction() {
  if (SUPPORT_PHONE) return { href: telHref(SUPPORT_PHONE), hint: SUPPORT_PHONE };
  if (SUPPORT_EMAIL) return { href: `mailto:${SUPPORT_EMAIL}`, hint: SUPPORT_EMAIL };
  return { to: "/help#contact", hint: "How to reach the clinic" };
}

/**
 * One appointment: summary, Details / Notes / History, and the actions the
 * API says this caller may take now (`allowed_transitions`, `can_reschedule`).
 * Every action is checked again by the server when it is submitted.
 */
export default function AppointmentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { user, can } = useAuth();

  const [attempt, setAttempt] = useState(0);
  const appointmentFetch = useFetch(() => getAppointment(id), [id, attempt]);
  const history = useFetch(() => getAppointmentHistory(id), [id, attempt]);
  const refresh = () => setAttempt((n) => n + 1);

  // A notice belongs to the history entry it was shown on, e.g. "booked"
  // when arriving from the booking page or "moved" after a reschedule.
  const [flash, setFlash] = useState({ key: location.key, text: location.state?.notice ?? "" });
  if (flash.key !== location.key) setFlash({ key: location.key, text: location.state?.notice ?? "" });
  const notify = (text) => setFlash({ key: location.key, text });

  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(null); // { reason, note, busy, error }
  // "Reschedule" in the appointments list links here with ?reschedule=1.
  const [rescheduling, setRescheduling] = useState(searchParams.get("reschedule") === "1");
  const [move, setMove] = useState({ slot: null, busy: false, error: "", picker: 0 });
  const rescheduleHeading = useRef(null);

  // Keep the previous appointment off screen while another id loads.
  const a = appointmentFetch.data?.id === id ? appointmentFetch.data : null;
  const showPicker = rescheduling && a?.can_reschedule;

  useEffect(() => {
    if (showPicker) {
      rescheduleHeading.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
      rescheduleHeading.current?.focus({ preventScroll: true });
    }
  }, [showPicker]);

  if (appointmentFetch.status === 404 || appointmentFetch.status === 422) {
    return (
      <NotFound
        message="This appointment does not exist, or it is not one you can view."
        backTo="/appointments"
        backLabel="All appointments"
      />
    );
  }
  if (appointmentFetch.error) {
    const forbidden = appointmentFetch.status === 403;
    return (
      <div className="card">
        <Alert>{forbidden ? "You do not have permission to view this appointment." : appointmentFetch.error}</Alert>
        <div className="row">
          {!forbidden && (
            <button type="button" onClick={refresh}>
              Try again
            </button>
          )}
          <Link to="/appointments" className="button secondary">
            All appointments
          </Link>
        </div>
      </div>
    );
  }
  if (!a) {
    return (
      <div role="status" aria-label="Loading appointment">
        <div className="card skeleton" style={{ height: 190 }} />
        <div className="card skeleton" style={{ height: 320 }} />
      </div>
    );
  }

  const tz = a.timezone;
  const name = doctorName(a.doctor);
  // The server sends staff notes only to staff and the treating doctor.
  const staffView = "staff_notes" in a;
  const pending = busy || appointmentFetch.loading;
  const canCancel = a.allowed_transitions.includes("cancelled");
  const otherActions = a.allowed_transitions.filter((s) => s !== "cancelled");
  const roomAndDepartment = appointmentLocation(a);
  const blocked = blockedReason(a);
  const contact = contactAction();

  const transition = async (to) => {
    setBusy(true);
    setActionError("");
    notify("");
    try {
      await changeAppointmentStatus(id, { status: to });
      notify(DONE_TEXT[to] ?? `Marked ${STATUS_LABELS[to]}.`);
      refresh();
    } catch (err) {
      setActionError(getErrorMessage(err, "Could not update the appointment"));
    } finally {
      setBusy(false);
    }
  };

  const openCancel = () => setCancelling({ reason: "patient_request", note: "", busy: false, error: "" });
  const confirmCancel = async () => {
    setCancelling((c) => ({ ...c, busy: true, error: "" }));
    try {
      await changeAppointmentStatus(id, {
        status: "cancelled",
        cancellation_reason: cancelling.reason,
        note: cancelling.note.trim() || null,
      });
      setCancelling(null);
      setActionError("");
      notify(staffView ? "The appointment has been cancelled." : "Your appointment has been cancelled.");
      refresh();
    } catch (err) {
      setCancelling((c) => ({ ...c, busy: false, error: getErrorMessage(err, "Could not cancel the appointment") }));
    }
  };

  const startReschedule = () => {
    setRescheduling(true);
    if (showPicker) rescheduleHeading.current?.focus();
  };
  const confirmReschedule = async () => {
    setMove((m) => ({ ...m, busy: true, error: "" }));
    try {
      const res = await rescheduleAppointment(id, { starts_at: move.slot.starts_at });
      setRescheduling(false);
      setMove({ slot: null, busy: false, error: "", picker: 0 });
      const when = formatDateTime(res.data.starts_at, res.data.timezone);
      navigate(`/appointments/${res.data.id}`, { state: { notice: `The appointment has been moved to ${when}.` } });
    } catch (err) {
      // The chosen time may have just been taken: reload the free times.
      setMove((m) => ({ slot: null, busy: false, error: getErrorMessage(err, "Could not move the appointment"), picker: m.picker + 1 }));
      refresh();
    }
  };

  return (
    <div className="appointment-detail">
      <Breadcrumb items={[{ label: "Home", to: HOME_PATH }, { label: "Appointments", to: "/appointments" }, { label: "Appointment Details" }]} />
      <div className="page-head">
        <div>
          <h1>Appointment Details</h1>
          <p className="muted">
            {staffView ? "View the appointment and manage the visit." : "View your appointment information and manage your visit."}
          </p>
        </div>
      </div>

      <Alert kind="success">{flash.text}</Alert>
      <Alert>{actionError}</Alert>

      <section className="card appt-summary" aria-label="Appointment summary">
        <div className="appt-summary-doctor">
          <Avatar name={a.doctor.name} role="doctor" size={112} src={a.doctor.photo_url} />
          <div>
            <h2>
              {name}
              {a.doctor.is_verified && (
                <BadgeCheck className="verified" size={22} role="img" aria-label="Verified: medical license on file" />
              )}
            </h2>
            <p className="specialization">{a.doctor.specialization}</p>
            <p className="muted">{a.doctor.department_name}</p>
            <ul className="appt-summary-facts">
              {a.doctor.years_of_experience > 0 && (
                <li>
                  <BriefcaseMedical size={18} aria-hidden="true" />
                  {a.doctor.years_of_experience} years experience
                </li>
              )}
              <li>
                <Building2 size={18} aria-hidden="true" />
                {a.doctor.department_name} Department
              </li>
            </ul>
          </div>
        </div>

        <ul className="appt-summary-when">
          <li>
            <CalendarDays size={20} aria-hidden="true" />
            <time dateTime={a.starts_at}>{formatLongDate(a.starts_at, tz)}</time>
          </li>
          <li>
            <Clock size={20} aria-hidden="true" />
            <span>
              {formatTime(a.starts_at, tz)} – {formatTime(a.ends_at, tz)}
              <small>Clinic time ({tz})</small>
            </span>
          </li>
          {roomAndDepartment && (
            <li>
              <MapPin size={20} aria-hidden="true" />
              <span>
                {a.doctor.room_number ? `Room ${a.doctor.room_number}` : a.doctor.department_name}
                {a.doctor.room_number && <small>{a.doctor.department_name}</small>}
              </span>
            </li>
          )}
        </ul>

        <div className="appt-summary-side">
          <StatusBadge status={a.status} icon />
          {a.can_reschedule && (
            <button type="button" onClick={startReschedule} disabled={pending}>
              <CalendarSync size={18} aria-hidden="true" /> Reschedule
            </button>
          )}
          {canCancel && (
            <button type="button" className="danger" onClick={openCancel} disabled={pending}>
              <CircleX size={18} aria-hidden="true" /> Cancel Appointment
            </button>
          )}
          {otherActions.map((to) => (
            <button key={to} type="button" className="secondary" onClick={() => transition(to)} disabled={pending}>
              {to === "confirmed" && !staffView ? "Confirm attendance" : ACTION_LABELS[to]}
            </button>
          ))}
        </div>
      </section>

      {showPicker && (
        <section className="card appt-reschedule" aria-labelledby="reschedule-heading">
          <h2 id="reschedule-heading" ref={rescheduleHeading} tabIndex={-1}>
            Choose a new time
          </h2>
          <p className="muted">
            Free times with {name}. Your current appointment stays booked until the new time is confirmed.
          </p>
          <SlotPicker key={move.picker} doctorId={a.doctor.id} selected={move.slot} onSelect={(slot) => setMove((m) => ({ ...m, slot, error: "" }))} />
          <Alert>{move.error}</Alert>
          <div className="row">
            <button type="button" disabled={!move.slot || move.busy} onClick={confirmReschedule}>
              {move.busy
                ? "Moving…"
                : move.slot
                  ? `Confirm new time: ${formatDateTime(move.slot.starts_at, move.slot.timezone)}`
                  : "Select a new time"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={move.busy}
              onClick={() => {
                setRescheduling(false);
                setMove((m) => ({ ...m, slot: null, error: "" }));
              }}
            >
              Keep current time
            </button>
          </div>
        </section>
      )}

      <div className="appt-detail-grid">
        <AppointmentTabs
          appointment={a}
          history={history}
          staffView={staffView}
          canEditNotes={can("appointment:manage")}
          canOpenRecord={can("patient:read_any") || can("patient:read_assigned")}
          currentUserId={user?.id}
          onSaveNotes={(notes) => updateAppointment(id, { staff_notes: notes })}
          onRetryHistory={refresh}
        />

        <section className="card appt-quick" aria-labelledby="quick-actions">
          <div className="section-head">
            <Zap className="icon" size={20} aria-hidden="true" />
            <h3 id="quick-actions">Quick Actions</h3>
          </div>
          <ul className="quick-list">
            <li>
              <QuickAction
                icon={CalendarSync}
                label="Reschedule Appointment"
                hint={a.can_reschedule ? null : blocked}
                disabled={!a.can_reschedule || pending}
                onClick={startReschedule}
              />
            </li>
            <li>
              <QuickAction
                icon={CircleX}
                label="Cancel Appointment"
                hint={canCancel ? null : blocked}
                disabled={!canCancel || pending}
                onClick={openCancel}
                danger
              />
            </li>
            <li>
              <QuickAction
                icon={CalendarPlus}
                label="Add to Calendar"
                hint={canAddToCalendar(a) ? "Download a calendar file (.ics)" : "Only upcoming appointments can be added."}
                disabled={!canAddToCalendar(a)}
                onClick={() => downloadAppointmentIcs(a)}
              />
            </li>
            <li>
              <QuickAction icon={Phone} label="Contact Clinic" {...contact} />
            </li>
          </ul>
        </section>

        <section className="card appt-doctor" aria-labelledby="doctor-information">
          <div className="section-head">
            <Stethoscope className="icon" size={20} aria-hidden="true" />
            <h3 id="doctor-information">Doctor Information</h3>
          </div>
          <div className="doctor-mini">
            <Avatar name={a.doctor.name} role="doctor" size={80} src={a.doctor.photo_url} />
            <div>
              <h4>
                {name}
                {a.doctor.is_verified && (
                  <BadgeCheck className="verified" size={18} role="img" aria-label="Verified: medical license on file" />
                )}
              </h4>
              <p>{a.doctor.specialization}</p>
              <p className="muted">{a.doctor.department_name}</p>
            </div>
          </div>
          <Link to={`/doctors/${a.doctor.id}`} className="button secondary block">
            View Doctor Profile <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </section>
      </div>

      {cancelling && (
        <ConfirmDialog
          title="Cancel this appointment?"
          confirmLabel="Cancel appointment"
          cancelLabel="Keep appointment"
          danger
          busy={cancelling.busy}
          error={cancelling.error}
          onConfirm={confirmCancel}
          onCancel={() => setCancelling(null)}
        >
          <p>
            {name} on <strong>{formatDateTime(a.starts_at, tz)}</strong>. The time will be released for other patients.
          </p>
          {staffView && (
            <label>
              Reason
              <select value={cancelling.reason} onChange={(e) => setCancelling((c) => ({ ...c, reason: e.target.value }))}>
                {Object.entries(CANCELLATION_REASONS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            {staffView ? "Note (optional)" : "Note for the clinic (optional)"}
            <textarea
              value={cancelling.note}
              maxLength={500}
              onChange={(e) => setCancelling((c) => ({ ...c, note: e.target.value }))}
            />
          </label>
        </ConfirmDialog>
      )}
    </div>
  );
}
