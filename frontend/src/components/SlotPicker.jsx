import { useEffect, useState } from "react";
import { getErrorMessage } from "../services/api";
import { getAvailability } from "../services/scheduleService";
import { addDays, formatDayHeading, formatTime, isoDateIn } from "../utils/datetime";
import Alert from "./Alert";

const DAYS = 7;

/**
 * A week of free slots for one doctor, grouped by the clinic's local date.
 * Free slots come from the API (templates − leave − existing bookings); the
 * server re-checks the chosen slot when the booking is submitted.
 */
export default function SlotPicker({ doctorId, selected, onSelect }) {
  const [start, setStart] = useState(() => isoDateIn(new Date()));
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!doctorId) return;
    let cancelled = false;
    getAvailability(doctorId, start, addDays(start, DAYS - 1))
      .then((res) => {
        if (!cancelled) {
          setData(res.data);
          setError("");
        }
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err, "Could not load availability")));
    return () => {
      cancelled = true;
    };
  }, [doctorId, start]);

  if (!doctorId) return <p className="muted">Choose a doctor to see free times.</p>;

  const byDay = {};
  for (let i = 0; i < DAYS; i++) byDay[addDays(start, i)] = [];
  for (const slot of data?.slots ?? []) {
    const day = isoDateIn(slot.starts_at, data.timezone);
    if (byDay[day]) byDay[day].push(slot);
  }
  const today = isoDateIn(new Date());

  return (
    <div className="card">
      <div className="spread">
        <button type="button" className="secondary" disabled={start <= today} onClick={() => setStart(addDays(start, -DAYS))}>
          ← Earlier
        </button>
        <span className="muted small">Times shown in {data?.timezone ?? "clinic time"}</span>
        <button type="button" className="secondary" onClick={() => setStart(addDays(start, DAYS))}>
          Later →
        </button>
      </div>
      <Alert>{error}</Alert>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))", marginTop: "0.75rem" }}>
        {Object.entries(byDay).map(([day, slots]) => (
          <div key={day}>
            <strong className="small">{formatDayHeading(day)}</strong>
            <div className="stack" style={{ gap: "0.3rem", marginTop: "0.3rem" }}>
              {slots.length === 0 && <span className="muted small">—</span>}
              {slots.map((slot) => (
                <button
                  type="button"
                  key={slot.starts_at}
                  className={selected?.starts_at === slot.starts_at ? "" : "secondary"}
                  onClick={() => onSelect({ ...slot, timezone: data.timezone })}
                >
                  {formatTime(slot.starts_at, data.timezone)}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
