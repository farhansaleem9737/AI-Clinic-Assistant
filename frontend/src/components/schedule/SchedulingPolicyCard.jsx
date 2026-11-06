import { Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { getErrorMessage } from "../../services/api";
import { getSchedulingPolicy, saveSchedulingPolicy } from "../../services/queueService";
import Alert from "../Alert";
import FormField from "../FormField";
import PolicyPreview, { AffectedList } from "./PolicyPreview";

const MODES = [
  { value: "hybrid", label: "Hybrid", hint: "Booked times keep priority; walk-ins fill the free time in arrival order." },
  { value: "scheduled", label: "Scheduled only", hint: "Patients book exact times; no walk-in tokens." },
  { value: "fifo", label: "First come, first served", hint: "No booked times: patients get a token and are seen in arrival order." },
];

/**
 * The doctor's scheduling policy (D117): how long a consultation is, how
 * patients are seen, walk-ins and overbooking. Saving changes how future
 * free times are offered; existing appointments keep their own times.
 * Read-only for staff who may see but not change it.
 *
 * D120: the appointment duration is 15, 20 or 30 minutes (a length saved
 * earlier stays selectable as "current"); a live preview shows the day it
 * gives; a change that does not fit upcoming bookings is saved only after the
 * doctor confirms those keep their booked times (nothing is moved).
 */
export default function SchedulingPolicyCard({ doctorId, canEdit, onSaved }) {
  const [policy, setPolicy] = useState(null);
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  // 409 SCHEDULE_CONFLICTS from the server: the bookings that do not fit, and the doctor's explicit choice.
  const [conflict, setConflict] = useState(null);
  const [keepExisting, setKeepExisting] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getSchedulingPolicy(doctorId)
      .then((res) => {
        if (cancelled) return;
        setPolicy(res.data);
        setForm(res.data);
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err, "The scheduling settings could not be loaded.")));
    return () => {
      cancelled = true;
    };
  }, [doctorId]);

  if (!policy || !form) {
    return (
      <section className="card schedule-card policy-card" id="scheduling-policy" aria-label="Scheduling settings">
        {error ? <Alert>{error}</Alert> : <p className="muted" role="status">Loading scheduling settings…</p>}
      </section>
    );
  }

  const set = (field, value) => {
    setForm((f) => ({ ...f, [field]: value }));
    if (field === "consultation_minutes" || field === "buffer_minutes") {
      setConflict(null); // a different length: the server checks again
      setKeepExisting(false);
    }
  };
  const durations = [...new Set([...policy.standard_durations, policy.consultation_minutes])].sort((a, b) => a - b);
  const number = (field) => (e) => set(field, e.target.value === "" ? "" : Number(e.target.value));
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { mode, consultation_minutes, buffer_minutes, accept_walk_ins, walk_in_capacity, late_grace_minutes, max_overbook, allow_receptionist_overrides } = form;
      const res = await saveSchedulingPolicy(doctorId, {
        mode, consultation_minutes, buffer_minutes, accept_walk_ins, late_grace_minutes, max_overbook, allow_receptionist_overrides,
        walk_in_capacity: walk_in_capacity === "" || walk_in_capacity == null ? null : walk_in_capacity,
        keep_existing_appointments: Boolean(conflict && keepExisting),
      });
      setPolicy(res.data);
      setForm(res.data);
      setConflict(null);
      setKeepExisting(false);
      onSaved?.("Scheduling settings saved. New free times use them; existing appointments are unchanged.");
    } catch (err) {
      const details = err.response?.data?.error;
      if (details?.code === "SCHEDULE_CONFLICTS") {
        setConflict(details.details);
        setKeepExisting(false);
      } else setError(getErrorMessage(err, "The scheduling settings could not be saved."));
    } finally {
      setBusy(false);
    }
  };
  const disabled = !canEdit || busy;
  const walkIns = form.mode !== "scheduled";

  return (
    <section className="card schedule-card policy-card" id="scheduling-policy" aria-labelledby="policy-title">
      <div className="card-title">
        <Settings2 className="icon" size={24} aria-hidden="true" />
        <div>
          <h2 id="policy-title">Scheduling settings</h2>
          <p className="muted small">
            {policy.configured
              ? "How appointment times are offered and how the day's queue runs."
              : `Not saved yet: free times still use your weekly hours' ${policy.legacy_slot_minutes ?? 30}-minute slots. Save to use these settings.`}
          </p>
        </div>
      </div>
      <form onSubmit={save} className="policy-form">
        <fieldset disabled={disabled}>
          <legend className="sr-only">Scheduling mode</legend>
          <div className="policy-modes" role="radiogroup" aria-label="How patients are seen">
            {MODES.map((m) => (
              <label key={m.value} className={form.mode === m.value ? "policy-mode selected" : "policy-mode"}>
                <input type="radio" name="mode" value={m.value} checked={form.mode === m.value} onChange={() => set("mode", m.value)} />
                <span>
                  <strong>{m.label}</strong>
                  <small className="muted">{m.hint}</small>
                </span>
              </label>
            ))}
          </div>
          <div className="policy-grid">
            <FormField id="policy-duration" label="Appointment Duration">
              <select id="policy-duration" value={form.consultation_minutes} onChange={(e) => set("consultation_minutes", Number(e.target.value))}>
                {durations.map((m) => (
                  <option key={m} value={m}>
                    {m} minutes{policy.standard_durations.includes(m) ? "" : " (current)"}
                  </option>
                ))}
              </select>
            </FormField>
            <FormField id="policy-buffer" label="Buffer between patients (minutes)">
              <input id="policy-buffer" type="number" min={0} max={120} value={form.buffer_minutes} onChange={number("buffer_minutes")} />
            </FormField>
            <FormField id="policy-grace" label="Late-arrival grace (minutes)">
              <input id="policy-grace" type="number" min={0} max={120} value={form.late_grace_minutes} onChange={number("late_grace_minutes")} />
            </FormField>
            <FormField id="policy-overbook" label="Extra patients staff may double-book into one time">
              <input id="policy-overbook" type="number" min={0} max={5} value={form.max_overbook} onChange={number("max_overbook")} />
            </FormField>
            {walkIns && (
              <FormField id="policy-capacity" label="Walk-in tokens per day (empty = no limit)">
                <input id="policy-capacity" type="number" min={1} max={500} value={form.walk_in_capacity ?? ""} onChange={number("walk_in_capacity")} />
              </FormField>
            )}
          </div>
          {walkIns && (
            <label className="check">
              <input type="checkbox" checked={form.accept_walk_ins} onChange={(e) => set("accept_walk_ins", e.target.checked)} />
              <span>Accept walk-in patients</span>
            </label>
          )}
          <label className="check">
            <input type="checkbox" checked={form.allow_receptionist_overrides} onChange={(e) => set("allow_receptionist_overrides", e.target.checked)} />
            <span>Let the front desk book custom times, lengths and double bookings (always with a reason and an audit record)</span>
          </label>
        </fieldset>
        {form.mode !== "fifo" && (
          <PolicyPreview doctorId={doctorId} minutes={form.consultation_minutes} buffer={form.buffer_minutes === "" ? null : form.buffer_minutes} />
        )}
        {conflict && (
          <div className="policy-affected" role="alert">
            <p>
              <strong>
                {conflict.count} upcoming appointment{conflict.count === 1 ? "" : "s"} do not fit {form.consultation_minutes}-minute
                appointments.
              </strong>{" "}
              Saving will not move or cancel them: they keep their booked times and lengths. To change one, reschedule it.
            </p>
            <AffectedList items={conflict.appointments} total={conflict.count} />
            <label className="check">
              <input type="checkbox" checked={keepExisting} onChange={(e) => setKeepExisting(e.target.checked)} />
              <span>Keep these appointments at their booked times and save the new length</span>
            </label>
          </div>
        )}
        <Alert>{error}</Alert>
        {canEdit ? (
          <div className="policy-actions">
            <button type="submit" disabled={busy || (conflict && !keepExisting)}>
              {busy ? "Saving…" : conflict ? "Save and keep existing appointments" : "Save settings"}
            </button>
          </div>
        ) : (
          <p className="muted small">Only the doctor or an administrator can change these settings.</p>
        )}
      </form>
    </section>
  );
}
