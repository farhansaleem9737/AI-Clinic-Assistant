import { CalendarX, ChevronRight, Clock, MapPin } from "lucide-react";
import { Link } from "react-router-dom";
import { formatTime } from "../../utils/datetime";
import { doctorName } from "../../utils/format";
import Avatar from "../Avatar";
import EmptyState from "../EmptyState";
import StatusBadge from "../StatusBadge";

function dayParts(iso, timeZone) {
  const parts = new Intl.DateTimeFormat("en", { month: "short", day: "numeric", weekday: "short", timeZone }).formatToParts(
    new Date(iso)
  );
  const get = (type) => parts.find((p) => p.type === type)?.value;
  return { month: get("month"), day: get("day"), weekday: get("weekday") };
}

/**
 * Appointment rows in the dashboard style. `perspective` decides who is the
 * headline: a patient sees the doctor; a doctor sees the patient; the front
 * desk sees the patient with the doctor underneath.
 */
export default function AppointmentList({ appointments, perspective = "patient", emptyText, emptyAction }) {
  if (appointments.length === 0) {
    return (
      <EmptyState icon={CalendarX} action={emptyAction}>
        {emptyText}
      </EmptyState>
    );
  }
  return (
    <div>
      {appointments.map((a) => {
        const day = dayParts(a.starts_at, a.timezone);
        const showPatient = perspective !== "patient";
        const headline = showPatient ? a.patient.name : doctorName(a.doctor);
        const subline = showPatient
          ? perspective === "front_desk"
            ? `${a.patient.mrn} · ${doctorName(a.doctor)}`
            : a.patient.mrn
          : `${a.doctor.specialization} · ${a.doctor.department_name}`;
        return (
          <Link key={a.id} to={`/appointments/${a.id}`} className="appt-item">
            <span className="day">
              <span className="month">{day.month}</span>
              <span className="num">{day.day}</span>
              <span className="dow">{day.weekday}</span>
            </span>
            <Avatar name={showPatient ? a.patient.name : a.doctor.name} size={48} />
            <div className="who">
              <strong>{headline}</strong>
              <div className="muted small">{subline}</div>
              <div className="meta">
                <span>
                  <Clock size={14} aria-hidden="true" />
                  {formatTime(a.starts_at, a.timezone)}
                </span>
                {a.doctor.room_number && (
                  <span>
                    <MapPin size={14} aria-hidden="true" />
                    Room {a.doctor.room_number}
                  </span>
                )}
              </div>
            </div>
            <StatusBadge status={a.status} />
            <ChevronRight size={18} className="muted" aria-hidden="true" />
          </Link>
        );
      })}
    </div>
  );
}
