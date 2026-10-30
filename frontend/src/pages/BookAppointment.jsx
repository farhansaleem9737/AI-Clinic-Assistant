import { UsersRound } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import Alert from "../components/Alert";
import BookingStepper from "../components/booking/BookingStepper";
import BookingSuccess from "../components/booking/BookingSuccess";
import ConfirmStep from "../components/booking/ConfirmStep";
import DateTimeStep from "../components/booking/DateTimeStep";
import DoctorPicker from "../components/booking/DoctorPicker";
import PatientPickerDialog from "../components/booking/PatientPickerDialog";
import SelectedPatientCard from "../components/booking/SelectedPatientCard";
import { useAuth } from "../context/useAuth";
import { getPublicDoctor } from "../services/doctorService";
import { getPatient } from "../services/patientService";

/**
 * Select Doctor → Date & Time → Confirm, for everyone. Patients book for
 * themselves; staff (appointment:create) book on behalf of a patient they
 * choose (D82), with the same steps and the same booking API.
 */
export default function BookAppointment() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  // A new link (another doctor, another patient) starts a fresh booking.
  return <BookingWizard key={params.toString()} staff={can("appointment:create")} />;
}

// The patient a staff booking is for: `?patient=<id>`, checked by the API
// (it answers 404 for a patient the caller may not see). Never a name.
function usePatientFromUrl(staff, patientId) {
  const [state, setState] = useState({ patient: null, loading: Boolean(staff && patientId), error: "" });
  useEffect(() => {
    if (!staff || !patientId) return;
    let cancelled = false;
    getPatient(patientId)
      .then((res) => {
        if (cancelled) return;
        setState(
          res.data.is_active
            ? { patient: res.data, loading: false, error: "" }
            : { patient: null, loading: false, error: "This patient's record is inactive and cannot be booked. Choose another patient." }
        );
      })
      .catch(() => !cancelled && setState({ patient: null, loading: false, error: "That patient was not found, or you do not have access to their record." }));
    return () => {
      cancelled = true;
    };
  }, [staff, patientId]);
  return state;
}

/**
 * `?doctor=<id>` (from the directory or a profile) starts at step 2 with that
 * doctor, once the API confirms it is bookable; `&slot=<time>` goes straight
 * to the confirm step, which re-checks the time. Nothing is booked before
 * "Confirm Appointment".
 */
function BookingWizard({ staff }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const handoffDoctorId = params.get("doctor");
  const handoffSlot = params.get("slot");
  const patientState = usePatientFromUrl(staff, params.get("patient"));
  const patient = patientState.patient;

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
  // Arriving with a doctor (and maybe a time) but no patient, e.g. from
  // Doctor Schedules: ask for the patient straight away.
  const [picking, setPicking] = useState(staff && !params.get("patient") && Boolean(handoffDoctorId));

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

  // Back from step 1: wherever the user came from inside the app; otherwise
  // the patient's record (staff) or the dashboard.
  const leave = () => {
    if (location.key !== "default") navigate(-1);
    else navigate(staff && patient ? `/patients/${patient.id}` : "/dashboard");
  };
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
  // A different patient starts a new booking (the wizard remounts on the new URL).
  const changePatient = (next) => {
    setPicking(false);
    if (next.id === patient?.id) return;
    const query = new URLSearchParams({ patient: next.id });
    // A first choice keeps a doctor/time handed over in the link; replacing
    // a patient discards the previous patient's draft (the dialog said so).
    if (!patient) {
      if (doctor) query.set("doctor", doctor.id);
      if (slot) query.set("slot", slot.starts_at);
    }
    setParams(query, { replace: true });
  };
  const needsPatient = staff && !patient;

  let content;
  let plainStep = false;
  if (handoffLoading) {
    content = <div className="skeleton" style={{ height: 320 }} role="status" aria-label="Loading" />;
  } else if (booked) {
    content = <BookingSuccess appointment={booked} onBehalf={staff} />;
  } else if (step === 1 || !doctor || needsPatient) {
    content = (
      <>
        <Alert>{handoffError}</Alert>
        <DoctorPicker
          selected={doctor}
          onSelect={chooseDoctor}
          onBack={leave}
          onContinue={() => toStep(2)}
          subtitle={staff ? "Choose a doctor for this appointment." : undefined}
          blockedReason={() => (needsPatient ? "Select the patient this appointment is for before continuing." : null)}
        />
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
        patient={staff ? patient : undefined}
        onBooked={(appointment) => {
          setReason("");
          setBooked(appointment);
        }}
      />
    );
  }
  const shownStep = booked ? 4 : needsPatient ? 1 : step;

  return (
    <div className="booking-page">
      <header className={`page-head${staff ? " staff-booking-head" : ""}`}>
        <div>
          <h1>Book Appointment</h1>
          <p className="muted">
            {staff ? "Schedule an appointment for a patient." : "Find and book an appointment with the right doctor for your needs."}
          </p>
        </div>
        {staff && (
          <aside className="on-behalf-panel" aria-label="Booking on behalf of a patient">
            <UsersRound size={34} aria-hidden="true" />
            <div>
              <strong>Booking on behalf of a patient</strong>
              <p>You are scheduling this appointment for the selected patient.</p>
            </div>
          </aside>
        )}
      </header>
      {staff && !booked && (
        <SelectedPatientCard
          patient={patient}
          loading={patientState.loading}
          error={patientState.error}
          onChange={() => setPicking(true)}
        />
      )}
      <BookingStepper current={shownStep} />
      {/* Steps 2 and 3 are sets of separate cards (content, then actions); step 1 and the result sit in one card. */}
      <section
        ref={card}
        tabIndex={-1}
        className={plainStep ? "booking-step-cards" : "card booking-card"}
        aria-labelledby="booking-step-title"
      >
        {content}
      </section>
      {picking && (
        <PatientPickerDialog
          currentId={patient?.id}
          hasDraft={Boolean(doctor || slot)}
          onSelect={changePatient}
          onClose={() => setPicking(false)}
        />
      )}
    </div>
  );
}
