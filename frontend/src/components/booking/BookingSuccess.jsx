import { CheckCircle2 } from "lucide-react";
import { Link } from "react-router-dom";
import { appointmentReference } from "../../utils/appointments";
import { formatLongDate, formatSlotTime } from "../../utils/datetime";
import { doctorName } from "../../utils/format";
import StatusBadge from "../StatusBadge";

/**
 * Shown only after the API has saved the appointment, from its response:
 * the permanent reference, and (D120) the estimated place in the doctor's day.
 */
export default function BookingSuccess({ appointment, onBehalf = false }) {
  const auto = appointment.booking_mode === "auto";
  return (
    <div className="booking-success" role="status">
      <CheckCircle2 className="success-icon" size={48} aria-hidden="true" />
      <h2 id="booking-step-title">
        {onBehalf ? `Appointment booked for ${appointment.patient.name}` : "Your appointment is booked"}
      </h2>
      <p>
        <strong>{doctorName(appointment.doctor)}</strong> · {appointment.doctor.specialization}
      </p>
      <p>
        {formatLongDate(appointment.starts_at, appointment.timezone)} at{" "}
        {formatSlotTime(appointment.starts_at, appointment.timezone)}{" "}
        <span className="muted small">({appointment.timezone})</span>
      </p>
      <dl className="booking-success-facts">
        <div>
          <dt>Reference</dt>
          <dd>{appointmentReference(appointment.id)}</dd>
        </div>
        {appointment.queue_position ? (
          <div>
            <dt>Queue no.</dt>
            <dd>
              #{appointment.queue_position} <span className="muted small">(estimated)</span>
            </dd>
          </div>
        ) : null}
        {appointment.duration_minutes ? (
          <div>
            <dt>Duration</dt>
            <dd>About {appointment.duration_minutes} minutes</dd>
          </div>
        ) : null}
      </dl>
      <p className="muted small booking-success-note">
        {auto ? "This was the next available time. " : ""}
        The time is an estimated start. Check in at reception when you arrive: you'll get your token for the day there.
      </p>
      <p className="booking-success-status">
        Status: <StatusBadge status={appointment.status} />
      </p>
      <div className="booking-success-actions">
        <Link to={`/appointments/${appointment.id}`} className="button">
          View Appointment Details
        </Link>
        {onBehalf ? (
          <Link to={`/patients/${appointment.patient.id}`} className="button secondary">
            Patient Record
          </Link>
        ) : (
          <Link to="/appointments" className="button secondary">
            My Appointments
          </Link>
        )}
      </div>
    </div>
  );
}
