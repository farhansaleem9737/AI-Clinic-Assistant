import { TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";
import { bookAppointment } from "../../services/appointmentService";
import { getErrorMessage } from "../../services/api";
import { isoDateIn, localToInstant } from "../../utils/datetime";
import ConfirmDialog from "../ConfirmDialog";
import FormField from "../FormField";
import PatientPickerDialog from "../booking/PatientPickerDialog";

const DURATIONS = [10, 15, 20, 30, 45, 60];

/**
 * A front-desk booking outside the normal rules (D117): any 5-minute start
 * within the doctor's hours, a custom length, or an authorized double booking
 * into a taken time. A double booking shows a warning, needs a reason and an
 * explicit confirmation; the server checks the permission, the doctor's policy
 * and their overbooking limit again, and audits every override.
 */
export default function OverrideBookingDialog({ doctorId, doctorName, timezone, policy, onClose, onBooked }) {
  const [patient, setPatient] = useState(null);
  const [picking, setPicking] = useState(false);
  const [date, setDate] = useState(() => isoDateIn(new Date(), timezone));
  const [time, setTime] = useState("");
  const [duration, setDuration] = useState(String(policy.consultation_minutes));
  const [customDuration, setCustomDuration] = useState("");
  const [double, setDouble] = useState(false);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const key = useRef(crypto.randomUUID());

  const minutes = duration === "custom" ? Number(customDuration) : Number(duration);

  const submit = async () => {
    const found = {};
    if (!patient) found.patient = "Choose the patient.";
    if (!time) found.time = "Enter a start time.";
    else if (Number(time.split(":")[1]) % 5) found.time = "Use a 5-minute mark, e.g. 10:05.";
    if (!(minutes >= 5 && minutes <= 240)) found.duration = "Use 5 to 240 minutes.";
    if (double && reason.trim().length < 3) found.reason = "Say why this double booking is needed.";
    if (double && !confirmed) found.confirmed = "Confirm that you understand the extra wait.";
    setErrors(found);
    setError("");
    if (Object.keys(found).length || busy) return;
    setBusy(true);
    try {
      const res = await bookAppointment(
        {
          doctor_id: doctorId,
          patient_id: patient.id,
          starts_at: localToInstant(date, time, timezone),
          custom_time: true,
          duration_minutes: minutes,
          double_booking: double,
          override_reason: reason.trim() || null,
        },
        key.current
      );
      onBooked(
        res.data.capacity_exception
          ? `Double-booked ${patient.name ?? `${patient.first_name} ${patient.last_name}`} at ${time} (authorized capacity exception). Waits around this time may be longer.`
          : `Booked ${patient.name ?? `${patient.first_name} ${patient.last_name}`} at ${time} for ${minutes} minutes.`
      );
    } catch (err) {
      key.current = crypto.randomUUID(); // a corrected request is a new booking
      const code = err.response?.data?.error?.code;
      if (code === "SLOT_TAKEN" && !double) setError("That time is already booked. Tick “Double booking” to add this patient anyway.");
      else setError(getErrorMessage(err, "The booking could not be made."));
    } finally {
      setBusy(false);
    }
  };

  const name = patient ? patient.name ?? `${patient.first_name} ${patient.last_name}` : "";
  return (
    <>
      <ConfirmDialog
        title="Custom booking"
        description={`${doctorName}. Times are in clinic time (${timezone}). Every custom booking is recorded with your name.`}
        showClose
        confirmLabel={double ? "Confirm double booking" : "Book"}
        busy={busy}
        error={error}
        onConfirm={submit}
        onCancel={onClose}
        className="wide-dialog override-dialog"
      >
        <FormField id="override-patient" label="Patient" error={errors.patient}>
          <button id="override-patient" type="button" className="secondary block" onClick={() => setPicking(true)}>
            {name || "Choose a patient…"}
          </button>
        </FormField>
        <div className="override-grid">
          <FormField id="override-date" label="Date" error={errors.date}>
            <input id="override-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </FormField>
          <FormField id="override-time" label="Start time" error={errors.time}>
            <input id="override-time" type="time" step={300} value={time} onChange={(e) => setTime(e.target.value)} />
          </FormField>
          <FormField id="override-duration" label="Length" error={errors.duration}>
            <select id="override-duration" value={duration} onChange={(e) => setDuration(e.target.value)}>
              {DURATIONS.map((m) => (
                <option key={m} value={m}>
                  {m} minutes
                </option>
              ))}
              <option value="custom">Custom…</option>
            </select>
          </FormField>
          {duration === "custom" && (
            <FormField id="override-custom-duration" label="Custom length (minutes)">
              <input id="override-custom-duration" type="number" min={5} max={240} value={customDuration} onChange={(e) => setCustomDuration(e.target.value)} />
            </FormField>
          )}
        </div>
        {policy.max_overbook > 0 && (
          <label className="check">
            <input type="checkbox" checked={double} onChange={(e) => setDouble(e.target.checked)} />
            <span>Double booking: add this patient to a time that is already booked (up to {policy.max_overbook} extra)</span>
          </label>
        )}
        {double && (
          <div className="override-warning" role="note">
            <p>
              <TriangleAlert size={18} aria-hidden="true" /> Two patients will share one time. The doctor sees one patient at a
              time, so one of them will wait longer. Tell the patient their consultation time is not guaranteed.
            </p>
            <FormField id="override-reason" label="Reason (required)" error={errors.reason}>
              <textarea id="override-reason" rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
            </FormField>
            <label className="check">
              <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
              <span>I understand this is a capacity exception and will be recorded.</span>
            </label>
            {errors.confirmed && <p className="field-error">{errors.confirmed}</p>}
          </div>
        )}
        {!double && (
          <FormField id="override-note" label="Reason (optional)">
            <input id="override-note" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
          </FormField>
        )}
      </ConfirmDialog>
      {picking && (
        <PatientPickerDialog
          currentId={patient?.id}
          onClose={() => setPicking(false)}
          onSelect={(p) => {
            setPatient(p);
            setPicking(false);
          }}
        />
      )}
    </>
  );
}
