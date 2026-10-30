import { CalendarDays, ChevronLeft, ChevronRight, Search, SearchX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import ActionMenu from "../components/ActionMenu";
import Alert from "../components/Alert";
import Avatar from "../components/Avatar";
import ConfirmDialog from "../components/ConfirmDialog";
import DateSelect from "../components/DateSelect";
import EmptyState from "../components/EmptyState";
import NumberedPager from "../components/NumberedPager";
import StatusBadge from "../components/StatusBadge";
import { getErrorMessage } from "../services/api";
import { changeAppointmentStatus, countAppointmentsByDay, listAppointments } from "../services/appointmentService";
import { CANCELLATION_REASONS, CONFIRM_ACTIONS, MENU_ACTIONS, STATUS_LABELS } from "../utils/appointments";
import { addDays, formatSlotTime } from "../utils/datetime";
import {
  countParams,
  doctorListParams,
  DOCTOR_PAGE_SIZE,
  mediumDay,
  readDay,
  shortDay,
  VIEWS,
  weekday,
} from "../utils/doctorAppointments";
import { ageFromDateOfBirth } from "../utils/patient";

const SEARCH_DELAY_MS = 350;
const ACTIVE = ["requested", "scheduled", "confirmed", "checked_in", "in_progress"];
const EMPTY = {
  day: "No appointments on this date.",
  upcoming: "No upcoming appointments after today.",
  past: "No past appointments.",
};

function PatientCell({ patient }) {
  const age = ageFromDateOfBirth(patient.date_of_birth);
  return (
    <div className="appt-patient">
      <Avatar name={patient.name} role="patient" src={patient.photo_url} size={48} alt={`Photo of ${patient.name}`} />
      <div>
        <strong>{patient.name}</strong>
        <span className="muted small">
          {[age != null && `${age} years`, `#${patient.mrn}`].filter(Boolean).join(" · ")}
        </span>
      </div>
    </div>
  );
}

function Row({ appointment: a, showDate, isNext, onAction }) {
  const time = formatSlotTime(a.starts_at, a.timezone);
  const localDay = new Intl.DateTimeFormat("en-CA", { timeZone: a.timezone }).format(new Date(a.starts_at));
  const label = `${a.patient.name}, ${showDate ? `${mediumDay(localDay)} ` : ""}${time}`;
  const items = [
    { label: "View Details", to: `/appointments/${a.id}` },
    ...a.allowed_transitions
      .filter((status) => MENU_ACTIONS[status])
      .map((status) => ({
        label: MENU_ACTIONS[status],
        onSelect: () => onAction(a, status),
        danger: status === "cancelled" || status === "no_show",
      })),
    a.can_reschedule && { label: "Reschedule", to: `/appointments/${a.id}?reschedule=1` },
  ].filter(Boolean);

  return (
    <tr className={isNext ? "is-next" : ""}>
      <td data-label="Time">
        <strong className="appt-time">
          <time dateTime={a.starts_at}>{time}</time>
        </strong>
        {showDate && <span className="muted small appt-date">{shortDay(localDay)}</span>}
        {isNext && <span className="next-tag">Next</span>}
      </td>
      <td data-label="Patient">
        <PatientCell patient={a.patient} />
      </td>
      <td data-label="Reason / Type">
        <span className="appt-reason">{a.reason || <span className="muted">No reason given</span>}</span>
        {a.rescheduled_from_id && <span className="muted small">Rescheduled appointment</span>}
      </td>
      <td data-label="Status">
        <StatusBadge status={a.status} icon />
      </td>
      <td className="appt-actions">
        <Link to={`/appointments/${a.id}`} className="button secondary view-button">
          View<span className="sr-only">: {label}</span> <ChevronRight size={16} aria-hidden="true" />
        </Link>
        <ActionMenu label={`Actions for ${label}`} items={items} />
      </td>
    </tr>
  );
}

/**
 * The doctor's own appointments (D79): a day's schedule plus Upcoming and
 * Past, with real counts, status filter, patient search and paging. The API
 * returns only this doctor's appointments and, per row, the actions the
 * state machine allows. The URL keeps the view, date, status and page; the
 * search text (a patient's name) stays out of it.
 */
export default function DoctorAppointments() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const view = VIEWS.includes(searchParams.get("view")) ? searchParams.get("view") : "day";
  const selected = readDay(searchParams.get("date"));
  const status = STATUS_LABELS[searchParams.get("status")] ? searchParams.get("status") : "";
  const page = Math.max(1, Number(searchParams.get("page")) || 1);

  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [counts, setCounts] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(null); // { appointment, status } awaiting confirmation
  const [cancelReason, setCancelReason] = useState("doctor_unavailable");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  const update = (changes) => {
    const next = { view, date: selected, status, page, ...changes };
    const params = new URLSearchParams();
    if (next.view !== "day") params.set("view", next.view);
    if (next.date) params.set("date", next.date);
    if (next.status) params.set("status", next.status);
    if (next.page > 1) params.set("page", String(next.page));
    setSearchParams(params);
  };

  // Counts first: they also tell the doctor's timezone and today's date,
  // which the Upcoming / Past ranges are measured from.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const countRes = await countAppointmentsByDay(countParams({ day: selected, status, q }));
        if (cancelled) return;
        const c = countRes.data;
        const listRes = await listAppointments(doctorListParams({ view, day: c.day, today: c.today, status, q, page }));
        if (cancelled) return;
        setCounts(c);
        setData(listRes.data);
        setError("");
      } catch (err) {
        if (!cancelled) setError(getErrorMessage(err, "Could not load your appointments"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [view, selected, status, q, page, attempt]);

  const day = counts?.day ?? selected;
  const isToday = counts && day === counts.today;
  const filtered = Boolean(status || q.trim());

  const onSearch = (value) => {
    setTyped(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setQ(value);
      update({ page: 1 });
    }, SEARCH_DELAY_MS);
  };
  const clearFilters = () => {
    clearTimeout(timer.current);
    setTyped("");
    setQ("");
    update({ status: "", page: 1 });
  };
  const goToDay = (value) => update({ view: "day", date: value, page: 1 });

  const run = async (appointment, target) => {
    setBusy(true);
    setActionError("");
    try {
      await changeAppointmentStatus(appointment.id, {
        status: target,
        ...(target === "cancelled" ? { cancellation_reason: cancelReason } : {}),
      });
      setPending(null);
      setNotice(`${appointment.patient.name}: ${STATUS_LABELS[target].toLowerCase()}.`);
      setAttempt((n) => n + 1); // reload the list and the counts
    } catch (err) {
      const message = getErrorMessage(err, "Could not update the appointment");
      if (pending) {
        setActionError(message);
      } else {
        setNotice("");
        setError(message);
      }
    } finally {
      setBusy(false);
    }
  };
  const onAction = (appointment, target) => {
    setNotice("");
    setActionError("");
    if (CONFIRM_ACTIONS[target]) {
      setCancelReason("doctor_unavailable");
      setPending({ appointment, status: target });
    } else run(appointment, target);
  };

  const items = data?.items ?? [];
  const nextId =
    view === "day" && isToday
      ? items.find((a) => ACTIVE.includes(a.status) && new Date(a.ends_at) > new Date())?.id
      : null;
  const tabs = [
    { key: "day", label: isToday || !counts ? "Today" : mediumDay(day), count: counts?.on_day },
    { key: "upcoming", label: "Upcoming", count: counts?.upcoming },
    { key: "past", label: "Past", count: counts?.past },
  ];
  const bannerTitle = view === "day" ? (isToday ? "Today's Schedule" : "Schedule for Selected Date") : view === "upcoming" ? "Upcoming Appointments" : "Past Appointments";
  const bannerCount = view === "day" ? counts?.on_day : view === "upcoming" ? counts?.upcoming : counts?.past;
  const bannerText =
    bannerCount == null
      ? "Loading…"
      : `You have ${bannerCount} appointment${bannerCount === 1 ? "" : "s"}${
          view === "day" ? (isToday ? " today" : " on this date") : view === "upcoming" ? " after today" : " before today"
        }${filtered ? " matching your filters" : ""}.`;

  return (
    <div className="doctor-appointments">
      <header className="schedule-head">
        <h1>My Appointments</h1>
        <p className="muted">View and manage your appointments.</p>
      </header>

      <div className="appt-toolbar">
        <div className="appt-tabs" role="tablist" aria-label="Appointment views">
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={view === t.key}
              aria-controls="appt-panel"
              className={view === t.key ? "active" : ""}
              onClick={() => update({ view: t.key, page: 1 })}
            >
              {t.label}
              {t.count != null && ` (${t.count})`}
            </button>
          ))}
        </div>
        <DateSelect value={day} onChange={goToDay} />
        <label className="appt-status-filter">
          <span className="sr-only">Status</span>
          <select value={status} onChange={(e) => update({ status: e.target.value, page: 1 })}>
            <option value="">All Statuses</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <div className="appt-search">
          <Search size={20} aria-hidden="true" />
          <input
            type="search"
            aria-label="Search patients"
            placeholder="Search patients..."
            value={typed}
            maxLength={100}
            onChange={(e) => onSearch(e.target.value)}
          />
        </div>
      </div>

      <div aria-live="polite">
        <Alert kind="success">{notice}</Alert>
      </div>

      <section className="card appt-board" id="appt-panel" role="tabpanel" aria-labelledby="appt-banner-title" aria-busy={loading}>
        <div className="appt-banner">
          <CalendarDays className="appt-banner-icon" size={46} aria-hidden="true" />
          <div className="appt-banner-text">
            <h2 id="appt-banner-title">{bannerTitle}</h2>
            <p>{bannerText}</p>
          </div>
          <div className="appt-banner-side">
            {day && (
              <div className="appt-banner-date">
                <strong>{mediumDay(day)}</strong>
                <span>{weekday(day)}</span>
              </div>
            )}
            <button type="button" className="secondary icon-square" aria-label="Previous day" onClick={() => day && goToDay(addDays(day, -1))} disabled={!day}>
              <ChevronLeft size={20} aria-hidden="true" />
            </button>
            <button type="button" className="secondary icon-square" aria-label="Next day" onClick={() => day && goToDay(addDays(day, 1))} disabled={!day}>
              <ChevronRight size={20} aria-hidden="true" />
            </button>
            <button type="button" className="secondary view-schedule" onClick={() => navigate("/schedule")}>
              <CalendarDays size={18} aria-hidden="true" /> View Schedule
            </button>
          </div>
        </div>

        {error ? (
          <div role="alert" className="appt-error">
            <p>{error}</p>
            <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </button>
          </div>
        ) : loading && !data ? (
          <div role="status" aria-label="Loading appointments">
            {[0, 1, 2].map((i) => (
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
              No appointments match your search or status filter.
            </EmptyState>
          ) : (
            <EmptyState icon={CalendarDays}>{EMPTY[view]}</EmptyState>
          )
        ) : (
          <>
            <div className="appt-table-wrap">
              <table className="appt-table">
                <thead>
                  <tr>
                    <th scope="col">Time</th>
                    <th scope="col">Patient</th>
                    <th scope="col">Reason / Type</th>
                    <th scope="col">Status</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((a) => (
                    <Row key={a.id} appointment={a} showDate={view !== "day"} isNext={a.id === nextId} onAction={onAction} />
                  ))}
                </tbody>
              </table>
            </div>
            <NumberedPager page={page} pageSize={DOCTOR_PAGE_SIZE} total={data.total} noun="appointments" onChange={(p) => update({ page: p })} />
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
            {pending.appointment.patient.name},{" "}
            {formatSlotTime(pending.appointment.starts_at, pending.appointment.timezone)}.
            {pending.status === "cancelled" && " The patient's slot becomes free for others to book."}
          </p>
          {pending.status === "cancelled" && (
            <label className="edit-field">
              Reason
              <select value={cancelReason} onChange={(e) => setCancelReason(e.target.value)}>
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
