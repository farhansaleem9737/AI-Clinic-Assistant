import { CalendarSearch, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useFetch } from "../../hooks/useFetch";
import { previewSchedulingPolicy } from "../../services/queueService";
import { addDays, formatLongDate, formatSlotTime, isoDateIn } from "../../utils/datetime";
import Alert from "../Alert";

const STATUS_TEXT = { free: "free", booked: "booked", past: "already past" };

/**
 * What a length and buffer would give (D120): the real times of one date from
 * the booking engine (weekly hours, breaks, leave, existing bookings), its
 * booked and free capacity, and upcoming bookings that would not fit. Nothing
 * is saved; existing appointments are never moved.
 */
export default function PolicyPreview({ doctorId, minutes, buffer, timezone }) {
  const [day, setDay] = useState(() => addDays(isoDateIn(new Date(), timezone), 1));
  const valid = Number.isInteger(minutes) && Number.isInteger(buffer) && minutes >= 5 && buffer >= 0;
  const { data, loading, error } = useFetch(
    () => previewSchedulingPolicy(doctorId, { date: day, consultation_minutes: minutes, buffer_minutes: buffer }),
    [doctorId, day, minutes, buffer],
    { enabled: valid && Boolean(day) }
  );
  const preview = loading ? null : data;
  const tz = preview?.timezone ?? timezone;

  return (
    <section className="policy-preview" aria-labelledby="policy-preview-title">
      <div className="policy-preview-head">
        <h3 id="policy-preview-title">
          <CalendarSearch size={18} aria-hidden="true" /> Preview
        </h3>
        <label className="policy-preview-date">
          <span>Date</span>
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        </label>
      </div>
      {!valid ? (
        <p className="muted small">Enter a length and buffer to see the times.</p>
      ) : error ? (
        <Alert>{error}</Alert>
      ) : !preview ? (
        <p className="muted small" role="status">
          Working out the times…
        </p>
      ) : preview.slots.length === 0 ? (
        <p className="muted small">No working hours on {formatLongDate(`${day}T12:00:00Z`, "UTC")}.</p>
      ) : (
        <>
          <p className="small">
            <strong>{preview.slots.length}</strong> appointment times ·{" "}
            <strong>{preview.free_count}</strong> free · <strong>{preview.booked_count}</strong> booked
            <span className="muted"> · working {preview.working_hours.map(([a, b]) => `${a}–${b}`).join(", ")}</span>
          </p>
          <ul className="policy-preview-slots" aria-label={`Appointment times on ${day}`}>
            {preview.slots.map((s) => (
              <li key={s.starts_at} className={`preview-slot ${s.status}`} aria-label={`${formatSlotTime(s.starts_at, tz)}, ${STATUS_TEXT[s.status]}`}>
                {formatSlotTime(s.starts_at, tz)}
              </li>
            ))}
          </ul>
          <p className="muted small">Gaps are breaks, leave or blocked time. Taken times stay taken whatever the length.</p>
        </>
      )}
      {preview?.affected_count > 0 && (
        <div className="policy-affected" role="note">
          <p>
            <TriangleAlert size={18} aria-hidden="true" />
            <span>
              {preview.affected_count} upcoming appointment{preview.affected_count === 1 ? "" : "s"} do not match this length.
              They keep their booked times; saving will ask you to confirm that.
            </span>
          </p>
          <AffectedList items={preview.affected} total={preview.affected_count} timezone={tz} />
        </div>
      )}
    </section>
  );
}

export function AffectedList({ items, total, timezone }) {
  return (
    <ul className="policy-affected-list">
      {items.map((a) => (
        <li key={a.id}>
          <Link to={`/appointments/${a.id}`}>
            {formatLongDate(a.starts_at, timezone)}, {formatSlotTime(a.starts_at, timezone)}
          </Link>{" "}
          <span className="muted small">({a.duration_minutes} min)</span>
        </li>
      ))}
      {total > items.length && <li className="muted small">and {total - items.length} more</li>}
    </ul>
  );
}
