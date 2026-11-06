import { CalendarClock, Hourglass, Ticket } from "lucide-react";
import { useEffect } from "react";
import { useFetch } from "../../hooks/useFetch";
import { getNextAvailable } from "../../services/appointmentService";
import { longDate } from "../../utils/calendar";
import { formatSlotTime } from "../../utils/datetime";
import Alert from "../Alert";

/**
 * Automatic token booking (D120): the clinic's earliest free time with this
 * doctor on `date`, assigned by the server from the same engine every booking
 * uses. The time is selected for the user (`onSelect`) so "Continue" works at
 * once; nothing is reserved, and the booking checks it again. If it has been
 * taken meanwhile, the server names the next one and the user reviews it.
 */
export default function AutoTokenPanel({ doctorId, date, patientId, selected, onSelect, onPickDate, refreshKey = 0 }) {
  const { data, loading, error } = useFetch(
    () => getNextAvailable(doctorId, date, patientId),
    [doctorId, date, patientId],
    // Not a shared cache entry: the earliest time changes as people book.
    { refresh: String(refreshKey) }
  );
  const result = loading ? null : data;
  const slot = result?.slot ?? null;

  useEffect(() => {
    if (!result) return;
    if (!slot) {
      if (selected) onSelect(null);
      return;
    }
    if (selected?.starts_at !== slot.starts_at || selected?.mode !== "auto") {
      onSelect({
        starts_at: slot.starts_at,
        ends_at: slot.ends_at,
        timezone: result.timezone,
        mode: "auto",
        queue_position: result.queue_position,
      });
    }
  }, [result, slot, selected, onSelect]);

  if (error) return <Alert>{error}</Alert>;
  if (!result) {
    return (
      <p className="muted small" role="status">
        Finding the next available time…
      </p>
    );
  }
  if (!slot) {
    return (
      <div className="booking-empty">
        <p className="muted">There are no free times on {longDate(date)}.</p>
        {result.next_date && (
          <button type="button" className="secondary" onClick={() => onPickDate(result.next_date)}>
            See {longDate(result.next_date)}
          </button>
        )}
      </div>
    );
  }

  const tz = result.timezone;
  return (
    <div className="auto-token" aria-live="polite">
      <p className="auto-token-label">Your assigned time</p>
      <p className="auto-token-time">
        {formatSlotTime(slot.starts_at, tz)} <span>– {formatSlotTime(slot.ends_at, tz)}</span>
      </p>
      <dl className="auto-token-facts">
        <div>
          <dt>
            <CalendarClock size={18} aria-hidden="true" /> Date
          </dt>
          <dd>{longDate(date)}</dd>
        </div>
        <div>
          <dt>
            <Hourglass size={18} aria-hidden="true" /> Duration
          </dt>
          <dd>About {result.consultation_minutes} minutes</dd>
        </div>
        <div>
          <dt>
            <Ticket size={18} aria-hidden="true" /> Queue no.
          </dt>
          <dd>
            #{result.queue_position} <span className="muted small">(estimated)</span>
          </dd>
        </div>
      </dl>
      <p className="muted small">
        This is the earliest free time that day. It's an estimated start time: you may be seen a little earlier or
        later. Nothing is booked until you confirm.
      </p>
    </div>
  );
}
