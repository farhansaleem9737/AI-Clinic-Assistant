import { ArrowLeft, ArrowRight, Briefcase, Building2, CheckCircle2, CircleAlert, CircleDollarSign } from "lucide-react";
import { bookingAvailability } from "../../utils/doctors";
import { CURRENCY, doctorName } from "../../utils/format";
import Alert from "../Alert";
import Avatar from "../Avatar";
import DateTimePicker from "../doctors/DateTimePicker";

// The full-width summary of the doctor chosen in step 1. Every field comes
// from the API; the clinic has no address on record, so the department is
// shown as the location rather than an invented address.
function DoctorSummary({ doctor }) {
  const badge = bookingAvailability(doctor.availability);
  return (
    <section className="card doctor-summary-card" aria-label="Selected doctor">
      <div className="doctor-summary-main">
        <Avatar name={doctor.name} role="doctor" src={doctor.photo_url} size={112} alt={doctorName(doctor)} />
        <div className="doctor-summary-text">
          <h3>{doctorName(doctor)}</h3>
          <p className="muted">
            {doctor.specialization} · {doctor.department_name}
          </p>
          <div className="doctor-summary-facts">
            <span>
              <Briefcase size={22} aria-hidden="true" /> {doctor.years_of_experience} years experience
            </span>
            <span>
              <CircleDollarSign size={22} aria-hidden="true" />
              {doctor.consultation_fee == null ? (
                <span className="muted">Fee not available</span>
              ) : (
                <span className="fee">
                  <strong>{CURRENCY ? `${CURRENCY} ${doctor.consultation_fee}` : doctor.consultation_fee}</strong>
                  <small className="muted">Consultation fee</small>
                </span>
              )}
            </span>
          </div>
        </div>
      </div>
      <div className="doctor-summary-side">
        <p className="doctor-summary-location">
          <Building2 size={24} aria-hidden="true" />
          <span>
            {doctor.department_name}
            <small className="muted">Department</small>
          </span>
        </p>
        <span className={`badge with-icon ${badge.tone}`}>
          {badge.tone === "ok" ? <CheckCircle2 size={15} aria-hidden="true" /> : <CircleAlert size={15} aria-hidden="true" />}
          {badge.label}
        </span>
      </div>
    </section>
  );
}

/**
 * Step 2: a date and a free time for the chosen doctor, from real
 * availability. `notice` explains why the user is back here (e.g. the time
 * was just taken); `refreshKey` reloads the times.
 */
export default function DateTimeStep({ doctor, slot, onSelect, notice, refreshKey, onBack, onContinue }) {
  return (
    <>
      <h2 id="booking-step-title" className="sr-only">
        Select Date &amp; Time
      </h2>
      <DoctorSummary doctor={doctor} />
      <Alert kind="warn">{notice}</Alert>

      <DateTimePicker doctorId={doctor.id} selected={slot} onSelect={onSelect} refreshKey={refreshKey} layout="cards" />

      <div className="card booking-footer-card">
        <p className="sr-only" aria-live="polite">
          {slot ? "A time is selected. Continue to confirm." : "Choose a date, then a time."}
        </p>
        <div className="booking-actions plain">
          <button type="button" className="secondary" onClick={onBack}>
            <ArrowLeft size={17} aria-hidden="true" /> Back
          </button>
          <button type="button" disabled={!slot} onClick={onContinue}>
            Continue <ArrowRight size={17} aria-hidden="true" />
          </button>
        </div>
      </div>
    </>
  );
}
