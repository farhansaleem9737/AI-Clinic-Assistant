import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import Alert from "../components/Alert";
import SlotPicker from "../components/SlotPicker";
import StatusBadge from "../components/StatusBadge";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import {
  changeAppointmentStatus,
  getAppointment,
  getAppointmentHistory,
  rescheduleAppointment,
  updateAppointment,
} from "../services/appointmentService";
import { ACTION_LABELS, CANCELLATION_REASONS, STATUS_LABELS } from "../utils/appointments";
import { formatDateTime } from "../utils/datetime";
import { doctorName } from "../utils/format";

export default function AppointmentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const [appointment, setAppointment] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");
  const location = useLocation();
  // e.g. "Your appointment is booked." when arriving from the booking page.
  const [notice, setNotice] = useState(location.state?.notice ?? "");
  const [cancelling, setCancelling] = useState(false);
  const [cancel, setCancel] = useState({ cancellation_reason: "patient_request", note: "" });
  const [searchParams] = useSearchParams();
  // "Reschedule" in the appointments list links here with ?reschedule=1.
  const [rescheduling, setRescheduling] = useState(searchParams.get("reschedule") === "1");
  const [newSlot, setNewSlot] = useState(null);
  const [notes, setNotes] = useState("");

  const load = useCallback(() => {
    getAppointment(id)
      .then((res) => {
        setAppointment(res.data);
        setNotes(res.data.staff_notes ?? "");
      })
      .catch((err) => setError(getErrorMessage(err, "Appointment not found")));
    getAppointmentHistory(id)
      .then((res) => setHistory(res.data))
      .catch(() => {});
  }, [id]);

  useEffect(load, [load]);

  const act = async (action, success) => {
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(success);
      setCancelling(false);
      load();
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const doReschedule = async () => {
    setError("");
    try {
      const res = await rescheduleAppointment(id, { starts_at: newSlot.starts_at });
      navigate(`/appointments/${res.data.id}`);
      setRescheduling(false);
      setNewSlot(null);
    } catch (err) {
      setError(getErrorMessage(err));
      setNewSlot(null);
    }
  };

  if (!appointment) return error ? <Alert>{error}</Alert> : <p className="muted">Loading…</p>;
  const a = appointment;
  const tz = a.timezone;
  // The API lists exactly what this user may do now; it re-checks on submit.
  const actions = a.allowed_transitions.filter((s) => s !== "cancelled");

  return (
    <div>
      <p>
        <Link to="/appointments">← Appointments</Link>
      </p>
      <div className="card">
        <div className="spread">
          <h2>{formatDateTime(a.starts_at, tz)}</h2>
          <StatusBadge status={a.status} />
        </div>
        <p>
          {doctorName(a.doctor)} · {a.doctor.specialization} · {a.doctor.department_name}
        </p>
        <p>
          Patient: {a.patient.name} <span className="muted small">({a.patient.mrn})</span>
          {(can("patient:read_any") || can("patient:read_assigned")) && (
            <>
              {" "}
              · <Link to={`/patients/${a.patient.id}`}>record</Link>
            </>
          )}
        </p>
        {a.reason && <p>Reason: {a.reason}</p>}
        {a.status === "cancelled" && (
          <p className="muted">
            Cancelled ({CANCELLATION_REASONS[a.cancellation_reason] ?? a.cancellation_reason})
            {a.cancellation_note ? ` — ${a.cancellation_note}` : ""}
          </p>
        )}
        {a.rescheduled_to_id && (
          <p>
            Moved to <Link to={`/appointments/${a.rescheduled_to_id}`}>the new appointment</Link>.
          </p>
        )}
        {a.rescheduled_from_id && (
          <p className="muted small">
            Rescheduled from <Link to={`/appointments/${a.rescheduled_from_id}`}>an earlier appointment</Link>.
          </p>
        )}
      </div>

      <Alert>{error}</Alert>
      <Alert kind="success">{notice}</Alert>

      {(actions.length > 0 || a.allowed_transitions.includes("cancelled") || a.can_reschedule) && (
        <div className="card row">
          {actions.map((to) => (
            <button key={to} onClick={() => act(() => changeAppointmentStatus(id, { status: to }), `Marked ${STATUS_LABELS[to]}`)}>
              {ACTION_LABELS[to]}
            </button>
          ))}
          {a.can_reschedule && (
            <button className="secondary" onClick={() => setRescheduling(!rescheduling)}>
              Reschedule
            </button>
          )}
          {a.allowed_transitions.includes("cancelled") && (
            <button className="danger" onClick={() => setCancelling(!cancelling)}>
              Cancel appointment
            </button>
          )}
        </div>
      )}

      {cancelling && (
        <div className="card stack">
          <label>
            Reason
            <select value={cancel.cancellation_reason} onChange={(e) => setCancel({ ...cancel, cancellation_reason: e.target.value })}>
              {Object.entries(CANCELLATION_REASONS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Note (optional)
            <input value={cancel.note} onChange={(e) => setCancel({ ...cancel, note: e.target.value })} maxLength={500} />
          </label>
          <button
            className="danger"
            onClick={() =>
              act(
                () => changeAppointmentStatus(id, { status: "cancelled", cancellation_reason: cancel.cancellation_reason, note: cancel.note || null }),
                "Appointment cancelled"
              )
            }
          >
            Confirm cancellation
          </button>
        </div>
      )}

      {rescheduling && a.can_reschedule && (
        <div className="stack" style={{ maxWidth: "none" }}>
          <h3>Pick a new time</h3>
          <SlotPicker doctorId={a.doctor.id} selected={newSlot} onSelect={setNewSlot} />
          <button disabled={!newSlot} onClick={doReschedule}>
            {newSlot ? `Move to ${formatDateTime(newSlot.starts_at, newSlot.timezone)}` : "Select a time"}
          </button>
        </div>
      )}

      {can("appointment:manage") && "staff_notes" in a && (
        <div className="card stack">
          <label>
            Staff notes (not visible to the patient)
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={1000} />
          </label>
          <button onClick={() => act(() => updateAppointment(id, { staff_notes: notes || null }), "Notes saved")}>Save notes</button>
        </div>
      )}
      {!can("appointment:manage") && a.staff_notes && (
        <div className="card">
          <strong>Staff notes:</strong> {a.staff_notes}
        </div>
      )}

      <div className="card">
        <h3>History</h3>
        <table>
          <tbody>
            {history.map((h, i) => (
              <tr key={i}>
                <td className="small">{formatDateTime(h.changed_at, tz)}</td>
                <td>
                  {h.from_status ? `${STATUS_LABELS[h.from_status]} → ` : ""}
                  {STATUS_LABELS[h.to_status]}
                </td>
                <td className="muted small">{h.changed_by_user_id ? h.reason ?? "" : `system${h.reason ? `: ${h.reason}` : ""}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
