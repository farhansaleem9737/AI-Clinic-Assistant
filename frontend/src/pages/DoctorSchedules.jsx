import { Briefcase, CalendarDays, CalendarPlus, ChevronDown, ChevronLeft, ChevronRight, CircleDollarSign, Clock, Info } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Alert from "../components/Alert";
import Avatar from "../components/Avatar";
import DateSelect from "../components/DateSelect";
import EmptyState from "../components/EmptyState";
import { useAuth } from "../context/useAuth";
import { useFetch } from "../hooks/useFetch";
import { getErrorMessage } from "../services/api";
import { getPublicDepartments } from "../services/departmentService";
import { getPublicDoctors, getPublicSpecializations } from "../services/doctorService";
import { getDaySchedule } from "../services/scheduleService";
import { addDays, formatSlotTime, formatWallTime } from "../utils/datetime";
import { readDay } from "../utils/doctorAppointments";
import { CURRENCY, doctorName } from "../utils/format";

// What each slot / day status says. Colour repeats the words, never replaces them.
const SLOT_LABELS = {
  available: "Available",
  booked: "Booked",
  blocked: "Unavailable",
  break: "Break",
  past: "Past",
  beyond_horizon: "Not yet bookable",
};
const DAY_LABELS = {
  available: "Available",
  fully_booked: "Fully Booked",
  off: "Off",
  unavailable: "Unavailable",
  past: "Past",
};
const hours = (ranges) => ranges.map((r) => `${formatWallTime(r.start_time)} – ${formatWallTime(r.end_time)}`).join(", ");
const utcDay = (isoDate, options) =>
  new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" }).format(new Date(`${isoDate}T00:00:00Z`));

function availabilityBadge(board) {
  const day = board.week.find((d) => d.date === board.date);
  if (board.available_slots > 0)
    return { tone: "ok", label: board.date === board.today ? "Available Today" : "Available on Selected Date" };
  return { tone: day?.status === "fully_booked" ? "warn" : "neutral", label: DAY_LABELS[day?.status] ?? "Unavailable" };
}

function DoctorSummary({ doctor, board }) {
  const badge = board && availabilityBadge(board);
  return (
    <section className="card ds-summary" aria-label="Selected doctor">
      <Avatar name={doctor.name} role="doctor" src={doctor.photo_url} size={116} alt={doctorName(doctor)} />
      <div className="ds-identity">
        <h2>{doctorName(doctor)}</h2>
        <p className="muted">{doctor.specialization}</p>
        <p className="muted">{doctor.department_name}</p>
      </div>
      <div className="ds-fact">
        <Briefcase size={26} aria-hidden="true" />
        <span>
          <strong>{doctor.years_of_experience} years</strong>
          <small className="muted">Experience</small>
        </span>
      </div>
      <div className="ds-fact">
        <CircleDollarSign size={26} aria-hidden="true" />
        <span>
          <strong>
            {doctor.consultation_fee == null ? "Not set" : CURRENCY ? `${CURRENCY} ${doctor.consultation_fee}` : doctor.consultation_fee}
          </strong>
          <small className="muted">Consultation Fee</small>
        </span>
      </div>
      {badge && (
        <div className={`ds-availability ${badge.tone}`}>
          <strong>
            <span className="dot" aria-hidden="true" /> {badge.label}
          </strong>
          <small>{board.working_hours.length ? hours(board.working_hours) : "No working hours scheduled"}</small>
        </div>
      )}
    </section>
  );
}

function WeekStrip({ board, onPick }) {
  return (
    <div className="card ds-week" role="group" aria-label="Week">
      {board.week.map((d) => {
        const selected = d.date === board.date;
        return (
          <button
            key={d.date}
            type="button"
            className={`ds-day ${d.status}${selected ? " selected" : ""}`}
            aria-pressed={selected}
            aria-label={`${utcDay(d.date, { weekday: "long", month: "long", day: "numeric" })}: ${DAY_LABELS[d.status]}`}
            onClick={() => onPick(d.date)}
          >
            <span>{utcDay(d.date, { weekday: "short" })}</span>
            <strong>{utcDay(d.date, { month: "short", day: "numeric" })}</strong>
            <small>{DAY_LABELS[d.status]}</small>
          </button>
        );
      })}
    </div>
  );
}

function WorkingHours({ board }) {
  return (
    <section className="card ds-hours" aria-labelledby="ds-hours-title">
      <div className="pd-card-head">
        <Clock className="pd-icon" size={30} aria-hidden="true" />
        <div>
          <h2 id="ds-hours-title">Doctor&apos;s Working Hours</h2>
          <p className="muted">{utcDay(board.date, { dateStyle: "full" })}</p>
        </div>
      </div>
      <dl className="ds-hours-list">
        <div>
          <dt>Working Hours</dt>
          <dd>{board.working_hours.length ? hours(board.working_hours) : "No working hours scheduled."}</dd>
        </div>
        <div>
          <dt>Appointment Duration</dt>
          <dd>{board.slot_minutes} minutes</dd>
        </div>
        <div>
          <dt>Break Time</dt>
          <dd>{board.breaks.length ? hours(board.breaks) : "No scheduled breaks."}</dd>
        </div>
        <div>
          <dt>Total Slots</dt>
          <dd>
            {board.total_slots} slot{board.total_slots === 1 ? "" : "s"}
            <small className="muted"> · {board.available_slots} still available</small>
          </dd>
        </div>
      </dl>
    </section>
  );
}

function SlotGrid({ board, selected, onSelect }) {
  return (
    <section className="card ds-slots" aria-labelledby="ds-slots-title">
      <div className="pd-card-head ds-slots-head">
        <CalendarDays className="pd-icon" size={30} aria-hidden="true" />
        <h2 id="ds-slots-title">Available Time Slots</h2>
        <ul className="ds-legend" aria-label="Legend">
          <li className="available">Available</li>
          <li className="booked">Booked</li>
          <li className="unavailable">Unavailable</li>
        </ul>
      </div>
      {board.slots.length === 0 ? (
        <EmptyState icon={CalendarDays}>No time slots on this date.</EmptyState>
      ) : (
        <div className="ds-slot-grid" role="group" aria-label="Time slots">
          {board.slots.map((slot) => {
            const time = formatSlotTime(slot.starts_at, board.timezone);
            if (slot.status !== "available") {
              return (
                <span key={slot.starts_at} className={`ds-slot ${slot.status}`}>
                  {time}
                  <small>{SLOT_LABELS[slot.status]}</small>
                </span>
              );
            }
            const isSelected = selected === slot.starts_at;
            return (
              <button
                key={slot.starts_at}
                type="button"
                className={`ds-slot available${isSelected ? " selected" : ""}`}
                aria-pressed={isSelected}
                aria-label={`${time}, available`}
                onClick={() => onSelect(isSelected ? null : slot.starts_at)}
              >
                {time}
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}

/**
 * Doctor Schedules for front-desk staff (D83): pick a doctor (filtered by
 * department and specialization) and a date, see the real day — hours,
 * breaks, booked and free slots — and hand a free time to the booking
 * wizard. Nothing is booked here. The URL keeps doctor, date and filters.
 */
export default function DoctorSchedules() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const doctorId = params.get("doctor") ?? "";
  const departmentId = params.get("department") ?? "";
  const specialization = params.get("specialization") ?? "";
  const date = readDay(params.get("date"));
  const patientId = params.get("patient");

  const [board, setBoard] = useState(null);
  const [boardError, setBoardError] = useState("");
  const [attempt, setAttempt] = useState(0);
  // The selected time belongs to one doctor and date; it is dropped when either changes.
  const [pick, setPick] = useState({ key: "", slot: null });
  const key = `${doctorId}|${date ?? ""}`;
  const selectedSlot = pick.key === key ? pick.slot : null;

  const departments = useFetch(getPublicDepartments, []);
  const specializations = useFetch(() => getPublicSpecializations(departmentId || undefined), [departmentId]);
  const doctors = useFetch(
    () =>
      getPublicDoctors({
        department_id: departmentId || undefined,
        specialization: specialization || undefined,
        sort: "name_asc",
        page_size: 100,
      }),
    [departmentId, specialization]
  );
  const doctorList = doctors.data?.items ?? [];
  const doctor = doctorList.find((d) => d.id === doctorId) ?? null;
  const excluded = Boolean(doctorId && doctors.data && !doctors.loading && !doctor);

  const update = (changes) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setParams(next, { replace: true });
  };

  useEffect(() => {
    if (!doctorId || excluded) return;
    let cancelled = false;
    getDaySchedule(doctorId, date ?? undefined)
      .then((res) => {
        if (cancelled) return;
        setBoard(res.data);
        setBoardError("");
      })
      .catch((err) => {
        if (cancelled) return;
        setBoard(null);
        setBoardError(getErrorMessage(err, "Could not load this schedule"));
      });
    return () => {
      cancelled = true;
    };
  }, [doctorId, date, excluded, attempt]);

  const shownBoard = board && board.doctor_id === doctorId && (!date || board.date === date) ? board : null;
  const day = date ?? shownBoard?.date ?? null;
  const goTo = (value) => update({ date: value });
  const book = () => {
    const query = new URLSearchParams({ doctor: doctorId, slot: selectedSlot });
    if (patientId) query.set("patient", patientId);
    navigate(`/appointments/book?${query}`);
  };

  return (
    <div className="doctor-schedules">
      <header className="schedule-head ds-head">
        <div>
          <h1>Doctor Schedules</h1>
          <p className="muted">View doctor availability and book appointments.</p>
        </div>
        {can("schedule:manage_any") && doctorId && (
          <Link to="/schedule" className="button secondary">
            Manage working hours
          </Link>
        )}
      </header>

      <div className="ds-filters">
        <label className="ds-filter ds-doctor-filter">
          {doctor ? <Avatar name={doctor.name} role="doctor" src={doctor.photo_url} size={36} /> : null}
          <span className="sr-only">Doctor</span>
          <select value={doctorId} onChange={(e) => update({ doctor: e.target.value })} aria-label="Doctor">
            <option value="">{doctors.loading ? "Loading doctors…" : "Select a doctor"}</option>
            {doctorList.map((d) => (
              <option key={d.id} value={d.id}>
                {doctorName(d)}
              </option>
            ))}
          </select>
          <ChevronDown size={16} aria-hidden="true" />
        </label>
        <label className="ds-filter">
          <span className="ds-filter-label">Department</span>
          <select value={departmentId} onChange={(e) => update({ department: e.target.value, specialization: "" })}>
            <option value="">All Departments</option>
            {(departments.data?.items ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label className="ds-filter">
          <span className="ds-filter-label">Specialization</span>
          <select value={specialization} onChange={(e) => update({ specialization: e.target.value })}>
            <option value="">All Specializations</option>
            {(specializations.data ?? []).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <DateSelect value={day} onChange={goTo} />
        <div className="ds-nav" role="group" aria-label="Change date">
          <button type="button" className="secondary" aria-label="Previous day" disabled={!day} onClick={() => goTo(addDays(day, -1))}>
            <ChevronLeft size={18} aria-hidden="true" />
          </button>
          <button type="button" className="secondary" disabled={!shownBoard} onClick={() => goTo(shownBoard.today)}>
            Today
          </button>
          <button type="button" className="secondary" aria-label="Next day" disabled={!day} onClick={() => goTo(addDays(day, 1))}>
            <ChevronRight size={18} aria-hidden="true" />
          </button>
        </div>
      </div>

      {doctors.error && <Alert>{doctors.error}</Alert>}
      {excluded && (
        <Alert kind="warn">The selected doctor does not match these filters. Choose a doctor from the list.</Alert>
      )}
      {doctors.data && !doctors.loading && doctorList.length === 0 && (
        <div className="card">
          <EmptyState icon={CalendarDays}>No doctors match these filters.</EmptyState>
        </div>
      )}

      {!doctorId || excluded ? (
        doctorList.length > 0 && (
          <div className="card">
            <EmptyState icon={CalendarDays}>Select a doctor to see their schedule.</EmptyState>
          </div>
        )
      ) : boardError ? (
        <div className="card" role="alert">
          <p>{boardError}</p>
          <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </div>
      ) : !shownBoard || !doctor ? (
        <div role="status" aria-label="Loading schedule">
          <div className="card skeleton" style={{ height: 150 }} />
          <div className="card skeleton" style={{ height: 320 }} />
        </div>
      ) : (
        <>
          <DoctorSummary doctor={doctor} board={shownBoard} />
          <WeekStrip board={shownBoard} onPick={goTo} />
          <div className="ds-columns">
            <WorkingHours board={shownBoard} />
            <div className="ds-right">
              <SlotGrid board={shownBoard} selected={selectedSlot} onSelect={(slot) => setPick({ key, slot })} />
              <div className="ds-info" role="status">
                <Info className="ds-info-icon" size={24} aria-hidden="true" />
                <p>
                  Showing availability for {doctorName(doctor)} on {utcDay(shownBoard.date, { dateStyle: "full" })}.
                  <br />
                  Booked slots are shown for reference. Select an available time to book an appointment.
                </p>
                {can("appointment:create") && (
                  <button type="button" onClick={book} disabled={!selectedSlot}>
                    <CalendarPlus size={18} aria-hidden="true" /> Book Appointment
                  </button>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
