import { Ticket } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../context/useAuth";
import { getErrorMessage } from "../../services/api";
import { registerWalkIn } from "../../services/queueService";
import { formatCalendarDate } from "../../utils/datetime";
import Alert from "../Alert";

/**
 * For a doctor who sees patients in arrival order (D117): instead of a time,
 * the patient asks for a token for a day, then checks in at reception on
 * arrival. No time is promised.
 */
export default function TokenRequest({ doctorId, today, lastDay }) {
  const { can } = useAuth();
  const [date, setDate] = useState(today);
  const [token, setToken] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (can("appointment:check_in")) {
    return (
      <p className="muted">
        This doctor sees patients in arrival order. Register walk-ins from the queue on the <Link to="/appointments">Appointments</Link> page.
      </p>
    );
  }
  if (token) {
    return (
      <div className="token-result" role="status">
        <span className="queue-token big">#{token.token_number}</span>
        <p>
          Your token for {formatCalendarDate(token.session_date)} is <strong>#{token.token_number}</strong>. Check in at reception
          when you arrive: patients are seen in the order they check in, so there is no fixed time. Your place and an estimated
          wait appear on your Appointments page.
        </p>
      </div>
    );
  }
  const request = async () => {
    setBusy(true);
    setError("");
    try {
      setToken((await registerWalkIn({ doctor_id: doctorId, session_date: date })).data);
    } catch (err) {
      setError(getErrorMessage(err, "A token could not be issued. Please try again."));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="token-request">
      <p className="muted">This doctor sees patients in arrival order: ask for a token for the day you want to come.</p>
      <label className="field">
        Day
        <input type="date" value={date} min={today} max={lastDay} onChange={(e) => setDate(e.target.value)} />
      </label>
      <Alert>{error}</Alert>
      <button type="button" disabled={busy || !date} onClick={request}>
        <Ticket size={17} aria-hidden="true" /> {busy ? "Requesting…" : "Get a token"}
      </button>
    </div>
  );
}
