import { CalendarDays, CalendarPlus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/useAuth";
import { formatDateTime } from "../../utils/datetime";
import { doctorName } from "../../utils/format";
import DateTimePicker from "./DateTimePicker";

/**
 * "Book an Appointment" on the doctor profile: pick a date, then a time,
 * then continue to the confirmation step. Every date and time shown comes
 * from the API; nothing is booked here, and the booking itself re-checks
 * that the time is still free.
 */
export default function BookingPanel({ doctor, headingRef }) {
  const { user, can } = useAuth();
  const navigate = useNavigate();
  const mayBook = !user || can("appointment:create") || can("appointment:create_own");
  const name = doctorName(doctor);
  const [slot, setSlot] = useState(null);

  const book = () => navigate(`/appointments/book?${new URLSearchParams({ doctor: doctor.id, slot: slot.starts_at })}`);

  return (
    <section className="card booking-panel" id="book" aria-labelledby="book-heading">
      <div className="booking-panel-head">
        <CalendarDays className="icon" size={24} aria-hidden="true" />
        <h2 id="book-heading" ref={headingRef} tabIndex={-1}>
          Book an Appointment
        </h2>
      </div>
      <p className="muted">Select a date and time to book an appointment with {name}.</p>

      <DateTimePicker doctorId={doctor.id} selected={slot} onSelect={setSlot} />

      <div className="booking-footer">
        {mayBook ? (
          <>
            <button type="button" className="large" disabled={!slot} onClick={book}>
              <CalendarPlus size={18} aria-hidden="true" /> Book appointment
            </button>
            <p className="muted small" aria-live="polite">
              {slot && (
                <>
                  Selected: <strong>{formatDateTime(slot.starts_at, slot.timezone)}</strong>.{" "}
                </>
              )}
              You will be able to confirm your appointment details on the next step.
              {!user && " You will be asked to sign in or create an account first."}
            </p>
          </>
        ) : (
          <p className="muted small">Online booking is available to patients.</p>
        )}
      </div>
    </section>
  );
}
