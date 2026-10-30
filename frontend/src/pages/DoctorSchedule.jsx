import { CalendarDays, Clock } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Alert from "../components/Alert";
import ConfirmDialog from "../components/ConfirmDialog";
import ExceptionDialog from "../components/schedule/ExceptionDialog";
import ExceptionsCard from "../components/schedule/ExceptionsCard";
import WeeklyHoursCard from "../components/schedule/WeeklyHoursCard";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { listDoctors } from "../services/doctorService";
import {
  createDateException,
  deleteDateException,
  getWeeklySchedule,
  listDateExceptions,
  saveWeeklySchedule,
  updateDateException,
} from "../services/scheduleService";
import { formatMonthDay, isoDateIn, timeZoneLabel } from "../utils/datetime";
import { doctorName } from "../utils/format";

// A refused schedule change as one readable sentence (no patient details: the
// API sends only the doctor's own dates).
function scheduleError(err, fallback) {
  const data = err?.response?.data?.error;
  if (data?.code === "SCHEDULE_CONFLICT") {
    const dates = (data.details?.dates ?? []).map(formatMonthDay).join(", ");
    return `${data.message}${dates ? ` Affected dates: ${dates}.` : ""}`;
  }
  if (err?.response?.status === 403) return "You do not have permission to change this schedule.";
  if (err?.response?.status === 422) return "Some hours are not valid. Check each day's start and end times.";
  return getErrorMessage(err, fallback);
}

function SectionNav({ active, onSelect }) {
  const tabs = [
    { key: "weekly", label: "Weekly Hours", icon: Clock, target: "weekly-hours" },
    { key: "exceptions", label: "Exceptions", icon: CalendarDays, target: "schedule-exceptions" },
  ];
  return (
    <nav className="schedule-nav" aria-label="Schedule sections">
      {tabs.map(({ key, label, icon: Icon, target }) => (
        <a
          key={key}
          href={`#${target}`}
          className={active === key ? "active" : ""}
          aria-current={active === key ? "true" : undefined}
          onClick={(e) => {
            e.preventDefault();
            onSelect(key, target);
          }}
        >
          <Icon size={22} aria-hidden="true" /> {label}
        </a>
      ))}
    </nav>
  );
}

/**
 * My Schedule: the doctor's regular week and the dates that differ from it.
 * Everything the patient booking calendar offers is computed from these by
 * the API; staff with schedule:manage_any choose a doctor first.
 */
export default function DoctorSchedule() {
  const { user, can } = useAuth();
  const managesAny = can("schedule:manage_any");
  const [doctors, setDoctors] = useState([]);
  // `?doctor=` arrives from Admin > Doctors > Manage Schedule.
  const [searchParams] = useSearchParams();
  const [doctorId, setDoctorId] = useState(managesAny ? searchParams.get("doctor") ?? "" : user.doctor_id ?? "");
  const [schedule, setSchedule] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [exceptions, setExceptions] = useState([]);
  const [exceptionsLoading, setExceptionsLoading] = useState(true);
  const [exceptionsError, setExceptionsError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [section, setSection] = useState("weekly");
  const [dialog, setDialog] = useState(null); // { exception } for add/edit
  const [deleting, setDeleting] = useState(null);
  const [deleteError, setDeleteError] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!managesAny) return;
    listDoctors({ is_active: true, page_size: 100 })
      .then((res) => setDoctors(res.data.items))
      .catch(() => {});
  }, [managesAny]);

  const loadExceptions = useCallback(async () => {
    try {
      const res = await listDateExceptions(doctorId);
      setExceptions(res.data);
      setExceptionsError("");
    } catch (err) {
      setExceptionsError(getErrorMessage(err, "Could not load the exceptions"));
    } finally {
      setExceptionsLoading(false);
    }
  }, [doctorId]);

  useEffect(() => {
    if (!doctorId) return;
    let cancelled = false;
    getWeeklySchedule(doctorId)
      .then((res) => !cancelled && setSchedule(res.data))
      .catch((err) => !cancelled && setLoadError(getErrorMessage(err, "Could not load the weekly hours")));
    listDateExceptions(doctorId)
      .then((res) => {
        if (cancelled) return;
        setExceptions(res.data);
        setExceptionsError("");
      })
      .catch((err) => !cancelled && setExceptionsError(getErrorMessage(err, "Could not load the exceptions")))
      .finally(() => !cancelled && setExceptionsLoading(false));
    return () => {
      cancelled = true;
    };
  }, [doctorId, attempt]);

  if (!managesAny && !user.doctor_id) {
    return (
      <div className="doctor-schedule">
        <h1>My Schedule</h1>
        <Alert>Your login does not have a doctor profile, so there is no schedule to manage.</Alert>
      </div>
    );
  }

  const timeZone = schedule?.timezone;
  const today = timeZone ? isoDateIn(new Date(), timeZone) : isoDateIn(new Date());
  const timeZoneNote = timeZone ? `Times are in ${timeZoneLabel(timeZone)}.` : "";

  const retry = () => {
    setLoadError("");
    setExceptionsError("");
    setExceptionsLoading(true);
    setAttempt((n) => n + 1);
  };

  const jumpTo = (key, target) => {
    setSection(key);
    const element = document.getElementById(target);
    element?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    element?.querySelector("h2")?.focus({ preventScroll: true });
  };

  const saveWeek = async (days) => {
    try {
      const res = await saveWeeklySchedule(doctorId, days);
      setSchedule(res.data);
      return res.data;
    } catch (err) {
      throw new Error(scheduleError(err, "Could not save the weekly hours"), { cause: err });
    }
  };

  const saveException = async (payload) => {
    const existing = dialog.exception;
    await (existing ? updateDateException(doctorId, existing.id, payload) : createDateException(doctorId, payload));
    setDialog(null);
    setNotice(existing ? "The exception was updated." : "The exception was added.");
    await loadExceptions();
  };

  const confirmDelete = async () => {
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await deleteDateException(doctorId, deleting.id);
      setDeleting(null);
      setNotice("The exception was deleted. The weekly hours apply on that date again.");
      await loadExceptions();
    } catch (err) {
      setDeleteError(scheduleError(err, "Could not delete the exception"));
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <div className="doctor-schedule">
      <header className="schedule-head">
        <h1>{managesAny && doctorId !== user.doctor_id ? "Doctor Schedule" : "My Schedule"}</h1>
        <p className="muted">Manage your working hours and availability.</p>
      </header>

      {managesAny && (
        <label className="schedule-doctor-picker">
          Doctor
          <select
            value={doctorId}
            onChange={(e) => {
              setSchedule(null);
              setExceptions([]);
              setExceptionsLoading(true);
              setDoctorId(e.target.value);
            }}
          >
            <option value="">Select a doctor</option>
            {doctors.map((d) => (
              <option key={d.id} value={d.id}>
                {doctorName(d)} — {d.department_name}
              </option>
            ))}
          </select>
        </label>
      )}

      {doctorId && (
        <>
          <SectionNav active={section} onSelect={jumpTo} />
          <div aria-live="polite">
            <Alert kind="success">{notice}</Alert>
          </div>
          {timeZoneNote && <p className="muted small schedule-tz">{timeZoneNote}</p>}

          <div className="schedule-layout">
            {schedule ? (
              <WeeklyHoursCard key={`${doctorId}-${attempt}`} schedule={schedule} onSave={saveWeek} />
            ) : loadError ? (
              <section className="card schedule-card" role="alert" id="weekly-hours">
                <p>{loadError}</p>
                <button type="button" className="secondary" onClick={retry}>
                  Try again
                </button>
              </section>
            ) : (
              <section className="card schedule-card" id="weekly-hours" role="status" aria-label="Loading weekly hours">
                <div className="skeleton" style={{ height: 420 }} />
              </section>
            )}

            <ExceptionsCard
              exceptions={exceptions}
              loading={exceptionsLoading}
              error={exceptionsError}
              onRetry={retry}
              onAdd={() => {
                setNotice("");
                setDialog({ exception: null });
              }}
              onEdit={(exception) => {
                setNotice("");
                setDialog({ exception });
              }}
              onDelete={(exception) => {
                setNotice("");
                setDeleteError("");
                setDeleting(exception);
              }}
            />
          </div>
        </>
      )}

      {dialog && (
        <ExceptionDialog
          exception={dialog.exception}
          today={today}
          timeZoneNote={timeZoneNote}
          onSave={async (payload) => {
            try {
              await saveException(payload);
            } catch (err) {
              // Shown in the dialog; a conflict reads as one sentence.
              if (err?.response?.data?.error?.code === "SCHEDULE_CONFLICT")
                err.response.data.error.message = scheduleError(err);
              throw err;
            }
          }}
          onClose={() => setDialog(null)}
        />
      )}

      {deleting && (
        <ConfirmDialog
          title="Delete exception?"
          confirmLabel="Delete Exception"
          danger
          busy={deleteBusy}
          error={deleteError}
          onConfirm={confirmDelete}
          onCancel={() => setDeleting(null)}
        >
          <p>
            {formatMonthDay(deleting.date)} will follow the regular weekly hours again. Patients can then book any free
            time on that date.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
