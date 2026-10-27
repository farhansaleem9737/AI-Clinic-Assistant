import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import Alert from "../components/Alert";
import BookingStepper from "../components/booking/BookingStepper";
import BookingSuccess from "../components/booking/BookingSuccess";
import ConfirmStep from "../components/booking/ConfirmStep";
import DateTimeStep from "../components/booking/DateTimeStep";
import DoctorPicker from "../components/booking/DoctorPicker";
import SlotPicker from "../components/SlotPicker";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { bookAppointment } from "../services/appointmentService";
import { getPublicDepartments } from "../services/departmentService";
import { getPublicDoctor, getPublicDoctors } from "../services/doctorService";
import { getPatient, listPatients } from "../services/patientService";
import { formatDateTime } from "../utils/datetime";
import { doctorName, formatFee } from "../utils/format";

const BOOKED_NOTICE = { state: { notice: "Your appointment is booked." } };

/**
 * Patients book in three steps: Select Doctor → Date & Time → Confirm.
 * Staff (appointment:create) use the full form, because they pick the patient.
 */
export default function BookAppointment() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  if (can("appointment:create")) return <BookingForm />;
  // A new link (e.g. "Book" on another doctor) starts a fresh booking.
  return <BookingWizard key={params.toString()} />;
}

/**
 * The patient booking wizard. `?doctor=<id>` (from the directory or a
 * profile) starts at step 2 with that doctor, once the API confirms it is
 * bookable; `&slot=<time>` (chosen on the profile) goes straight to the
 * confirm step, which re-checks the time. Nothing is booked before
 * "Confirm Booking".
 */
function BookingWizard() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const handoffDoctorId = params.get("doctor");
  const handoffSlot = params.get("slot");

  const [step, setStep] = useState(1);
  const [doctor, setDoctor] = useState(null);
  const [slot, setSlot] = useState(null);
  // The optional reason typed on step 3; kept while moving between steps.
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [booked, setBooked] = useState(null);
  const [handoffLoading, setHandoffLoading] = useState(Boolean(handoffDoctorId));
  const [handoffError, setHandoffError] = useState("");

  // Validate a doctor handed over in the URL against the API; never trust the id itself.
  useEffect(() => {
    if (!handoffDoctorId) return;
    let cancelled = false;
    getPublicDoctor(handoffDoctorId)
      .then((res) => {
        if (cancelled) return;
        setDoctor(res.data);
        if (handoffSlot && !Number.isNaN(Date.parse(handoffSlot))) {
          setSlot({ starts_at: handoffSlot });
          setStep(3);
        } else {
          setStep(2);
          if (handoffSlot) setNotice("That appointment link is not valid. Please choose a time.");
        }
      })
      .catch(() => {
        if (!cancelled) setHandoffError("That doctor is not available for booking. Please choose another doctor.");
      })
      .finally(() => !cancelled && setHandoffLoading(false));
    return () => {
      cancelled = true;
    };
  }, [handoffDoctorId, handoffSlot]);

  // Move focus to the new step so keyboard and screen-reader users follow along.
  const card = useRef(null);
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    card.current?.focus();
  }, [step, booked]);

  // Back from step 1: wherever the user came from, or the dashboard.
  const leave = () => (location.key === "default" ? navigate("/dashboard") : navigate(-1));
  const chooseDoctor = useCallback((next) => {
    setDoctor(next);
    setSlot(null);
  }, []);
  const toStep = (next) => {
    setNotice("");
    setStep(next);
  };
  // The doctor stopped taking bookings meanwhile: back to choosing a doctor.
  const doctorGone = (message) => {
    setDoctor(null);
    setSlot(null);
    setHandoffError(message);
    setStep(1);
  };
  // The time was taken or withdrawn: back to step 2 with fresh times.
  const slotUnavailable = (message) => {
    setSlot(null);
    setNotice(message);
    setRefreshKey((n) => n + 1);
    setStep(2);
  };

  let content;
  let plainStep = false;
  if (handoffLoading) {
    content = <div className="skeleton" style={{ height: 320 }} role="status" aria-label="Loading" />;
  } else if (booked) {
    content = <BookingSuccess appointment={booked} />;
  } else if (step === 1 || !doctor) {
    content = (
      <>
        <Alert>{handoffError}</Alert>
        <DoctorPicker selected={doctor} onSelect={chooseDoctor} onBack={leave} onContinue={() => toStep(2)} />
      </>
    );
  } else if (step === 2 || !slot) {
    plainStep = true;
    content = (
      <DateTimeStep
        doctor={doctor}
        slot={slot}
        onSelect={setSlot}
        notice={notice}
        refreshKey={refreshKey}
        onBack={() => toStep(1)}
        onContinue={() => toStep(3)}
      />
    );
  } else {
    plainStep = true;
    content = (
      <ConfirmStep
        key={slot.starts_at}
        doctor={doctor}
        slot={slot}
        reason={reason}
        onReasonChange={setReason}
        onBack={() => toStep(2)}
        onUnavailable={slotUnavailable}
        onDoctorGone={doctorGone}
        onBooked={(appointment) => {
          setReason("");
          setBooked(appointment);
        }}
      />
    );
  }

  return (
    <div className="booking-page">
      <header className="page-head">
        <div>
          <h1>Book Appointment</h1>
          <p className="muted">Find and book an appointment with the right doctor for your needs.</p>
        </div>
      </header>
      <BookingStepper current={booked ? 4 : step} />
      {/* Steps 2 and 3 are sets of separate cards (content, then actions); step 1 and the result sit in one card. */}
      <section
        ref={card}
        tabIndex={-1}
        className={plainStep ? "booking-step-cards" : "card booking-card"}
        aria-labelledby="booking-step-title"
      >
        {content}
      </section>
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
