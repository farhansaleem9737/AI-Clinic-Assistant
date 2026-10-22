import { CalendarDays, History, NotebookPen, UserRound } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { getErrorMessage } from "../../services/api";
import { CANCELLATION_REASONS, STATUS_LABELS } from "../../utils/appointments";
import { formatCalendarDate, formatDateTime, formatLongDate, formatTime } from "../../utils/datetime";
import { appointmentLocation } from "../../utils/ics";
import { SEX_LABELS } from "../../utils/patient";
import { telHref } from "../../utils/support";
import Alert from "../Alert";
import StatusBadge from "../StatusBadge";

const TABS = [
  { id: "details", label: "Details" },
  { id: "notes", label: "Notes" },
  { id: "history", label: "History" },
];

const NOT_PROVIDED = <span className="muted">Not provided</span>;

function Info({ label, children }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children || NOT_PROVIDED}</dd>
    </div>
  );
}

function PanelCard({ icon: Icon, title, children }) {
  const headingId = useId();
  return (
    <section className="card" aria-labelledby={headingId}>
      <div className="section-head">
        <Icon className="icon" size={20} aria-hidden="true" />
        <h3 id={headingId}>{title}</h3>
      </div>
      {children}
    </section>
  );
}

function PatientInformation({ appointment: a, canOpenRecord }) {
  const profile = a.patient_profile;
  return (
    <PanelCard icon={UserRound} title="Patient Information">
      <div className="info-grid">
        <dl className="info-list">
          <Info label="Full Name">{a.patient.name}</Info>
          <Info label="Date of Birth">{formatCalendarDate(a.patient.date_of_birth)}</Info>
          {profile && <Info label="Sex at birth">{SEX_LABELS[profile.sex_at_birth] ?? profile.sex_at_birth}</Info>}
          <Info label="MRN">{a.patient.mrn}</Info>
        </dl>
        {profile ? (
          <dl className="info-list">
            <Info label="Phone">{profile.phone && <a href={telHref(profile.phone)}>{profile.phone}</a>}</Info>
            <Info label="Email">{profile.email && <a href={`mailto:${profile.email}`}>{profile.email}</a>}</Info>
            <Info label="Address">{profile.address}</Info>
          </dl>
        ) : (
          <p className="muted">The patient&apos;s contact details are not available to your account.</p>
        )}
      </div>
      {canOpenRecord && (
        <p className="panel-link">
          <Link to={`/patients/${a.patient.id}`}>Open patient record</Link>
        </p>
      )}
    </PanelCard>
  );
}

function AppointmentInformation({ appointment: a }) {
  const tz = a.timezone;
  const location = appointmentLocation(a);
  return (
    <PanelCard icon={CalendarDays} title="Appointment Information">
      <dl className="info-list ruled">
        <Info label="Reason">{a.reason}</Info>
        <Info label="Date">
          <time dateTime={a.starts_at}>{formatLongDate(a.starts_at, tz)}</time>
        </Info>
        <Info label="Time">
          {formatTime(a.starts_at, tz)} – {formatTime(a.ends_at, tz)} <span className="muted small">({tz})</span>
        </Info>
        <Info label="Location">{location}</Info>
        <Info label="Status">
          <StatusBadge status={a.status} icon />
        </Info>
        {a.status === "cancelled" && (
          <Info label="Cancelled">
            {CANCELLATION_REASONS[a.cancellation_reason] ?? (a.cancellation_reason === "rescheduled" ? "Rescheduled" : a.cancellation_reason)}
            {a.cancelled_at && <span className="muted small"> · {formatDateTime(a.cancelled_at, tz)}</span>}
          </Info>
        )}
        {a.rescheduled_to_id && (
          <Info label="Moved to">
            <Link to={`/appointments/${a.rescheduled_to_id}`}>View the new appointment</Link>
          </Info>
        )}
        {a.rescheduled_from_id && (
          <Info label="Rescheduled from">
            <Link to={`/appointments/${a.rescheduled_from_id}`}>View the earlier appointment</Link>
          </Info>
        )}
        <Info label="Booked on">{formatDateTime(a.created_at, tz)}</Info>
      </dl>
    </PanelCard>
  );
}

function StaffNotes({ appointment, canEdit, onSave }) {
  const [draft, setDraft] = useState(appointment.staff_notes ?? "");
  const [state, setState] = useState({ busy: false, error: "", saved: false });

  if (!canEdit) {
    return appointment.staff_notes ? <p className="prose">{appointment.staff_notes}</p> : <p className="muted">No staff notes.</p>;
  }
  const save = async (event) => {
    event.preventDefault();
    setState({ busy: true, error: "", saved: false });
    try {
      await onSave(draft.trim() || null);
      setState({ busy: false, error: "", saved: true });
    } catch (err) {
      setState({ busy: false, error: getErrorMessage(err, "Could not save the notes"), saved: false });
    }
  };
  return (
    <form className="stack wide" onSubmit={save}>
      <label>
        Staff notes
        <textarea value={draft} maxLength={1000} onChange={(e) => setDraft(e.target.value)} />
      </label>
      <Alert>{state.error}</Alert>
      <div className="row">
        <button type="submit" disabled={state.busy}>
          {state.busy ? "Saving…" : "Save notes"}
        </button>
        {state.saved && (
          <span className="muted small" role="status">
            Notes saved.
          </span>
        )}
      </div>
    </form>
  );
}

function Notes({ appointment: a, staffView, canEditNotes, onSaveNotes }) {
  return (
    <PanelCard icon={NotebookPen} title="Notes">
      <h4 className="panel-subhead">Reason for visit</h4>
      {a.reason ? <p className="prose">{a.reason}</p> : <p className="muted">No reason was given when booking.</p>}
      {a.cancellation_note && (
        <>
          <h4 className="panel-subhead">Cancellation note</h4>
          <p className="prose">{a.cancellation_note}</p>
        </>
      )}
      {staffView ? (
        <>
          <h4 className="panel-subhead">
            Staff notes <span className="muted small">(not visible to the patient)</span>
          </h4>
          <StaffNotes key={a.id} appointment={a} canEdit={canEditNotes} onSave={onSaveNotes} />
        </>
      ) : (
        <p className="muted small panel-foot">Notes from your consultation are not available online yet.</p>
      )}
    </PanelCard>
  );
}

function actorLabel(entry, currentUserId) {
  if (entry.changed_by_user_id === null) return "Automatically";
  if (entry.changed_by_user_id === currentUserId) return "By you";
  return null;
}

function HistoryPanel({ appointment, history, currentUserId, onRetry }) {
  return (
    <PanelCard icon={History} title="History">
      {history.error ? (
        <>
          <Alert>{history.error}</Alert>
          <button type="button" className="secondary" onClick={onRetry}>
            Try again
          </button>
        </>
      ) : !history.data ? (
        <div role="status" aria-label="Loading history">
          <div className="skeleton" style={{ height: 48, marginBottom: 8 }} />
          <div className="skeleton" style={{ height: 48 }} />
        </div>
      ) : history.data.length === 0 ? (
        <p className="muted">No changes have been recorded yet.</p>
      ) : (
        <ol className="timeline">
          {history.data.map((entry, index) => {
            const actor = actorLabel(entry, currentUserId);
            return (
              <li key={index}>
                <h3>{STATUS_LABELS[entry.to_status] ?? entry.to_status}</h3>
                <p className="muted small">
                  <time dateTime={entry.changed_at}>{formatDateTime(entry.changed_at, appointment.timezone)}</time>
                  {entry.from_status && ` · from ${STATUS_LABELS[entry.from_status] ?? entry.from_status}`}
                  {actor && ` · ${actor}`}
                </p>
                {entry.reason && <p>{entry.reason}</p>}
              </li>
            );
          })}
        </ol>
      )}
    </PanelCard>
  );
}

/**
 * Details / Notes / History for one appointment, as keyboard-operable tabs
 * (arrow keys, Home, End). Everything shown comes from the API response:
 * staff notes only exist in the staff/doctor view, history from the
 * appointment's recorded status changes.
 */
export default function AppointmentTabs({ appointment, history, staffView, canEditNotes, canOpenRecord, currentUserId, onSaveNotes, onRetryHistory }) {
  const [active, setActive] = useState("details");

  const onKeyDown = (event) => {
    const index = TABS.findIndex((t) => t.id === active);
    const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: TABS.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const target = TABS[(next + TABS.length) % TABS.length];
    setActive(target.id);
    document.getElementById(`appt-tab-${target.id}`)?.focus();
  };

  return (
    <div className="appt-detail-main">
      <div className="card tab-strip" role="tablist" aria-label="Appointment sections" onKeyDown={onKeyDown}>
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`appt-tab-${t.id}`}
            aria-selected={active === t.id}
            aria-controls="appt-tab-panel"
            tabIndex={active === t.id ? 0 : -1}
            className={active === t.id ? "active" : ""}
            onClick={() => setActive(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div id="appt-tab-panel" role="tabpanel" aria-labelledby={`appt-tab-${active}`}>
        {active === "details" && (
          <>
            <PatientInformation appointment={appointment} canOpenRecord={canOpenRecord} />
            <AppointmentInformation appointment={appointment} />
          </>
        )}
        {active === "notes" && (
          <Notes appointment={appointment} staffView={staffView} canEditNotes={canEditNotes} onSaveNotes={onSaveNotes} />
        )}
        {active === "history" && (
          <HistoryPanel appointment={appointment} history={history} currentUserId={currentUserId} onRetry={onRetryHistory} />
        )}
      </div>
    </div>
  );
}
