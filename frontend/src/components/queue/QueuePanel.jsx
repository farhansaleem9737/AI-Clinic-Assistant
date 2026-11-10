import { BellRing, CalendarPlus, Clock, Play, RefreshCw, Square, UserPlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useRealtimeEvent } from "../../hooks/useRealtime";
import { getErrorMessage } from "../../services/api";
import realtime from "../../services/realtime";
import { changeAppointmentStatus } from "../../services/appointmentService";
import { callNextPatient, getQueueBoard, getQueueSessions, queueAction, registerWalkIn } from "../../services/queueService";
import { formatTime } from "../../utils/datetime";
import { waitText } from "../../utils/queue";
import Alert from "../Alert";
import PatientPickerDialog from "../booking/PatientPickerDialog";
import OverrideBookingDialog from "./OverrideBookingDialog";

const REFRESH_MS = 30000; // the fallback poll, paused while live updates are connected (D122)

const MODE_LABEL = { hybrid: "Hybrid", scheduled: "Scheduled only", fifo: "First come, first served" };

function Token({ entry }) {
  return (
    <span className={`queue-token ${entry.kind === "walk_in" ? "walk-in" : "scheduled"}`} aria-label={`Token ${entry.token_number}`}>
      #{entry.token_number}
    </span>
  );
}

function EntryLine({ entry, timezone }) {
  return (
    <div className="queue-entry-main">
      <Token entry={entry} />
      <span className="queue-entry-who">
        <strong>{entry.patient_name}</strong>
        <small className="muted">
          {entry.kind === "walk_in" ? "Walk-in" : `Booked ${formatTime(entry.scheduled_at, timezone)}`}
          {entry.checked_in_at && ` · arrived ${formatTime(entry.checked_in_at, timezone)}`}
        </small>
      </span>
      {entry.late && <span className="badge warn">Late</span>}
      {entry.prioritized && <span className="badge info">Moved up</span>}
      {entry.deferred_until && <span className="badge">Back {formatTime(entry.deferred_until, timezone)}</span>}
    </div>
  );
}

/**
 * The day's queue for one doctor (D117). The front desk picks a doctor's
 * session; the doctor sees their own. Every action is checked again by the
 * server, which also decides the order ("call next" follows its rules).
 */
export default function QueuePanel({ role, doctorId: fixedDoctorId, canOverride = false }) {
  const staff = role === "staff";
  const [sessions, setSessions] = useState(null);
  const [doctorId, setDoctorId] = useState(fixedDoctorId ?? "");
  const [loaded, setBoard] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const [booking, setBooking] = useState(false);

  useEffect(() => {
    if (!staff) return;
    getQueueSessions()
      .then((res) => {
        setSessions(res.data);
        setDoctorId((current) => current || res.data[0]?.doctor_id || "");
      })
      .catch((err) => setError(getErrorMessage(err, "Today's sessions could not be loaded.")));
  }, [staff]);

  const load = useCallback(() => {
    if (!doctorId) return Promise.resolve();
    return getQueueBoard(doctorId)
      .then((res) => setBoard(res.data))
      .catch((err) => setError(getErrorMessage(err, "The queue could not be loaded.")));
  }, [doctorId]);

  useEffect(() => {
    load();
    const timer = setInterval(() => !realtime.connected && load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);
  // This doctor's queue or appointments changed (someone checked in, booked, cancelled), or a reconnect.
  useRealtimeEvent(["queue.", "appointment."], (event) => {
    if (!event.payload || event.payload.doctor_id === doctorId) load();
  });

  const run = async (work, success) => {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await work();
      if (success) setNotice(typeof success === "function" ? success(result) : success);
      await load();
    } catch (err) {
      setError(getErrorMessage(err, "That could not be done. Please try again."));
    } finally {
      setBusy(false);
    }
  };
  const act = (entry, action, body, success) => run(() => queueAction(entry.id, action, body), success);

  // Never show one doctor's queue under another's name while switching.
  const board = loaded?.doctor_id === doctorId ? loaded : null;

  if (staff && sessions && sessions.length === 0) {
    return (
      <section className="card queue-panel" aria-label="Today's queue">
        <h2>Today's queue</h2>
        <p className="muted">No doctor is working today.</p>
      </section>
    );
  }

  const tz = board?.timezone;

  const doctorActions = role === "doctor";

  return (
    <section className="card queue-panel" aria-labelledby="queue-title">
      <div className="queue-head">
        <div>
          <h2 id="queue-title">Today's queue</h2>
          {board && (
            <p className="muted small">
              {board.doctor_name} · {MODE_LABEL[board.policy.mode]} · {board.policy.consultation_minutes}-minute consultations
            </p>
          )}
        </div>
        <div className="queue-head-actions">
          {staff && sessions && (
            <label className="queue-doctor-picker">
              <span className="sr-only">Doctor</span>
              <select value={doctorId} onChange={(e) => setDoctorId(e.target.value)} aria-label="Doctor's session">
                {sessions.map((s) => (
                  <option key={s.doctor_id} value={s.doctor_id}>
                    {s.doctor_name} ({s.hours.map((h) => h.join("–")).join(", ")}) · {s.waiting} waiting
                  </option>
                ))}
              </select>
            </label>
          )}
          <button type="button" className="secondary icon-text" onClick={() => load()} aria-label="Refresh the queue">
            <RefreshCw size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div aria-live="polite">
        <Alert kind="success">{notice}</Alert>
      </div>
      <Alert>{error}</Alert>

      {!board ? (
        <p className="muted" role="status">
          Loading the queue…
        </p>
      ) : (
        <>
          {board.running_late_minutes > 0 && (
            <Alert kind="warn">The current consultation is {board.running_late_minutes} min over its expected length: waits may be longer.</Alert>
          )}
          <div className="queue-toolbar">
            <button type="button" disabled={busy || board.waiting.length === 0 || Boolean(board.called)} onClick={() =>
              run(() => callNextPatient(board.doctor_id), (res) =>
                `Token #${res.data.entry.token_number} (${res.data.entry.patient_name}) called.` +
                (res.data.may_delay_scheduled ? " A booked patient is due soon and may wait a little." : ""))
            }>
              <BellRing size={16} aria-hidden="true" /> Call next
            </button>
            {staff && board.policy.mode !== "scheduled" && board.policy.accept_walk_ins && (
              <button type="button" className="secondary" disabled={busy} onClick={() => setPicking(true)}>
                <UserPlus size={16} aria-hidden="true" /> Register walk-in
              </button>
            )}
            {staff && canOverride && (
              <button type="button" className="secondary" disabled={busy} onClick={() => setBooking(true)}>
                <CalendarPlus size={16} aria-hidden="true" /> Custom booking
              </button>
            )}
          </div>

          <div className="queue-now">
            <div className="queue-now-card">
              <h3>In consultation</h3>
              {board.current ? (
                <>
                  <EntryLine entry={board.current} timezone={tz} />
                  {doctorActions && (
                    <button type="button" disabled={busy} onClick={() => act(board.current, "complete", undefined, "Consultation completed.")}>
                      <Square size={15} aria-hidden="true" /> Complete
                    </button>
                  )}
                </>
              ) : (
                <p className="muted small">Nobody right now.</p>
              )}
            </div>
            <div className="queue-now-card">
              <h3>Called</h3>
              {board.called ? (
                <>
                  <EntryLine entry={board.called} timezone={tz} />
                  <div className="queue-row-actions">
                    {doctorActions && (
                      <button type="button" disabled={busy || Boolean(board.current)} onClick={() => act(board.called, "start", undefined, "Consultation started.")}>
                        <Play size={15} aria-hidden="true" /> Start
                      </button>
                    )}
                    <button type="button" className="secondary" disabled={busy} onClick={() => act(board.called, "absent", undefined, "Marked absent: they can check in again.")}>
                      Not here
                    </button>
                    <button type="button" className="secondary" disabled={busy} onClick={() => act(board.called, "defer", { minutes: 15 }, "Deferred for 15 minutes.")}>
                      Defer 15 min
                    </button>
                  </div>
                </>
              ) : (
                <p className="muted small">Nobody called.</p>
              )}
            </div>
          </div>

          <h3 className="queue-section-title">Waiting ({board.waiting.length})</h3>
          {board.waiting.length === 0 ? (
            <p className="muted small">Nobody is waiting.</p>
          ) : (
            <ol className="queue-list">
              {board.waiting.map((e) => (
                <li key={e.id} className="queue-row">
                  <EntryLine entry={e} timezone={tz} />
                  <span className="queue-wait muted small">{waitText(e.estimated_wait)}</span>
                  <div className="queue-row-actions">
                    {doctorActions && (
                      <button type="button" className="secondary" disabled={busy || Boolean(board.current)} onClick={() => act(e, "start", undefined, "Consultation started.")}>
                        Start
                      </button>
                    )}
                    <button type="button" className="secondary" disabled={busy || Boolean(board.called)} onClick={() => act(e, "call", undefined, `Token #${e.token_number} called out of order.`)}>
                      Call
                    </button>
                    <button type="button" className="secondary" disabled={busy || e.prioritized} onClick={() => act(e, "prioritize", {}, `Token #${e.token_number} moved to the front.`)}>
                      Move up
                    </button>
                    <button type="button" className="secondary" disabled={busy} onClick={() => act(e, "defer", { minutes: 15 }, `Token #${e.token_number} deferred for 15 minutes.`)}>
                      Defer
                    </button>
                    {staff && e.kind === "walk_in" && (
                      <button type="button" className="secondary danger" disabled={busy} onClick={() => act(e, "no-show", undefined, `Token #${e.token_number} marked a no-show.`)}>
                        No-show
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}

          {(board.not_arrived.length > 0 || board.registered.length > 0) && (
            <>
              <h3 className="queue-section-title">Not arrived yet</h3>
              <ul className="queue-list">
                {board.not_arrived.map((a) => (
                  <li key={a.appointment_id} className="queue-row">
                    <div className="queue-entry-main">
                      <Clock size={16} aria-hidden="true" className="muted" />
                      <span className="queue-entry-who">
                        <strong>{a.patient_name}</strong>
                        <small className="muted">Booked {formatTime(a.scheduled_at, tz)}</small>
                      </span>
                      {a.late && <span className="badge warn">Late</span>}
                    </div>
                    {staff && (
                      <div className="queue-row-actions">
                        <button type="button" className="secondary" disabled={busy} onClick={() =>
                          run(() => changeAppointmentStatus(a.appointment_id, { status: "checked_in" }), `${a.patient_name} checked in.`)
                        }>
                          Check in
                        </button>
                      </div>
                    )}
                  </li>
                ))}
                {board.registered.map((e) => (
                  <li key={e.id} className="queue-row">
                    <EntryLine entry={e} timezone={tz} />
                    {staff && (
                      <div className="queue-row-actions">
                        <button type="button" className="secondary" disabled={busy} onClick={() => act(e, "check-in", undefined, `Token #${e.token_number} checked in.`)}>
                          Check in
                        </button>
                        <button type="button" className="secondary danger" disabled={busy} onClick={() => act(e, "no-show", undefined, `Token #${e.token_number} marked a no-show.`)}>
                          No-show
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}

          {board.finished.length > 0 && (
            <details className="queue-finished">
              <summary>Finished and absent ({board.finished.length})</summary>
              <ul className="queue-list">
                {board.finished.map((e) => (
                  <li key={e.id} className="queue-row">
                    <EntryLine entry={e} timezone={tz} />
                    <span className="badge">{e.state.replace("_", " ")}</span>
                    {staff && e.state === "absent" && (
                      <button type="button" className="secondary" disabled={busy} onClick={() => act(e, "check-in", undefined, `Token #${e.token_number} is back in the queue.`)}>
                        Check in again
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}

      {picking && (
        <PatientPickerDialog
          onClose={() => setPicking(false)}
          onSelect={(patient) => {
            setPicking(false);
            run(() => registerWalkIn({ doctor_id: board.doctor_id, patient_id: patient.id }), (res) =>
              `${res.data.patient_name}: token #${res.data.token_number}. ${waitText(res.data.estimated_wait)}`
            );
          }}
        />
      )}
      {booking && board && (
        <OverrideBookingDialog
          doctorId={board.doctor_id}
          doctorName={board.doctor_name}
          timezone={board.timezone}
          policy={board.policy}
          onClose={() => setBooking(false)}
          onBooked={(message) => {
            setBooking(false);
            setNotice(message);
            load();
          }}
        />
      )}
    </section>
  );
}
