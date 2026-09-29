import { useCallback, useEffect, useState } from "react";
import Alert from "../components/Alert";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { listDoctors } from "../services/doctorService";
import {
  createException,
  createTemplate,
  deactivateTemplate,
  deleteException,
  listExceptions,
  listTemplates,
} from "../services/scheduleService";
import { formatDateTime, isoDateIn, localInputToIso, WEEKDAYS } from "../utils/datetime";
import { doctorName } from "../utils/format";

const KINDS = { leave: "Leave", holiday: "Holiday", block: "Blocked time", extra_availability: "Extra availability" };
const EMPTY_TEMPLATE = { weekday: 0, start_time: "09:00", end_time: "13:00", slot_minutes: 30, valid_from: "", valid_until: "" };
const EMPTY_EXCEPTION = { kind: "leave", starts_at: "", ends_at: "", reason: "" };

// Doctors manage their own weekly hours and time off; staff with
// schedule:manage_any pick any doctor.
export default function DoctorSchedule() {
  const { user, can } = useAuth();
  const managesAny = can("schedule:manage_any");
  const [doctors, setDoctors] = useState([]);
  const [doctorId, setDoctorId] = useState(managesAny ? "" : user.doctor_id ?? "");
  const [templates, setTemplates] = useState([]);
  const [exceptions, setExceptions] = useState([]);
  const [template, setTemplate] = useState({ ...EMPTY_TEMPLATE, valid_from: isoDateIn(new Date()) });
  const [exception, setException] = useState(EMPTY_EXCEPTION);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!managesAny) return;
    listDoctors({ is_active: true, page_size: 100 })
      .then((res) => setDoctors(res.data.items))
      .catch(() => {});
  }, [managesAny]);

  const load = useCallback(() => {
    if (!doctorId) return;
    listTemplates(doctorId)
      .then((res) => setTemplates(res.data))
      .catch((err) => setError(getErrorMessage(err)));
    listExceptions(doctorId, new Date().toISOString())
      .then((res) => setExceptions(res.data))
      .catch(() => {});
  }, [doctorId]);

  useEffect(load, [load]);

  const run = async (action, success) => {
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(success);
      load();
      return true;
    } catch (err) {
      setError(getErrorMessage(err));
      return false;
    }
  };

  if (!managesAny && !user.doctor_id) return <Alert>You do not have a doctor profile.</Alert>;

  const addTemplate = async (e) => {
    e.preventDefault();
    const body = {
      ...template,
      doctor_id: doctorId,
      weekday: Number(template.weekday),
      slot_minutes: Number(template.slot_minutes),
      valid_until: template.valid_until || null,
    };
    if (await run(() => createTemplate(body), "Working hours added")) setTemplate({ ...template, start_time: "14:00", end_time: "17:00" });
  };

  const addException = async (e) => {
    e.preventDefault();
    const body = {
      doctor_id: doctorId,
      kind: exception.kind,
      starts_at: localInputToIso(exception.starts_at),
      ends_at: localInputToIso(exception.ends_at),
      reason: exception.reason || null,
    };
    if (await run(() => createException(body), "Saved")) setException(EMPTY_EXCEPTION);
  };

  return (
    <div>
      <h2>Schedule</h2>
      {managesAny && (
        <label style={{ maxWidth: 400 }}>
          Doctor
          <select value={doctorId} onChange={(e) => setDoctorId(e.target.value)}>
            <option value="">Select a doctor</option>
            {doctors.map((d) => (
              <option key={d.id} value={d.id}>
                {doctorName(d)} — {d.department_name}
              </option>
            ))}
          </select>
        </label>
      )}
      <Alert>{error}</Alert>
      <Alert kind="success">{notice}</Alert>

      {doctorId && (
        <>
          <div className="card">
            <h3>Weekly working hours</h3>
            <p className="muted small">Local time of the doctor's department.</p>
            <table>
              <thead>
                <tr>
                  <th>Day</th>
                  <th>Hours</th>
                  <th>Slot</th>
                  <th>Valid</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {templates.map((t) => (
                  <tr key={t.id}>
                    <td>{WEEKDAYS[t.weekday]}</td>
                    <td>
                      {t.start_time.slice(0, 5)}–{t.end_time.slice(0, 5)}
                    </td>
                    <td>{t.slot_minutes} min</td>
                    <td className="small">
                      from {t.valid_from}
                      {t.valid_until ? ` until ${t.valid_until}` : ""}
                    </td>
                    <td>
                      <button className="danger" onClick={() => run(() => deactivateTemplate(t.id), "Working hours removed")}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <form className="row" onSubmit={addTemplate} style={{ marginTop: "0.75rem", alignItems: "end" }}>
              <label>
                Day
                <select value={template.weekday} onChange={(e) => setTemplate({ ...template, weekday: e.target.value })}>
                  {WEEKDAYS.map((d, i) => (
                    <option key={d} value={i}>
                      {d}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                From
                <input type="time" value={template.start_time} onChange={(e) => setTemplate({ ...template, start_time: e.target.value })} required />
              </label>
              <label>
                To
                <input type="time" value={template.end_time} onChange={(e) => setTemplate({ ...template, end_time: e.target.value })} required />
              </label>
              <label>
                Slot (min)
                <input
                  type="number"
                  min="5"
                  max="240"
                  value={template.slot_minutes}
                  onChange={(e) => setTemplate({ ...template, slot_minutes: e.target.value })}
                  style={{ width: 80 }}
                />
              </label>
              <label>
                Valid from
                <input type="date" value={template.valid_from} onChange={(e) => setTemplate({ ...template, valid_from: e.target.value })} required />
              </label>
              <label>
                until (optional)
                <input type="date" value={template.valid_until} onChange={(e) => setTemplate({ ...template, valid_until: e.target.value })} />
              </label>
              <button type="submit">Add</button>
            </form>
          </div>

          <div className="card">
            <h3>Time off and extra hours</h3>
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>From</th>
                  <th>To</th>
                  <th>Note</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {exceptions.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      None upcoming.
                    </td>
                  </tr>
                )}
                {exceptions.map((x) => (
                  <tr key={x.id}>
                    <td>{KINDS[x.kind]}</td>
                    <td>{formatDateTime(x.starts_at)}</td>
                    <td>{formatDateTime(x.ends_at)}</td>
                    <td>{x.reason}</td>
                    <td>
                      <button className="danger" onClick={() => run(() => deleteException(x.id), "Removed")}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <form className="row" onSubmit={addException} style={{ marginTop: "0.75rem", alignItems: "end" }}>
              <label>
                Type
                <select value={exception.kind} onChange={(e) => setException({ ...exception, kind: e.target.value })}>
                  {Object.entries(KINDS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                From
                <input type="datetime-local" value={exception.starts_at} onChange={(e) => setException({ ...exception, starts_at: e.target.value })} required />
              </label>
              <label>
                To
                <input type="datetime-local" value={exception.ends_at} onChange={(e) => setException({ ...exception, ends_at: e.target.value })} required />
              </label>
              <label>
                Note
                <input value={exception.reason} onChange={(e) => setException({ ...exception, reason: e.target.value })} maxLength={255} />
              </label>
              <button type="submit">Add</button>
            </form>
          </div>
        </>
      )}
    </div>
  );
}
