import { Clock, Pencil, Plus, Save, X } from "lucide-react";
import { useEffect, useState } from "react";
import { formatWallTime, WEEKDAYS } from "../../utils/datetime";
import Alert from "../Alert";
import { draftFrom, intervalsError, payloadFrom } from "./weekly";

// Offered when a day without hours is switched on; nothing is saved until Save Changes.
const SUGGESTED = { start: "09:00", end: "17:00" };
const MAX_RANGES = 6;

function Switch({ checked, label, onChange, disabled }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className="switch"
      onClick={() => onChange(!checked)}
      disabled={disabled}
    >
      <span className="switch-thumb" aria-hidden="true" />
    </button>
  );
}

function TimeBoxes({ day, edge }) {
  if (!day.enabled) return <span className="muted" aria-label="Not set">—</span>;
  return (
    <div className="time-boxes">
      {day.intervals.map((i, index) => (
        <span key={index} className="time-box">
          <Clock size={17} aria-hidden="true" />
          {formatWallTime(i[edge])}
        </span>
      ))}
    </div>
  );
}

function DayEditor({ name, intervals, error, onChange, onDone, onCancel }) {
  const update = (index, field, value) =>
    onChange(intervals.map((i, k) => (k === index ? { ...i, [field]: value } : i)));
  return (
    <div className="day-editor" role="group" aria-label={`${name} working hours`}>
      {intervals.map((interval, index) => (
        <div className="day-editor-range" key={index}>
          <label>
            {intervals.length > 1 ? `Start ${index + 1}` : "Start time"}
            <input
              type="time"
              value={interval.start}
              onChange={(e) => update(index, "start", e.target.value)}
              aria-label={`${name} start time${intervals.length > 1 ? ` ${index + 1}` : ""}`}
              aria-invalid={error ? true : undefined}
              required
            />
          </label>
          <label>
            {intervals.length > 1 ? `End ${index + 1}` : "End time"}
            <input
              type="time"
              value={interval.end}
              onChange={(e) => update(index, "end", e.target.value)}
              aria-label={`${name} end time${intervals.length > 1 ? ` ${index + 1}` : ""}`}
              aria-invalid={error ? true : undefined}
              required
            />
          </label>
          {intervals.length > 1 && (
            <button
              type="button"
              className="secondary small-button"
              onClick={() => onChange(intervals.filter((_, k) => k !== index))}
              aria-label={`Remove ${name} time range ${index + 1}`}
            >
              <X size={15} aria-hidden="true" />
            </button>
          )}
        </div>
      ))}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <div className="day-editor-actions">
        {intervals.length < MAX_RANGES && (
          <button
            type="button"
            className="secondary small-button"
            onClick={() => onChange([...intervals, { start: "", end: "" }])}
          >
            <Plus size={15} aria-hidden="true" /> Add another time range
          </button>
        )}
        <span className="spacer" />
        <button type="button" className="secondary small-button" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="small-button" onClick={onDone}>
          Done
        </button>
      </div>
    </div>
  );
}

/**
 * The regular week as a draft: switch days on and off and edit their hours,
 * then Save Changes sends the whole week at once. Nothing is saved before.
 */
export default function WeeklyHoursCard({ schedule, onSave }) {
  const [saved, setSaved] = useState(() => draftFrom(schedule));
  const [days, setDays] = useState(saved);
  const [editing, setEditing] = useState(null); // { weekday, intervals, error }
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const dirty = JSON.stringify(payloadFrom(days)) !== JSON.stringify(payloadFrom(saved));

  // A reload or closed tab would lose the draft: let the browser ask first.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const setDay = (weekday, changes) => {
    setDays((current) => current.map((d) => (d.weekday === weekday ? { ...d, ...changes } : d)));
    setNotice("");
  };

  const openEditor = (day) =>
    setEditing({
      weekday: day.weekday,
      intervals: day.intervals.length ? day.intervals : [SUGGESTED],
      error: "",
    });

  const toggle = (day, on) => {
    if (on && day.intervals.length === 0) {
      openEditor(day); // hours first; the day switches on with Done
      return;
    }
    setDay(day.weekday, { enabled: on });
    if (!on && editing?.weekday === day.weekday) setEditing(null);
  };

  const finishEditing = () => {
    const problem = intervalsError(editing.intervals);
    if (problem) {
      setEditing({ ...editing, error: problem });
      return;
    }
    const intervals = [...editing.intervals].sort((a, b) => a.start.localeCompare(b.start));
    setDay(editing.weekday, { enabled: true, intervals });
    setEditing(null);
    setError("");
  };

  const save = async () => {
    setError("");
    setNotice("");
    if (editing) {
      setError(`Finish editing ${WEEKDAYS[editing.weekday]} first: choose Done or Cancel.`);
      return;
    }
    const broken = days.find((d) => d.enabled && intervalsError(d.intervals));
    if (broken) {
      setError(`${WEEKDAYS[broken.weekday]}: ${intervalsError(broken.intervals)}`);
      return;
    }
    setSaving(true);
    try {
      const fresh = draftFrom(await onSave(payloadFrom(days)));
      setSaved(fresh);
      setDays(fresh);
      setNotice("Your weekly hours were saved.");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="card schedule-card" aria-labelledby="weekly-hours-title" id="weekly-hours">
      <div className="schedule-card-head">
        <Clock className="schedule-card-icon" size={34} aria-hidden="true" />
        <div>
          <h2 id="weekly-hours-title" tabIndex={-1}>
            Weekly Working Hours
          </h2>
          <p className="muted">
            Set your regular weekly working hours. You can enable or disable days and set start and end times.
          </p>
        </div>
      </div>

      <div className="weekly-table-wrap">
        <table className="weekly-table">
          <thead>
            <tr>
              <th scope="col">Day</th>
              <th scope="col">Status</th>
              <th scope="col">Start Time</th>
              <th scope="col">End Time</th>
              <th scope="col">Action</th>
            </tr>
          </thead>
          <tbody>
            {days.map((day) => {
              const name = WEEKDAYS[day.weekday];
              const isEditing = editing?.weekday === day.weekday;
              return [
                <tr key={day.weekday} className={day.enabled ? "" : "day-off"}>
                  <th scope="row">{name}</th>
                  <td>
                    <span className="status-cell">
                      <Switch
                        checked={day.enabled}
                        label={`${name} available`}
                        onChange={(on) => toggle(day, on)}
                        disabled={saving}
                      />
                      <span className="status-text">{day.enabled ? "Available" : "Unavailable"}</span>
                    </span>
                  </td>
                  <td data-label="Start Time">
                    <TimeBoxes day={day} edge="start" />
                  </td>
                  <td data-label="End Time">
                    <TimeBoxes day={day} edge="end" />
                  </td>
                  <td>
                    <button
                      type="button"
                      className="secondary edit-button"
                      onClick={() => openEditor(day)}
                      disabled={saving || isEditing}
                      aria-label={`Edit ${name} hours`}
                    >
                      <Pencil size={16} aria-hidden="true" /> Edit
                    </button>
                  </td>
                </tr>,
                isEditing && (
                  <tr key={`${day.weekday}-editor`} className="editor-row">
                    <td colSpan={5}>
                      <DayEditor
                        name={name}
                        intervals={editing.intervals}
                        error={editing.error}
                        onChange={(intervals) => setEditing({ ...editing, intervals, error: "" })}
                        onDone={finishEditing}
                        onCancel={() => {
                          setEditing(null);
                          setError("");
                        }}
                      />
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
      </div>

      <div className="weekly-footer">
        <div aria-live="polite" className="weekly-status">
          <Alert>{error}</Alert>
          <Alert kind="success">{notice}</Alert>
          {dirty && !error && (
            <span className="unsaved">
              You have unsaved changes.{" "}
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  setDays(saved);
                  setEditing(null);
                }}
              >
                Discard
              </button>
            </span>
          )}
        </div>
        <button type="button" className="save-button" onClick={save} disabled={saving || (!dirty && !editing)} aria-busy={saving}>
          <Save size={18} aria-hidden="true" /> {saving ? "Saving…" : "Save Changes"}
        </button>
      </div>
    </section>
  );
}
