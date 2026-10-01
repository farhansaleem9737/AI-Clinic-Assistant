import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Alert from "../components/Alert";
import Avatar from "../components/Avatar";
import SlotPicker from "../components/SlotPicker";
import { useAuth } from "../context/useAuth";
import { useFetch } from "../hooks/useFetch";
import { getErrorMessage } from "../services/api";
import { bookAppointment } from "../services/appointmentService";
import { getPublicDepartments } from "../services/departmentService";
import { getPublicAvailability, getPublicDoctor, getPublicDoctors } from "../services/doctorService";
import { getPatient, listPatients } from "../services/patientService";
import { addDays, formatDateTime, isoDateIn } from "../utils/datetime";
import { doctorName, formatFee } from "../utils/format";

const BOOKED_NOTICE = { state: { notice: "Your appointment is booked." } };

/**
 * Patients who chose a doctor and time on the doctor's profile land on a
 * confirmation step; everyone else gets the full booking form. Staff
 * (appointment:create) always use the form, because they pick the patient.
 */
export default function BookAppointment() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const doctorId = params.get("doctor");
  const startsAt = params.get("slot");
  if (!can("appointment:create") && doctorId && startsAt) {
    return <BookingReview key={`${doctorId} ${startsAt}`} doctorId={doctorId} startsAt={startsAt} />;
  }
  return <BookingForm />;
}

// The confirmation step: shows what will be booked. Nothing is booked until
// "Confirm appointment", and the server re-checks the time then.
function BookingReview({ doctorId, startsAt }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [taken, setTaken] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  const valid = !Number.isNaN(Date.parse(startsAt));
  const day = valid ? isoDateIn(startsAt) : null;
  const doctorFetch = useFetch(() => getPublicDoctor(doctorId), [doctorId]);
  // Free times around the chosen instant (the clinic's date can differ from
  // the browser's): confirms it is still offered and gives its timezone.
  const check = useFetch(() => getPublicAvailability(doctorId, addDays(day, -1), addDays(day, 1)), [doctorId, day], {
    enabled: valid,
  });

  const doctor = doctorFetch.data;
  const offered = check.data?.days
    .flatMap((d) => d.slots)
    .find((s) => Date.parse(s.starts_at) === Date.parse(startsAt));
  const timezone = check.data?.timezone;
  const backToProfile = `/doctors/${doctorId}#book`;

  if (!valid || doctorFetch.status === 404 || doctorFetch.status === 422) {
    return (
      <div className="card booking-review">
        <h2>Book an appointment</h2>
        <Alert>That appointment link is not valid.</Alert>
        <Link to="/doctors" className="button secondary">
          Find a doctor
        </Link>
      </div>
    );
  }
  if (doctorFetch.error || check.error) {
    return (
      <div className="card booking-review">
        <h2>Book an appointment</h2>
        <Alert>{doctorFetch.error || check.error}</Alert>
        <Link to={backToProfile} className="button secondary">
          Back to the doctor
        </Link>
      </div>
    );
  }
  if (!doctor || !check.data) return <div className="card skeleton" style={{ height: 320 }} role="status" aria-label="Loading" />;

  const name = doctorName(doctor);
  if (!offered || taken) {
    return (
      <div className="card booking-review">
        <h2>Book an appointment</h2>
        <Alert kind="warn">
          {taken
            ? "Sorry, this time was just booked by someone else. Please choose another time."
            : "This time is no longer available. Please choose another time."}
        </Alert>
        <Link to={backToProfile} className="button">
          Choose another time
        </Link>
      </div>
    );
  }

  const confirm = async () => {
    setError("");
    setSubmitting(true);
    try {
      const body = { doctor_id: doctor.id, starts_at: offered.starts_at, reason: reason.trim() || null };
      const res = await bookAppointment(body, idempotencyKey);
      navigate(`/appointments/${res.data.id}`, BOOKED_NOTICE);
    } catch (err) {
      if (err.response?.status === 409) setTaken(true);
      else setError(getErrorMessage(err, "Booking failed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="card booking-review">
      <h2>Review your appointment</h2>
      <p className="muted">Check the details below. The time is not reserved until you confirm.</p>
      <Alert>{error}</Alert>
      <div className="booking-review-doctor">
        <Avatar name={doctor.name} role="doctor" size={64} />
        <div>
          <strong>{name}</strong>
          <p className="muted">
            {doctor.specialization} · {doctor.department_name}
          </p>
        </div>
      </div>
      <dl className="booking-review-facts">
        <div>
          <dt>Date and time</dt>
          <dd>
            {formatDateTime(offered.starts_at, timezone)} <span className="muted small">({timezone})</span>
          </dd>
        </div>
        {doctor.consultation_fee != null && (
          <div>
            <dt>Consultation fee</dt>
            <dd>{formatFee(doctor.consultation_fee)}</dd>
          </div>
        )}
        <div>
          <dt>Patient</dt>
          <dd>{user.name}</dd>
        </div>
      </dl>
      <label>
        Reason for visit (optional)
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
      </label>
      <div className="row">
        <button type="button" disabled={submitting} onClick={confirm}>
          {submitting ? "Booking…" : "Confirm appointment"}
        </button>
        <Link to={backToProfile} className="button secondary">
          Change time
        </Link>
      </div>
    </div>
  );
}

// The full form: choose department, doctor and time (and, for staff, the patient).
function BookingForm() {
  const { can, user } = useAuth();
  const isStaff = can("appointment:create");
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const [departments, setDepartments] = useState([]);
  const [departmentId, setDepartmentId] = useState("");
  const [doctors, setDoctors] = useState([]);
  const [doctor, setDoctor] = useState(null);
  const [patient, setPatient] = useState(null);
  const [patientQuery, setPatientQuery] = useState("");
  const [patientMatches, setPatientMatches] = useState([]);
  // A time picked on the doctor profile arrives in the URL; the server
  // re-checks that it is still free when the booking is submitted.
  const [slot, setSlot] = useState(() => (params.get("slot") ? { starts_at: params.get("slot") } : null));
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // One key per booking attempt: resubmitting the same form cannot double-book.
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());

  useEffect(() => {
    getPublicDepartments()
      .then((res) => setDepartments(res.data.items))
      .catch(() => {});
    const preselectedDoctor = params.get("doctor");
    if (preselectedDoctor) {
      getPublicDoctor(preselectedDoctor)
        .then((res) => {
          setDoctor(res.data);
          setDepartmentId(res.data.department_id);
        })
        .catch(() => setError("That doctor is not available for booking"));
    }
    const preselectedPatient = params.get("patient");
    if (preselectedPatient && isStaff) {
      getPatient(preselectedPatient)
        .then((res) => setPatient(res.data))
        .catch(() => {});
    }
  }, [params, isStaff]);

  useEffect(() => {
    if (!departmentId) return;
    getPublicDoctors({ department_id: departmentId, page_size: 100 })
      .then((res) => setDoctors(res.data.items))
      .catch(() => {});
  }, [departmentId]);

  useEffect(() => {
    if (!isStaff || patientQuery.trim().length < 2) return;
    const timer = setTimeout(() => {
      listPatients({ q: patientQuery, is_active: true, page_size: 10 })
        .then((res) => setPatientMatches(res.data.items))
        .catch(() => {});
    }, 250);
    return () => clearTimeout(timer);
  }, [patientQuery, isStaff]);

  const submit = async () => {
    setError("");
    setSubmitting(true);
    try {
      const body = { doctor_id: doctor.id, starts_at: slot.starts_at, reason: reason || null };
      if (isStaff) body.patient_id = patient.id;
      const res = await bookAppointment(body, idempotencyKey);
      // The appointment page is the confirmation: it shows what was booked.
      navigate(`/appointments/${res.data.id}`, BOOKED_NOTICE);
    } catch (err) {
      setError(getErrorMessage(err, "Booking failed"));
      // The slot may have just been taken: let the user pick another, with a fresh key.
      setSlot(null);
      setIdempotencyKey(crypto.randomUUID());
    } finally {
      setSubmitting(false);
    }
  };

  const ready = doctor && slot && (!isStaff || patient);

  return (
    <div>
      <h2>Book an appointment</h2>
      <Alert>{error}</Alert>

      {isStaff && (
        <div className="card stack">
          <h3>1. Patient</h3>
          {patient ? (
            <div className="spread">
              <span>
                {patient.first_name} {patient.last_name} <span className="muted small">({patient.mrn}, born {patient.date_of_birth})</span>
              </span>
              <button type="button" className="secondary" onClick={() => setPatient(null)}>
                Change
              </button>
            </div>
          ) : (
            <>
              <input placeholder="Search by name, MRN or phone" value={patientQuery} onChange={(e) => setPatientQuery(e.target.value)} />
              {patientMatches.map((p) => (
                <button type="button" key={p.id} className="secondary" onClick={() => setPatient(p)}>
                  {p.first_name} {p.last_name} · {p.mrn} · {p.date_of_birth}
                </button>
              ))}
            </>
          )}
        </div>
      )}

      <div className="card stack">
        <h3>{isStaff ? "2." : "1."} Doctor</h3>
        <label>
          Department
          <select
            value={departmentId}
            onChange={(e) => {
              setDepartmentId(e.target.value);
              setDoctor(null);
              setSlot(null);
            }}
          >
            <option value="">Select department</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Doctor
          <select
            value={doctor?.id ?? ""}
            onChange={(e) => {
              setDoctor(doctors.find((d) => d.id === e.target.value) ?? null);
              setSlot(null);
            }}
          >
            <option value="">Select doctor</option>
            {doctors.map((d) => (
              <option key={d.id} value={d.id}>
                {doctorName(d)} — {d.specialization} ({formatFee(d.consultation_fee)})
              </option>
            ))}
          </select>
        </label>
      </div>

      <h3>{isStaff ? "3." : "2."} Time</h3>
      <SlotPicker doctorId={doctor?.id} selected={slot} onSelect={setSlot} />

      <div className="card stack">
        <label>
          Reason for visit (optional)
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
        </label>
        {slot && (
          <p>
            <strong>{formatDateTime(slot.starts_at, slot.timezone)}</strong> with {doctor && doctorName(doctor)}
            {isStaff && patient ? ` for ${patient.first_name} ${patient.last_name}` : ` for ${user.name}`}
          </p>
        )}
        <button type="button" disabled={!ready || submitting} onClick={submit}>
          {submitting ? "Booking…" : "Book appointment"}
        </button>
      </div>
    </div>
  );
}
