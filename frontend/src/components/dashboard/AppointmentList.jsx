import { ArrowRight, CalendarX, Clock, MapPin } from "lucide-react";
import { Link } from "react-router-dom";
import { dayParts, formatDateTime, formatTime } from "../../utils/datetime";
import { doctorName } from "../../utils/format";
import Avatar from "../Avatar";
import EmptyState from "../EmptyState";
import StatusBadge from "../StatusBadge";

/**
 * Appointment rows in the dashboard style. `perspective` decides who is the
 * headline: a patient sees the doctor; a doctor sees the patient; the front
 * desk sees the patient with the doctor underneath. Changing or cancelling
 * happens on the appointment page, which "View details" opens.
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
        const when = formatDateTime(a.starts_at, a.timezone);
        return (
          <article key={a.id} className="appt-item" aria-label={`${headline}, ${when}`}>
            <span className="day" aria-hidden="true">
              <span className="month">{day.month}</span>
              <span className="num">{day.day}</span>
              <span className="dow">{day.weekday}</span>
            </span>
            <Avatar
              name={showPatient ? a.patient.name : a.doctor.name}
              role={showPatient ? undefined : "doctor"}
              size={52}
              src={showPatient ? undefined : a.doctor.photo_url}
            />
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
            <div className="appt-side">
              <StatusBadge status={a.status} />
              <Link to={`/appointments/${a.id}`} className="button secondary small">
                View details<span className="sr-only">: {headline}, {when}</span>
                <ArrowRight size={14} aria-hidden="true" />
              </Link>
            </div>
          </article>
        );
      })}
    </div>
  );
}
