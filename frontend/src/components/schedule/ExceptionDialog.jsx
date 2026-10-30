import { useState } from "react";
import { getErrorMessage } from "../../services/api";
import ConfirmDialog from "../ConfirmDialog";

const REASON_MAX = 255;

function validate(form, today) {
  const errors = {};
  if (!form.date) errors.date = "Choose a date.";
  else if (form.date < today) errors.date = "Choose today or a later date.";
  if (form.type === "custom_hours") {
    if (!form.start_time || !form.end_time) errors.hours = "Enter a start and an end time.";
    else if (form.start_time >= form.end_time) errors.hours = "The end time must be after the start time.";
  }
  if (form.reason.length > REASON_MAX) errors.reason = `Use at most ${REASON_MAX} characters.`;
  return errors;
}

// A server refusal, as messages for the form: { fields, form }.
function serverErrors(err) {
  const code = err?.response?.data?.error?.code;
  if (code === "EXCEPTION_EXISTS") return { fields: { date: "This date already has an exception. Edit that one instead." }, form: "" };
  if (code === "PAST_DATE" || code === "DATE_TOO_FAR") return { fields: { date: getErrorMessage(err) }, form: "" };
  return { fields: {}, form: getErrorMessage(err, "Could not save the exception") };
}

/**
 * Add or edit one date that differs from the weekly hours: the whole day off,
 * or custom hours that replace the weekly hours for that date.
 */
export default function ExceptionDialog({ exception, today, timeZoneNote, onSave, onClose }) {
  const [form, setForm] = useState({
    date: exception?.date ?? "",
    type: exception?.type ?? "unavailable",
    start_time: exception?.start_time?.slice(0, 5) ?? "",
    end_time: exception?.end_time?.slice(0, 5) ?? "",
    reason: exception?.reason ?? "",
  });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (field) => (e) => {
    setForm({ ...form, [field]: e.target.value });
    setErrors({ ...errors, [field === "start_time" || field === "end_time" ? "hours" : field]: undefined });
  };
  const describedBy = (id, error) => (error ? `${id}-error` : undefined);

  const save = async () => {
    const found = validate(form, today);
    setErrors(found);
    setError("");
    if (Object.keys(found).length) return;
    setBusy(true);
    const custom = form.type === "custom_hours";
    try {
      await onSave({
        date: form.date,
        type: form.type,
        start_time: custom ? form.start_time : null,
        end_time: custom ? form.end_time : null,
        reason: form.reason.trim() || null,
      });
    } catch (err) {
      const mapped = serverErrors(err);
      setErrors(mapped.fields);
      setError(mapped.form);
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      title={exception ? "Edit Exception" : "Add Exception"}
      confirmLabel="Save Exception"
      busy={busy}
      error={error}
      onConfirm={save}
      onCancel={onClose}
      className="exception-dialog"
    >
      <div className="exception-form">
        <div className="edit-field">
          <label htmlFor="exception-date">Date</label>
          <input
            id="exception-date"
            type="date"
            min={today}
            value={form.date}
            onChange={set("date")}
            required
            aria-invalid={errors.date ? true : undefined}
            aria-describedby={describedBy("exception-date", errors.date)}
          />
          {errors.date && (
            <small className="field-error" id="exception-date-error">
              {errors.date}
            </small>
          )}
        </div>

        <fieldset className="exception-type">
          <legend>Exception Type</legend>
          <label className="check">
            <input type="radio" name="exception-type" value="unavailable" checked={form.type === "unavailable"} onChange={set("type")} />
            <span>
              <strong>Unavailable</strong> — no appointments on this date
            </span>
          </label>
          <label className="check">
            <input type="radio" name="exception-type" value="custom_hours" checked={form.type === "custom_hours"} onChange={set("type")} />
            <span>
              <strong>Custom Hours</strong> — these hours replace the weekly hours for this date
            </span>
          </label>
        </fieldset>

        {form.type === "custom_hours" && (
          <div className="exception-hours-fields">
            <div className="edit-field">
              <label htmlFor="exception-start">Start Time</label>
              <input
                id="exception-start"
                type="time"
                value={form.start_time}
                onChange={set("start_time")}
                required
                aria-invalid={errors.hours ? true : undefined}
                aria-describedby={describedBy("exception-hours", errors.hours)}
              />
            </div>
            <div className="edit-field">
              <label htmlFor="exception-end">End Time</label>
              <input
                id="exception-end"
                type="time"
                value={form.end_time}
                onChange={set("end_time")}
                required
                aria-invalid={errors.hours ? true : undefined}
                aria-describedby={describedBy("exception-hours", errors.hours)}
              />
            </div>
            {errors.hours && (
              <small className="field-error" id="exception-hours-error">
                {errors.hours}
              </small>
            )}
          </div>
        )}

        <div className="edit-field">
          <label htmlFor="exception-reason">
            Reason <span className="optional">(optional)</span>
          </label>
          <input
            id="exception-reason"
            maxLength={REASON_MAX}
            placeholder="e.g. Personal leave, Public holiday, Conference"
            value={form.reason}
            onChange={set("reason")}
            aria-invalid={errors.reason ? true : undefined}
            aria-describedby={describedBy("exception-reason", errors.reason)}
          />
          {errors.reason && (
            <small className="field-error" id="exception-reason-error">
              {errors.reason}
            </small>
          )}
        </div>
        {timeZoneNote && <p className="muted small">{timeZoneNote}</p>}
      </div>
    </ConfirmDialog>
  );
}
