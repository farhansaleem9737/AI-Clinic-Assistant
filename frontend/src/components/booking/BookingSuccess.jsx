import { CheckCircle2 } from "lucide-react";
import { Link } from "react-router-dom";
import { formatLongDate, formatSlotTime } from "../../utils/datetime";
import { doctorName } from "../../utils/format";
import StatusBadge from "../StatusBadge";

/** Shown only after the API has saved the appointment, from its response. */
export default function BookingSuccess({ appointment }) {
  return (
    <div className="booking-success" role="status">
      <CheckCircle2 className="success-icon" size={48} aria-hidden="true" />
      <h2 id="booking-step-title">Your appointment is booked</h2>
      <p>
        <strong>{doctorName(appointment.doctor)}</strong> · {appointment.doctor.specialization}
      </p>
      <p>
        {formatLongDate(appointment.starts_at, appointment.timezone)} at{" "}
        {formatSlotTime(appointment.starts_at, appointment.timezone)}{" "}
        <span className="muted small">({appointment.timezone})</span>
      </p>
      <p className="booking-success-status">
        Status: <StatusBadge status={appointment.status} />
      </p>
      <div className="booking-success-actions">
        <Link to={`/appointments/${appointment.id}`} className="button">
          View Appointment Details
        </Link>
        <Link to="/appointments" className="button secondary">
          My Appointments
        </Link>
      </div>
    </div>
  );
}
