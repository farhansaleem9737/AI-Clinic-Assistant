import { Ban, CalendarCheck, CalendarDays, CalendarPlus, Plus } from "lucide-react";
import { formatMonthDay, formatWallTime, weekdayName } from "../../utils/datetime";
import ActionMenu from "../ActionMenu";
import EmptyState from "../EmptyState";

const TYPES = {
  unavailable: { label: "Unavailable", tone: "danger", icon: Ban },
  custom_hours: { label: "Custom Hours", tone: "ok", icon: CalendarCheck },
  extra_hours: { label: "Extra Hours", tone: "info", icon: CalendarPlus },
};

function hours(exception) {
  if (!exception.start_time) return null;
  return `${formatWallTime(exception.start_time)} – ${formatWallTime(exception.end_time)}`;
}

function ExceptionItem({ exception, onEdit, onDelete }) {
  const type = TYPES[exception.type];
  const Icon = type.icon;
  const multiDay = exception.end_date !== exception.date;
  const dateLabel = multiDay
    ? `${formatMonthDay(exception.date)} – ${formatMonthDay(exception.end_date)}`
    : formatMonthDay(exception.date);
  const items = [
    exception.editable && { label: "Edit Exception", onSelect: () => onEdit(exception) },
    { label: "Delete Exception", onSelect: () => onDelete(exception), danger: true },
  ].filter(Boolean);

  return (
    <li className="exception-item">
      <span className={`exception-icon ${type.tone}`} aria-hidden="true">
        <Icon size={24} />
      </span>
      <div className="exception-main">
        <strong className="exception-date">{dateLabel}</strong>
        <span className="muted">
          {multiDay ? `${weekdayName(exception.date)} – ${weekdayName(exception.end_date)}` : weekdayName(exception.date)}
        </span>
        {exception.reason && <span className="exception-reason">{exception.reason}</span>}
      </div>
      <div className="exception-side">
        <span className={`badge ${type.tone}`}>{type.label}</span>
        {hours(exception) && <span className="exception-hours">{hours(exception)}</span>}
      </div>
      <ActionMenu label={`Actions for ${dateLabel}`} items={items} />
    </li>
  );
}

/** Dates that differ from the weekly hours, from today on. */
export default function ExceptionsCard({ exceptions, loading, error, onRetry, onAdd, onEdit, onDelete }) {
  return (
    <section className="card schedule-card exceptions-card" aria-labelledby="exceptions-title" id="schedule-exceptions">
      <div className="schedule-card-head">
        <CalendarDays className="schedule-card-icon" size={30} aria-hidden="true" />
        <div>
          <h2 id="exceptions-title" tabIndex={-1}>
            Exceptions
          </h2>
          <p className="muted">Set specific dates with different hours or mark days as unavailable.</p>
        </div>
        <button type="button" className="add-exception" onClick={onAdd}>
          <Plus size={18} aria-hidden="true" /> Add Exception
        </button>
      </div>

      {loading ? (
        <div role="status" aria-label="Loading exceptions">
          <div className="skeleton exception-skeleton" />
          <div className="skeleton exception-skeleton" />
        </div>
      ) : error ? (
        <div role="alert" className="exceptions-error">
          <p>{error}</p>
          <button type="button" className="secondary" onClick={onRetry}>
            Try again
          </button>
        </div>
      ) : exceptions.length === 0 ? (
        <EmptyState icon={CalendarDays}>
          No upcoming exceptions. Add one for leave, a holiday or different hours on a specific date.
        </EmptyState>
      ) : (
        <ul className="exception-list">
          {exceptions.map((exception) => (
            <ExceptionItem key={exception.id} exception={exception} onEdit={onEdit} onDelete={onDelete} />
          ))}
        </ul>
      )}
    </section>
  );
}
