import { ArrowLeft, ArrowRight, CalendarDays, Clock, CreditCard, Hourglass, Info, MapPin, MessageCircle, Ticket } from "lucide-react";
import { useState } from "react";
import { useFetch } from "../../hooks/useFetch";
import { useRealtimeEvent } from "../../hooks/useRealtime";
import { getErrorMessage, isNetworkError } from "../../services/api";
import { bookAppointment } from "../../services/appointmentService";
import { bookingKey, bookingScope, forgetBookingKey } from "../../services/bookingKeys";
import { getPublicAvailability } from "../../services/doctorService";
import { durationMinutes } from "../../utils/appointments";
import { addDays, formatLongDate, formatSlotTime, isoDateIn, timeZoneLabel } from "../../utils/datetime";
import { doctorName, formatFee } from "../../utils/format";
import Alert from "../Alert";
import Avatar from "../Avatar";

export const REASON_MAX = 500;
const SLOT_TAKEN = "Sorry, this time was just booked by someone else. Please choose another time.";
const SLOT_GONE = "This time is no longer available. Please choose another time.";
const DOCTOR_GONE = "This doctor is no longer taking appointments. Please choose another doctor.";
const CHECKING = "We're checking whether your appointment was created. Please wait before trying again.";
const UNCERTAIN =
  "We couldn't confirm the booking. Pressing Confirm again is safe: it will not create a second appointment.";
// No answer, or a server fault: the booking may or may not have been saved.
const ambiguous = (err) => isNetworkError(err) || [500, 502, 504].includes(err?.response?.status);
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
// Automatic token (D120): the assigned time went meanwhile; the next one is shown for review, never booked silently.
const nextTimeNotice = (next, timezone) =>
  next?.starts_at
    ? `Sorry, that time was just taken. The next available time is ${formatSlotTime(next.starts_at, timezone)}: please review it and confirm again.`
    : "Sorry, that time was just taken and there are no more free times that day. Please choose another date.";

function DetailRow({ icon: Icon, label, children }) {
  return (
    <div className="detail-row">
      <dt>
        <Icon size={22} aria-hidden="true" /> {label}
      </dt>
      <dd>{children}</dd>
    </div>
  );
}

/**
 * Step 3: review, then book. The chosen time is re-checked against live
 * availability first (it may have come from a link, or been taken since);
 * the server checks again, under its booking locks, when "Confirm
 * Appointment" is pressed. Nothing is booked before that. One
 * Idempotency-Key per intended booking (services/bookingKeys.js), kept across
 * leaving and returning to this step, makes a double click, a retry or a lost
 * answer return the same appointment instead of a second one. After an
 * ambiguous failure the step asks the server once more with the same key.
 *
 * `reason` lives in the wizard, so it survives going back to step 2.
 */
export default function ConfirmStep({
  doctor,
  slot,
  reason,
  onReasonChange,
  onBack,
  onUnavailable,
  onDoctorGone,
  onBooked,
  // Staff booking on behalf of this patient (D82); omitted when patients book for themselves.
  patient,
}) {
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const scope = bookingScope({ patientId: patient?.id, doctorId: doctor.id, startsAt: slot.starts_at });
  const [idempotencyKey] = useState(() => bookingKey(scope));
  const [checking, setChecking] = useState(false);

  const day = isoDateIn(slot.starts_at);
  // The clinic's date can differ from the browser's: look one day either side.
  const check = useFetch(() => getPublicAvailability(doctor.id, addDays(day, -1), addDays(day, 1)), [doctor.id, day]);
  // Live (D122): if this doctor's times change while the user reads this page, check again
  // in the background; a time taken meanwhile shows "no longer available". The reason
  // typed so far is kept (it lives in the wizard). The booking itself is still checked by the server.
  useRealtimeEvent(["availability."], (event) => {
    if (submitting) return;
    if (!event.payload || event.payload.doctor_id === doctor.id) check.reload();
  });
  const offered = check.data?.days
    .flatMap((d) => d.slots)
    .find((s) => Date.parse(s.starts_at) === Date.parse(slot.starts_at));
  const timezone = check.data?.timezone;
  const doctorGone = check.status === 404;
  const auto = slot.mode === "auto";

  const confirm = async () => {
    if (submitting || !offered) return; // one request at a time
    setError("");
    setSubmitting(true);
    try {
      const body = {
        doctor_id: doctor.id,
        starts_at: offered.starts_at,
        reason: reason.trim() || null,
        booking_mode: auto ? "auto" : "custom",
      };
      if (patient) body.patient_id = patient.id;
      let res;
      try {
        res = await bookAppointment(body, idempotencyKey);
      } catch (first) {
        if (!ambiguous(first)) throw first;
        // Saved or not? Ask again with the same key: the server returns the
        // saved appointment, or books it now; never a second one.
        setChecking(true);
        await pause(1500);
        res = await bookAppointment(body, idempotencyKey);
      }
      forgetBookingKey(scope);
      onBooked(res.data);
    } catch (err) {
      setSubmitting(false);
      setChecking(false);
      const code = err.response?.data?.error?.code;
      if (err.response?.status === 409 || code === "DOCTOR_UNAVAILABLE") forgetBookingKey(scope);
      if (err.response?.status === 409 && auto && code === "SLOT_UNAVAILABLE") {
        onUnavailable(nextTimeNotice(err.response.data.error.details?.next_available, timezone));
      } else if (err.response?.status === 409) onUnavailable(SLOT_TAKEN);
      else if (code === "DOCTOR_UNAVAILABLE") onDoctorGone(DOCTOR_GONE);
      else if (ambiguous(err)) setError(UNCERTAIN);
      else setError(getErrorMessage(err, "We couldn't book the appointment. Please try again."));
    }
  };

  let body;
  if (doctorGone) {
    body = (
      <div className="booking-problem">
        <Alert kind="warn">{DOCTOR_GONE}</Alert>
        <button type="button" onClick={() => onDoctorGone(DOCTOR_GONE)}>
          Choose another doctor
        </button>
      </div>
    );
  } else if (check.error) {
    body = <Alert>{check.error}</Alert>;
  } else if (!check.data || check.loading) {
    body = <div className="skeleton" style={{ height: 300 }} role="status" aria-label="Checking that this time is still free" />;
  } else if (!offered) {
    body = (
      <div className="booking-problem">
        <Alert kind="warn">{SLOT_GONE}</Alert>
        <button type="button" onClick={() => onUnavailable(SLOT_GONE)}>
          Choose another time
        </button>
      </div>
    );
  } else {
    body = (
      <div className="confirm-columns">
        <section className="confirm-panel" aria-labelledby="confirm-details-title">
          <div className="card-title">
            <CalendarDays className="icon" size={26} aria-hidden="true" />
            <h3 id="confirm-details-title">Appointment Details</h3>
          </div>
          <div className="confirm-doctor">
            <Avatar name={doctor.name} role="doctor" src={doctor.photo_url} size={124} alt={doctorName(doctor)} />
            <div>
              <strong>{doctorName(doctor)}</strong>
              <span>{doctor.specialization}</span>
              <span>{doctor.department_name}</span>
            </div>
          </div>
          <dl className="detail-rows">
            <DetailRow icon={CalendarDays} label="Date">
              {formatLongDate(offered.starts_at, timezone)}
            </DetailRow>
            <DetailRow icon={Clock} label={auto ? "Estimated start time" : "Time"}>
              {formatSlotTime(offered.starts_at, timezone)}
              <small className="muted">
                {auto ? "Automatic token: the next available time" : "Custom time"} · {timeZoneLabel(timezone, offered.starts_at)}
              </small>
            </DetailRow>
            <DetailRow icon={Hourglass} label="Duration">
              About {durationMinutes(offered)} minutes
            </DetailRow>
            {slot.queue_position ? (
              <DetailRow icon={Ticket} label="Queue no.">
                #{slot.queue_position}
                <small className="muted">Estimated place in the doctor's day; it can move up if an earlier booking is cancelled</small>
              </DetailRow>
            ) : null}
            <DetailRow icon={MapPin} label="Location">
              {doctor.department_name}
              <small className="muted">Department</small>
            </DetailRow>
            <DetailRow icon={CreditCard} label="Consultation fee">
              {doctor.consultation_fee == null ? <span className="muted">Fee not available</span> : formatFee(doctor.consultation_fee)}
            </DetailRow>
          </dl>
        </section>

        <section className="confirm-panel reason-panel" aria-labelledby="confirm-reason-title">
          <div className="reason-body">
            <div className="card-title">
              <MessageCircle className="icon" size={26} aria-hidden="true" />
              <div>
                <h3 id="confirm-reason-title">Reason for Appointment</h3>
                <p className="muted small" id="confirm-reason-help">
                  {patient ? "Let the doctor know the reason for the visit (optional)." : "Let the doctor know the reason for your visit (optional)."}
                </p>
              </div>
            </div>
            <textarea
              aria-labelledby="confirm-reason-title"
              aria-describedby="confirm-reason-help confirm-reason-count"
              placeholder="Enter reason or additional notes..."
              value={reason}
              maxLength={REASON_MAX}
              onChange={(e) => onReasonChange(e.target.value.slice(0, REASON_MAX))}
              disabled={submitting}
            />
            <p className="reason-count muted small" id="confirm-reason-count">
              {reason.length}/{REASON_MAX}
            </p>
          </div>
          <div className="verify-note">
            <Info className="verify-icon" size={26} aria-hidden="true" />
            <div>
              <h4>Please verify your details</h4>
              <p>Make sure the doctor, date, time and other information are correct before confirming your appointment.</p>
            </div>
          </div>
        </section>
      </div>
    );
  }

  return (
    <>
      <section className="card confirm-card" aria-labelledby="booking-step-title">
        <h2 id="booking-step-title">{patient ? "Confirm the appointment" : "Confirm your appointment"}</h2>
        <p className="muted confirm-lead">Please review the details below before confirming the appointment.</p>
        {patient && (
          <p className="alert info on-behalf-note">
            Booking on behalf of{" "}
            <strong>
              {patient.first_name} {patient.last_name}
            </strong>{" "}
            (MRN {patient.mrn}). The appointment is recorded for this patient; you are recorded as the person who booked it.
          </p>
        )}
        {body}
        {checking && <Alert kind="info">{CHECKING}</Alert>}
        <Alert>{error}</Alert>
      </section>

      <div className="card booking-footer-card">
        <p className="sr-only" aria-live="polite">
          {checking ? CHECKING : submitting ? "Booking your appointment…" : ""}
        </p>
        <div className="booking-actions plain">
          <button type="button" className="secondary" onClick={onBack} disabled={submitting}>
            <ArrowLeft size={17} aria-hidden="true" /> Back
          </button>
          <button type="button" onClick={confirm} disabled={submitting || !offered} aria-busy={submitting}>
            {submitting ? (
              <>
                <span className="spinner" aria-hidden="true" /> Booking…
              </>
            ) : (
              <>
                Confirm Appointment <ArrowRight size={17} aria-hidden="true" />
              </>
            )}
          </button>
        </div>
      </div>
    </>
  );
}
