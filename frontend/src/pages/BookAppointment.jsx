import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import Alert from "../components/Alert";
import SlotPicker from "../components/SlotPicker";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { bookAppointment } from "../services/appointmentService";
import { getPublicDepartments } from "../services/departmentService";
import { getPublicDoctor, getPublicDoctors } from "../services/doctorService";
import { getPatient, listPatients } from "../services/patientService";
import { formatDateTime } from "../utils/datetime";
import { doctorName, formatFee } from "../utils/format";

// Patients book for themselves; staff (appointment:create) pick the patient.
export default function BookAppointment() {
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
  const [slot, setSlot] = useState(null);
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
      navigate(`/appointments/${res.data.id}`);
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
