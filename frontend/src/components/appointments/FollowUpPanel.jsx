import { CalendarClock } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useFetch } from "../../hooks/useFetch";
import { getErrorMessage } from "../../services/api";
import { dismissFollowUp, getFollowUp, saveFollowUp } from "../../services/appointmentService";
import { formatCalendarDate } from "../../utils/datetime";

const tomorrow = () => {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
};

/**
 * A follow-up visit due by a date (D108). The doctor or the clinic records it
 * (a date only); the patient sees it is due and not booked, and can book it
 * or dismiss it. Nothing is shown when there is none and the caller cannot add one.
 */
export default function FollowUpPanel({ appointmentId, doctorId }) {
  const [version, setVersion] = useState(0);
  const state = useFetch(() => getFollowUp(appointmentId), [appointmentId], { query: "appointments/follow-up", refresh: version });
  const [date, setDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const followUp = state.data?.follow_up ?? null;
  const canManage = Boolean(state.data?.can_manage);
  if (state.loading || state.error || (!followUp && !canManage)) return null;

  const run = async (action) => {
    setBusy(true);
    setError("");
    try {
      await action();
      setDate("");
      setVersion((n) => n + 1);
    } catch (err) {
      setError(getErrorMessage(err, "Could not save the follow-up"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="follow-up" aria-labelledby="follow-up-heading">
      <h4 id="follow-up-heading">
        <CalendarClock size={17} aria-hidden="true" /> Follow-up visit
      </h4>
      {followUp ? (
        <p>
          Due by <strong>{formatCalendarDate(followUp.due_date)}</strong>. <span className="muted">Not booked yet.</span>
        </p>
      ) : (
        <p className="muted">No follow-up recorded.</p>
      )}
      {canManage ? (
        <form
          className="follow-up-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (date) run(() => saveFollowUp(appointmentId, date));
          }}
        >
          <label>
            <span className="sr-only">Follow-up due by</span>
            <input type="date" min={tomorrow()} value={date} onChange={(e) => setDate(e.target.value)} required />
          </label>
          <button type="submit" className="secondary small-button" disabled={busy || !date}>
            {followUp ? "Change date" : "Record follow-up"}
          </button>
          {followUp && (
            <button type="button" className="link-button" disabled={busy} onClick={() => run(() => dismissFollowUp(followUp.id))}>
              Remove
            </button>
          )}
        </form>
      ) : (
        <div className="follow-up-form">
          <Link className="button small-button" to={`/appointments/book?doctor=${followUp.doctor_id ?? doctorId}`}>
            Book follow-up
          </Link>
          <button type="button" className="link-button" disabled={busy} onClick={() => run(() => dismissFollowUp(followUp.id))}>
            Dismiss
          </button>
        </div>
      )}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
