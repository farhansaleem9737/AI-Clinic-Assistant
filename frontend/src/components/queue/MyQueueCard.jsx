import { Ticket } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useRealtimeEvent } from "../../hooks/useRealtime";
import { getErrorMessage } from "../../services/api";
import realtime from "../../services/realtime";
import { getMyQueue, queueAction } from "../../services/queueService";
import { formatCalendarDate, formatTime, isoDateIn } from "../../utils/datetime";
import { waitText } from "../../utils/queue";
import Alert from "../Alert";

const STATE_TEXT = {
  registered: "Token issued: check in at reception when you arrive.",
  waiting: "Checked in: please wait to be called.",
  called: "You have been called: please go in now.",
  in_consultation: "In consultation.",
  absent: "You were called but not here: check in at reception again.",
};

/**
 * The patient's own tokens (D117): their token, place and an estimated wait.
 * The booked time is the reserved time; the estimate is only an estimate.
 * Nothing about other patients is shown (the API never sends it).
 */
export default function MyQueueCard() {
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(
    () =>
      getMyQueue()
        .then((res) => setEntries(res.data))
        .catch((err) => setError(getErrorMessage(err, "Your queue status could not be loaded."))),
    []
  );
  useEffect(() => {
    load();
    const timer = setInterval(() => !realtime.connected && load(), 60000);
    return () => clearInterval(timer);
  }, [load]);
  // Live (D122): my own token changed (it carries an id only for me), or the
  // queue I am waiting in moved, or a reconnect.
  useRealtimeEvent(["queue."], (event) => {
    const mine = event.resource_id || !event.payload;
    if (mine || entries?.some((e) => e.doctor_id === event.payload.doctor_id)) load();
  });

  if (!entries?.length && !error) return null;
  return (
    <section className="card my-queue" aria-labelledby="my-queue-title">
      <h2 id="my-queue-title">
        <Ticket size={20} aria-hidden="true" /> Your queue tokens
      </h2>
      <Alert>{error}</Alert>
      <ul>
        {(entries ?? []).map((e) => {
          const today = e.session_date === isoDateIn(new Date(), e.timezone);
          return (
            <li key={e.id} className="my-queue-item">
              <span className="queue-token big">#{e.token_number}</span>
              <div>
                <strong>{e.doctor_name}</strong>
                <p className="muted small">
                  {today ? "Today" : formatCalendarDate(e.session_date)}
                  {e.scheduled_at && ` · booked time ${formatTime(e.scheduled_at, e.timezone)}`}
                  {e.kind === "walk_in" && " · walk-in, seen in arrival order"}
                </p>
                <p className="small">{STATE_TEXT[e.state]}</p>
                {e.position && (
                  <p className="small">
                    Place in queue: <strong>{e.position}</strong>. {waitText(e.estimated_wait)} — consultations vary, so this is not a
                    fixed time.
                  </p>
                )}
                {e.kind === "walk_in" && ["registered", "waiting", "absent"].includes(e.state) && (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => queueAction(e.id, "cancel").then(load).catch((err) => setError(getErrorMessage(err, "The token could not be cancelled.")))}
                  >
                    Cancel this token
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
