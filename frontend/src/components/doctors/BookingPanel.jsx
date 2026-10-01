import { CalendarPlus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/useAuth";
import { useFetch } from "../../hooks/useFetch";
import { getPublicAvailability } from "../../services/doctorService";
import { addMonths, longDate, monthBounds, monthLabel } from "../../utils/calendar";
import { formatDateTime, formatTime, isoDateIn } from "../../utils/datetime";
import { doctorName } from "../../utils/format";
import Alert from "../Alert";
import BookingCalendar from "./BookingCalendar";

/**
 * "Book an Appointment" on the doctor profile: pick a date, then a time,
 * then continue to the confirmation step. Every date and time shown comes
 * from the API; nothing is booked here, and the booking itself re-checks
 * that the time is still free.
 */
export default function BookingPanel({ doctor, headingRef }) {
  const { user, can } = useAuth();
  const navigate = useNavigate();
  const mayBook = !user || can("appointment:create") || can("appointment:create_own");
  const name = doctorName(doctor);

  const [month, setMonth] = useState(() => isoDateIn(new Date()).slice(0, 7));
  const [picked, setPicked] = useState({ date: null, slot: null });
  const [attempt, setAttempt] = useState(0); // bumped by "Try again"

  const { first, last } = monthBounds(month);
  const { data, loading, error } = useFetch(() => getPublicAvailability(doctor.id, first, last), [doctor.id, first, attempt]);
  const current = loading ? null : data; // never show another month's times while loading

  const timezone = current?.timezone;
  const days = Object.fromEntries((current?.days ?? []).map((d) => [d.date, d.slots]));
  const counts = Object.fromEntries(Object.entries(days).map(([date, slots]) => [date, slots.length]));
  // The chosen date if it has times this month, otherwise the first date that does.
  const date = picked.date && days[picked.date] ? picked.date : (current?.days[0]?.date ?? null);
  const slots = date ? days[date] : [];
  const slot = slots.find((s) => s.starts_at === picked.slot) ?? null;

  const today = isoDateIn(new Date(), timezone);
  const canGoBack = month > today.slice(0, 7);
  const canGoForward = !current?.bookable_until || month < current.bookable_until.slice(0, 7);
  const emptyMonth = current && current.days.length === 0;

  const changeMonth = (next) => {
    setMonth(next);
    setPicked({ date: null, slot: null });
  };
  const book = () => navigate(`/appointments/book?${new URLSearchParams({ doctor: doctor.id, slot: slot.starts_at })}`);

  return (
    <section className="card booking-panel" id="book" aria-labelledby="book-heading">
      <h2 id="book-heading" ref={headingRef} tabIndex={-1}>
        Book an Appointment
      </h2>
      <p className="muted">Select a date and time to book an appointment with {name}.</p>

      {error ? (
        <div className="booking-error">
          <Alert>{error}</Alert>
          <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </div>
      ) : (
        <>
          <BookingCalendar
            month={month}
            today={today}
            available={counts}
            selected={date}
            canGoBack={canGoBack}
            canGoForward={canGoForward}
            onMonthChange={changeMonth}
            onSelect={(d) => setPicked({ date: d, slot: null })}
          />

          <div className="booking-times">
            <h3>Available times</h3>
            {loading ? (
              <p className="muted small" role="status">
                Loading available times…
              </p>
            ) : emptyMonth ? (
              <div className="booking-empty">
                <p className="muted">No appointment times are available in {monthLabel(month)}.</p>
                {canGoForward && (
                  <button type="button" className="secondary" onClick={() => changeMonth(addMonths(month, 1))}>
                    Show {monthLabel(addMonths(month, 1))}
                  </button>
                )}
              </div>
            ) : slots.length === 0 ? (
              <p className="muted">No appointment times are available for this date.</p>
            ) : (
              <>
                <p className="muted small">{longDate(date)}</p>
                <div className="slot-grid" role="group" aria-label={`Available times on ${longDate(date)}`}>
                  {slots.map((s) => (
                    <button
                      type="button"
                      key={s.starts_at}
                      className={s.starts_at === slot?.starts_at ? "selected" : "secondary"}
                      aria-pressed={s.starts_at === slot?.starts_at}
                      onClick={() => setPicked({ date, slot: s.starts_at })}
                    >
                      {formatTime(s.starts_at, timezone)}
                    </button>
                  ))}
                </div>
                <p className="muted small">Times are in the clinic's time zone ({timezone}).</p>
              </>
            )}
          </div>
        </>
      )}

      <div className="booking-footer">
        {mayBook ? (
          <>
            <button type="button" className="large" disabled={!slot} onClick={book}>
              <CalendarPlus size={18} aria-hidden="true" /> Book appointment
            </button>
            <p className="muted small" aria-live="polite">
              {slot && (
                <>
                  Selected: <strong>{formatDateTime(slot.starts_at, timezone)}</strong>.{" "}
                </>
              )}
              You will be able to confirm your appointment details on the next step.
              {!user && " You will be asked to sign in or create an account first."}
            </p>
          </>
        ) : (
          <p className="muted small">Online booking is available to patients.</p>
        )}
      </div>
    </section>
  );
}
