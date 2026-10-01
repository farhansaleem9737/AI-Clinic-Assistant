import { ArrowRight, CalendarPlus, CalendarX, Clock, FileText, MapPin, RotateCcw, Search, SearchX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import ActionMenu from "../components/ActionMenu";
import Alert from "../components/Alert";
import Avatar from "../components/Avatar";
import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import Pagination from "../components/Pagination";
import StatusBadge from "../components/StatusBadge";
import { useFetch } from "../hooks/useFetch";
import { getErrorMessage } from "../services/api";
import { changeAppointmentStatus, countAppointments, listAppointments } from "../services/appointmentService";
import {
  EMPTY_FILTERS,
  filterParams,
  hasFilters,
  listParams,
  listSearchParams,
  PAGE_SIZE,
  rangeIsValid,
  readListState,
  TABS,
} from "../utils/appointmentList";
import { STATUS_LABELS } from "../utils/appointments";
import { dayParts, formatDateTime, formatTime } from "../utils/datetime";
import { doctorName } from "../utils/format";

const SEARCH_DELAY_MS = 350;

const EMPTY_TEXT = {
  upcoming: "No upcoming appointments.",
  past: "No past appointments yet.",
  all: "You have no appointments yet.",
};

function AppointmentCard({ appointment: a, onCancel, onConfirm }) {
  const day = dayParts(a.starts_at, a.timezone);
  const name = doctorName(a.doctor);
  const when = formatDateTime(a.starts_at, a.timezone);
  const actions = [
    a.allowed_transitions.includes("confirmed") && { label: "Confirm attendance", onSelect: () => onConfirm(a) },
    a.can_reschedule && { label: "Reschedule", to: `/appointments/${a.id}?reschedule=1` },
    a.allowed_transitions.includes("cancelled") && { label: "Cancel appointment", onSelect: () => onCancel(a), danger: true },
  ].filter(Boolean);

  return (
    <article className="card appt-card" aria-label={`${name}, ${when}`}>
      <span className="day" aria-hidden="true">
        <span className="month">{day.month}</span>
        <span className="num">{day.day}</span>
        <span className="dow">{day.weekday}</span>
      </span>
      <div className="appt-card-doctor">
        <Avatar name={a.doctor.name} role="doctor" size={72} />
        <div>
          <h3>{name}</h3>
          <p>{a.doctor.specialization}</p>
          <p className="muted">{a.doctor.department_name}</p>
        </div>
      </div>
      <ul className="appt-card-facts">
        {a.reason && (
          <li>
            <FileText size={17} aria-hidden="true" />
            <span className="reason">{a.reason}</span>
          </li>
        )}
        <li>
          <Clock size={17} aria-hidden="true" />
          <time dateTime={a.starts_at}>{formatTime(a.starts_at, a.timezone)}</time>
        </li>
        {a.doctor.room_number && (
          <li>
            <MapPin size={17} aria-hidden="true" />
            Room {a.doctor.room_number}
          </li>
        )}
      </ul>
      <div className="appt-card-side">
        <StatusBadge status={a.status} icon />
        <Link to={`/appointments/${a.id}`} className="button secondary small">
          View details<span className="sr-only">: {name}, {when}</span>
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </div>
      <div className="appt-card-menu">
        {actions.length > 0 && <ActionMenu label={`Actions for the appointment with ${name}, ${when}`} items={actions} />}
      </div>
    </article>
  );
}

/**
 * The patient's appointments: Upcoming / Past / All tabs with real counts,
 * search, status and date filters, paging, and the actions the API says this
 * patient may take on each appointment. The URL holds the state.
 */
export default function PatientAppointments() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = readListState(searchParams);
  const { tab, filters, page } = state;
  // Changes always build on the latest URL, so a delayed search update can
  // never undo something changed in the meantime.
  const latest = useRef(searchParams);
  useEffect(() => {
    latest.current = searchParams;
  }, [searchParams]);
  const update = (changes) => setSearchParams(listSearchParams({ ...readListState(latest.current), ...changes }));
  const setFilters = (changes) => {
    const current = readListState(latest.current);
    update({ filters: { ...current.filters, ...changes }, page: 1 });
  };

  // What is being typed (search text, dates) lives here until it is ready to
  // go into the URL; it follows the URL when that changes from outside
  // (back button, Clear filters).
  const typed = { q: filters.q, from: filters.from, to: filters.to };
  const [drafts, setDrafts] = useState(typed);
  const [synced, setSynced] = useState(typed);
  if (typed.q !== synced.q || typed.from !== synced.from || typed.to !== synced.to) {
    setSynced(typed);
    setDrafts(typed);
  }
  const searchTimer = useRef(null);
  useEffect(() => () => clearTimeout(searchTimer.current), []);
  const onSearch = (value) => {
    setDrafts((d) => ({ ...d, q: value }));
    clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => setFilters({ q: value }), SEARCH_DELAY_MS);
  };
  // A date is applied once it is complete (typing a year passes through 0002, 0020…).
  const onDate = (key, value) => {
    setDrafts((d) => ({ ...d, [key]: value }));
    if (!value || Number(value.slice(0, 4)) >= 1900) setFilters({ [key]: value });
  };
  const clearFilters = () => {
    clearTimeout(searchTimer.current);
    setDrafts({ q: "", from: "", to: "" });
    update({ filters: EMPTY_FILTERS, page: 1 });
  };

  const [attempt, setAttempt] = useState(0); // "Try again", and after an action
  const valid = rangeIsValid(filters);
  const apiList = listParams(state);
  const apiCounts = filterParams(filters);
  const list = useFetch(() => listAppointments(apiList), [JSON.stringify(apiList), attempt], { enabled: valid });
  const counts = useFetch(() => countAppointments(apiCounts), [JSON.stringify(apiCounts), attempt], { enabled: valid });

  const [notice, setNotice] = useState("");
  const [cancelling, setCancelling] = useState(null); // { appointment, note, busy, error }
  const [actionError, setActionError] = useState("");

  const refresh = () => setAttempt((n) => n + 1);
  const confirmAttendance = async (a) => {
    setNotice("");
    setActionError("");
    try {
      await changeAppointmentStatus(a.id, { status: "confirmed" });
      setNotice("Thank you, your attendance is confirmed.");
      refresh();
    } catch (err) {
      setActionError(getErrorMessage(err, "Could not confirm the appointment"));
    }
  };
  const cancel = async () => {
    setCancelling((c) => ({ ...c, busy: true, error: "" }));
    try {
      await changeAppointmentStatus(cancelling.appointment.id, {
        status: "cancelled",
        cancellation_reason: "patient_request",
        note: cancelling.note.trim() || null,
      });
      setCancelling(null);
      setNotice("Your appointment has been cancelled.");
      refresh();
    } catch (err) {
      setCancelling((c) => ({ ...c, busy: false, error: getErrorMessage(err, "Could not cancel the appointment") }));
    }
  };

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const first = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const last = Math.min(page * PAGE_SIZE, total);

  const onTabKey = (e) => {
    const index = TABS.findIndex((t) => t.id === tab);
    const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: TABS.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    const target = TABS[(next + TABS.length) % TABS.length];
    update({ tab: target.id, page: 1 });
    document.getElementById(`tab-${target.id}`)?.focus();
  };

  return (
    <div className="appointments-page">
      <div className="page-head">
        <div>
          <h1>Appointments</h1>
          <p className="muted">View and manage your appointments.</p>
        </div>
        <Link to="/doctors" className="button large">
          <CalendarPlus size={19} aria-hidden="true" /> Book Appointment
        </Link>
      </div>

      <div className="card tab-strip" role="tablist" aria-label="Appointments" onKeyDown={onTabKey}>
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="appointment-results"
            tabIndex={tab === t.id ? 0 : -1}
            className={tab === t.id ? "active" : ""}
            onClick={() => update({ tab: t.id, page: 1 })}
          >
            {t.label}
            {counts.data && ` (${counts.data[t.id]})`}
          </button>
        ))}
      </div>

      <form className="card appt-filters" role="search" aria-label="Filter appointments" onSubmit={(e) => e.preventDefault()}>
        <div className="input-icon appt-search">
          <Search size={19} aria-hidden="true" />
          <input
            type="search"
            aria-label="Search by doctor name or specialization"
            placeholder="Search by doctor name or specialization…"
            value={drafts.q}
            maxLength={100}
            onChange={(e) => onSearch(e.target.value)}
          />
        </div>
        <label>
          Status
          <select value={filters.status} onChange={(e) => setFilters({ status: e.target.value })}>
            <option value="">All Statuses</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="date-range">
          <legend>Date range</legend>
          <input
            type="date"
            aria-label="From date"
            value={drafts.from}
            max={filters.to || undefined}
            onChange={(e) => onDate("from", e.target.value)}
          />
          <span aria-hidden="true">–</span>
          <input
            type="date"
            aria-label="To date"
            value={drafts.to}
            min={filters.from || undefined}
            onChange={(e) => onDate("to", e.target.value)}
          />
        </fieldset>
        <button
          type="button"
          className="secondary"
          disabled={!hasFilters(filters) && !drafts.q}
          onClick={clearFilters}
        >
          <RotateCcw size={17} aria-hidden="true" /> Clear filters
        </button>
      </form>

      <Alert kind="success">{notice}</Alert>
      <Alert>{actionError}</Alert>

      <div id="appointment-results" role="tabpanel" aria-labelledby={`tab-${tab}`} aria-busy={list.loading}>
        {!valid ? (
          <Alert>The start date must be on or before the end date.</Alert>
        ) : list.error ? (
          <div className="card">
            <Alert>{list.error}</Alert>
            <button type="button" onClick={refresh}>
              Try again
            </button>
          </div>
        ) : list.loading && items.length === 0 ? (
          <div role="status" aria-label="Loading appointments">
            {[0, 1, 2].map((i) => (
              <div key={i} className="card skeleton appt-skeleton" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="card">
            {hasFilters(filters) ? (
              <EmptyState
                icon={SearchX}
                action={
                  <button type="button" className="secondary" onClick={clearFilters}>
                    Clear filters
                  </button>
                }
              >
                No appointments match your filters.
              </EmptyState>
            ) : (
              <EmptyState
                icon={CalendarX}
                action={
                  tab !== "past" && (
                    <Link to="/doctors" className="button">
                      <CalendarPlus size={17} aria-hidden="true" /> Book Appointment
                    </Link>
                  )
                }
              >
                {EMPTY_TEXT[tab]}
              </EmptyState>
            )}
          </div>
        ) : (
          items.map((a) => (
            <AppointmentCard
              key={a.id}
              appointment={a}
              onConfirm={confirmAttendance}
              onCancel={(appointment) => setCancelling({ appointment, note: "", busy: false, error: "" })}
            />
          ))
        )}
      </div>

      {valid && !list.error && total > 0 && (
        <div className="list-footer">
          <p className="muted" aria-live="polite">
            Showing {first} to {last} of {total} {total === 1 ? "appointment" : "appointments"}
          </p>
          <Pagination page={page} totalPages={list.data.total_pages} onChange={(p) => update({ page: p })} />
        </div>
      )}

      {cancelling && (
        <ConfirmDialog
          title="Cancel this appointment?"
          confirmLabel="Cancel appointment"
          cancelLabel="Keep appointment"
          danger
          busy={cancelling.busy}
          error={cancelling.error}
          onConfirm={cancel}
          onCancel={() => setCancelling(null)}
        >
          <p>
            {doctorName(cancelling.appointment.doctor)} on{" "}
            <strong>{formatDateTime(cancelling.appointment.starts_at, cancelling.appointment.timezone)}</strong>. The time
            will be released for other patients.
          </p>
          <label>
            Note for the clinic (optional)
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
