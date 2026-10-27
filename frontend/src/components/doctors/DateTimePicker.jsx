import { CalendarDays, Clock, Info } from "lucide-react";
import { useEffect, useState } from "react";
import { useFetch } from "../../hooks/useFetch";
import { getPublicAvailability } from "../../services/doctorService";
import { addMonths, longDate, monthBounds, monthLabel } from "../../utils/calendar";
import { formatSlotTime, isoDateIn, timeZoneLabel } from "../../utils/datetime";
import Alert from "../Alert";
import BookingCalendar from "./BookingCalendar";

/**
 * Pick a date, then a free time, for one doctor. Every date and time comes
 * from the API (working hours − leave − bookings, booking notice applied);
 * nothing is reserved here, and the booking re-checks the time.
 *
 * `selected` is the chosen slot ({ starts_at, ends_at, timezone }) or null;
 * `onSelect` receives the new one, or null when the choice is cleared (date
 * or month changed, or the time is no longer offered). Bump `refreshKey` to
 * reload the times, e.g. after a booking conflict.
 *
 * `layout="panel"` (default) is the compact doctor-profile panel;
 * `layout="cards"` is the booking wizard's "Select a date" and "Available
 * times" cards. Both show unavailable times greyed out.
 */
export default function DateTimePicker({ doctorId, selected, onSelect, refreshKey = 0, layout = "panel" }) {
  // Open on the already-chosen time (e.g. coming back from the confirm step).
  const initialDate = selected?.timezone ? isoDateIn(selected.starts_at, selected.timezone) : null;
  const [month, setMonth] = useState(() => (initialDate ?? isoDateIn(new Date())).slice(0, 7));
  const [pickedDate, setPickedDate] = useState(initialDate);
  const [attempt, setAttempt] = useState(0); // bumped by "Try again"

  const { first, last } = monthBounds(month);
  const { data, loading, error } = useFetch(
    () => getPublicAvailability(doctorId, first, last),
    [doctorId, first, attempt, refreshKey]
  );
  const current = loading ? null : data; // never show another month's times while loading

  const timezone = current?.timezone;
  const byDate = Object.fromEntries((current?.days ?? []).map((d) => [d.date, d]));
  const counts = Object.fromEntries(Object.values(byDate).map((d) => [d.date, d.slots.length]));
  // The chosen date if it has times this month, otherwise the first date that does.
  const date = pickedDate && byDate[pickedDate] ? pickedDate : (current?.days[0]?.date ?? null);
  const slots = date ? byDate[date].slots : [];
  const slot = slots.find((s) => s.starts_at === selected?.starts_at) ?? null;
  const stale = Boolean(current && selected && !slot);

  // A chosen time that is no longer offered (refreshed, or another date) is cleared.
  useEffect(() => {
    if (stale) onSelect(null);
  }, [stale, onSelect]);

  const today = isoDateIn(new Date(), timezone);
  const canGoBack = month > today.slice(0, 7);
  const canGoForward = !current?.bookable_until || month < current.bookable_until.slice(0, 7);
  const emptyMonth = current && current.days.length === 0;

  const changeMonth = (next) => {
    setMonth(next);
    setPickedDate(null);
    onSelect(null);
  };
  const choose = (s) => {
    setPickedDate(date);
    onSelect({ ...s, timezone });
  };
  const retry = (
    <div className="booking-error">
      <Alert>{error}</Alert>
      <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
        Try again
      </button>
    </div>
  );

  const calendar = (
    <BookingCalendar
      month={month}
      today={today}
      available={counts}
      selected={date}
      canGoBack={canGoBack}
      canGoForward={canGoForward}
      onMonthChange={changeMonth}
      onSelect={(d) => {
        setPickedDate(d);
        onSelect(null);
      }}
    />
  );

  // Free and greyed-out (taken or too soon) times together, in time order.
  const board = date
    ? [
        ...slots.map((s) => ({ ...s, free: true })),
        ...(byDate[date].unavailable ?? []).map((s) => ({ ...s, free: false })),
      ].sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at))
    : [];

  const emptyMonthMessage = (
    <div className="booking-empty">
      <p className="muted">No appointment times are available in {monthLabel(month)}.</p>
      {canGoForward && (
        <button type="button" className="secondary" onClick={() => changeMonth(addMonths(month, 1))}>
          Show {monthLabel(addMonths(month, 1))}
        </button>
      )}
    </div>
  );

  if (layout === "cards") {
    return (
      <div className="datetime-cards">
        <section className="card calendar-card" aria-labelledby="pick-date-title">
          <div className="card-title">
            <CalendarDays className="icon" size={26} aria-hidden="true" />
            <div>
              <h3 id="pick-date-title">Select a date</h3>
              <p className="muted">Choose a date for your appointment.</p>
            </div>
          </div>
          {error ? (
            retry
          ) : (
            <>
              {calendar}
              <ul className="calendar-legend" aria-label="Calendar key">
                <li>
                  <span className="legend-dot selected" aria-hidden="true" /> Selected date
                </li>
                <li>
                  <span className="legend-dot available" aria-hidden="true" /> Available
                </li>
                <li>
                  <span className="legend-dot unavailable" aria-hidden="true" /> Unavailable
                </li>
              </ul>
            </>
          )}
        </section>

        <section className="card times-card" aria-labelledby="pick-time-title">
          <div className="card-title">
            <Clock className="icon" size={26} aria-hidden="true" />
            <div>
              <h3 id="pick-time-title">Available times</h3>
              <p className="muted">
                {date ? (
                  <>
                    Select a time slot for <span className="accent-text">{longDate(date)}</span>.
                  </>
                ) : (
                  "Select a date to see its times."
                )}
              </p>
            </div>
          </div>
          {error ? null : loading ? (
            <p className="muted small" role="status">
              Loading available times…
            </p>
          ) : emptyMonth ? (
            emptyMonthMessage
          ) : board.length === 0 ? (
            <p className="muted">No appointment times are available for this date.</p>
          ) : (
            <div className="time-grid" role="group" aria-label={`Times on ${longDate(date)}`}>
              {board.map((s) =>
                s.free ? (
                  <button
                    type="button"
                    key={s.starts_at}
                    className={s.starts_at === slot?.starts_at ? "time-slot selected" : "time-slot"}
                    aria-pressed={s.starts_at === slot?.starts_at}
                    onClick={() => choose(s)}
                  >
                    {formatSlotTime(s.starts_at, timezone)}
                  </button>
                ) : (
                  <button
                    type="button"
                    key={s.starts_at}
                    className="time-slot"
                    disabled
                    aria-label={`${formatSlotTime(s.starts_at, timezone)}, unavailable`}
                    title="Not available"
                  >
                    {formatSlotTime(s.starts_at, timezone)}
                  </button>
                )
              )}
            </div>
          )}
          {timezone && (
            <p className="timezone-note">
              <Info size={18} aria-hidden="true" />
              <span>
                Selected time zone: {timeZoneLabel(timezone, slot?.starts_at ?? `${date ?? today}T12:00:00Z`)}
                <span className="muted small"> · clinic time</span>
              </span>
            </p>
          )}
        </section>
      </div>
    );
  }

  if (error) return retry;

  return (
    <>
      {calendar}

      <div className="booking-times">
        <h3>
          <Clock size={18} aria-hidden="true" /> Available times
        </h3>
        {loading ? (
          <p className="muted small" role="status">
            Loading available times…
          </p>
        ) : emptyMonth ? (
          emptyMonthMessage
        ) : slots.length === 0 ? (
          <p className="muted">No appointment times are available for this date.</p>
        ) : (
          <>
            <p className="muted small">{longDate(date)}</p>
            <div className="slot-grid" role="group" aria-label={`Available times on ${longDate(date)}`}>
              {board.map((s) =>
                s.free ? (
                  <button
                    type="button"
                    key={s.starts_at}
                    className={s.starts_at === slot?.starts_at ? "selected" : "secondary"}
                    aria-pressed={s.starts_at === slot?.starts_at}
                    onClick={() => choose(s)}
                  >
                    {formatSlotTime(s.starts_at, timezone)}
                  </button>
                ) : (
                  <button
                    type="button"
                    key={s.starts_at}
                    className="secondary unavailable"
                    disabled
                    aria-label={`${formatSlotTime(s.starts_at, timezone)}, unavailable`}
                    title="Not available"
                  >
                    {formatSlotTime(s.starts_at, timezone)}
                  </button>
                )
              )}
            </div>
            <p className="muted small">Times are in the clinic's time zone ({timezone}).</p>
          </>
        )}
      </div>
    </>
  );
}
