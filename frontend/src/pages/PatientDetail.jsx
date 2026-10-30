import { CalendarPlus, CircleAlert, CircleCheck, Lock, Pencil, Phone, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import Alert from "../components/Alert";
import Avatar from "../components/Avatar";
import Breadcrumb from "../components/Breadcrumb";
import ConfirmDialog from "../components/ConfirmDialog";
import PatientDocuments from "../components/documents/PatientDocuments";
import InfoCard from "../components/patient-profile/InfoCard";
import EditPatientDialog from "../components/patients/EditPatientDialog";
import PatientAppointmentsCard from "../components/patients/PatientAppointmentsCard";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { activatePatient, createPatientAccount, deactivatePatient, getPatient } from "../services/patientService";
import { formatCalendarDate } from "../utils/datetime";
import { ageFromDateOfBirth, CONTACT_METHODS, patientFullName, SEX_LABELS } from "../utils/patient";

const registered = (iso) => new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(iso));
const SECTIONS = [
  { key: "personal", label: "Personal Information", target: "pd-personal" },
  { key: "contact", label: "Contact Information", target: "pd-contact" },
  { key: "appointments", label: "Appointments", target: "pd-appointments" },
];

function PatientStatus({ active }) {
  return active ? (
    <span className="badge ok with-icon">
      <CircleCheck size={15} aria-hidden="true" /> Active
    </span>
  ) : (
    <span className="badge danger with-icon">
      <CircleAlert size={15} aria-hidden="true" /> Inactive
    </span>
  );
}

function Multiline({ text }) {
  if (!text) return null;
  return text.split(/\r?\n/).map((line, i) => (
    <span key={i} className="pd-line">
      {line}
    </span>
  ));
}

function PortalLogin({ patient, onCreated }) {
  const [account, setAccount] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onCreated((await createPatientAccount(patient.id, account)).data);
      setAccount({ email: "", password: "" });
    } catch (err) {
      setError(getErrorMessage(err, "Could not create the login"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="card pd-card stack" onSubmit={submit} aria-labelledby="pd-login-title">
      <h2 id="pd-login-title">Create portal login</h2>
      <p className="muted small">Give the patient access to book and view their own appointments online.</p>
      <Alert>{error}</Alert>
      <label>
        Login email
        <input type="email" value={account.email} onChange={(e) => setAccount({ ...account, email: e.target.value })} required />
      </label>
      <label>
        Temporary password (min 8)
        <input
          type="password"
          minLength={8}
          value={account.password}
          onChange={(e) => setAccount({ ...account, password: e.target.value })}
          required
        />
      </label>
      <button type="submit" disabled={busy}>
        {busy ? "Creating…" : "Create login"}
      </button>
    </form>
  );
}

/**
 * One patient's record for staff (D81): identity header, personal and
 * contact details, appointments, and medical information only for clinicians
 * who treat the patient. The API decides what each caller may see.
 */
export default function PatientDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [patient, setPatient] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [section, setSection] = useState("personal");
  const [notice, setNotice] = useState("");
  const [statusOpen, setStatusOpen] = useState(false);
  const [statusError, setStatusError] = useState("");
  const [statusBusy, setStatusBusy] = useState(false);
  const editing = searchParams.get("edit") === "1" && can("patient:update");
  const medicalRef = useRef(null);
  // Medical information here means the clinical documents, which only a
  // treating clinician may read (document:read_assigned); the API enforces it.
  const clinical = can("document:read_assigned");

  useEffect(() => {
    let cancelled = false;
    getPatient(id)
      .then((res) => !cancelled && setPatient(res.data))
      .catch((err) => {
        if (cancelled) return;
        const status = err?.response?.status;
        setLoadError(
          status === 404
            ? "This patient was not found, or you do not have access to their record."
            : getErrorMessage(err, "Could not load the patient")
        );
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const setEditing = (open) => {
    const next = new URLSearchParams(searchParams);
    if (open) next.set("edit", "1");
    else next.delete("edit");
    setSearchParams(next, { replace: true });
  };

  if (!patient) {
    return (
      <div className="patient-detail">
        <Breadcrumb items={[{ label: "Patients", to: "/patients" }, { label: "Patient" }]} />
        {loadError ? (
          <div className="card" role="alert">
            <p>{loadError}</p>
            <Link to="/patients">Back to patients</Link>
          </div>
        ) : (
          <div role="status" aria-label="Loading patient">
            <div className="card skeleton" style={{ height: 150 }} />
            <div className="card skeleton" style={{ height: 320 }} />
          </div>
        )}
      </div>
    );
  }

  const name = patientFullName(patient);
  const age = ageFromDateOfBirth(patient.date_of_birth);
  const sex = SEX_LABELS[patient.sex_at_birth];
  const jump = (key, target) => {
    setSection(key);
    const element = document.getElementById(target);
    element?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    element?.querySelector("h2")?.focus({ preventScroll: true });
  };
  const emergency = [patient.emergency_contact_name, patient.emergency_contact_relationship && `(${patient.emergency_contact_relationship})`]
    .filter(Boolean)
    .join(" ");

  const changeStatus = async () => {
    setStatusBusy(true);
    setStatusError("");
    try {
      const res = await (patient.is_active ? deactivatePatient(patient.id) : activatePatient(patient.id));
      setPatient(res.data);
      setStatusOpen(false);
      setNotice(res.data.is_active ? "The patient was reactivated." : "The patient was deactivated.");
    } catch (err) {
      setStatusError(getErrorMessage(err, "Could not change the status"));
    } finally {
      setStatusBusy(false);
    }
  };

  return (
    <div className="patient-detail">
      <Breadcrumb items={[{ label: "Patients", to: "/patients" }, { label: name }]} />

      <header className="pd-header">
        <Avatar name={name} role="patient" src={patient.photo_url} size={116} alt={`Photo of ${name}`} />
        <div className="pd-identity">
          <div className="pd-title">
            <h1>{name}</h1>
            <PatientStatus active={patient.is_active} />
          </div>
          <ul className="pd-facts">
            <li>MRN: {patient.mrn}</li>
            {age != null && <li>{age} years</li>}
            {patient.sex_at_birth !== "unknown" && <li>{sex}</li>}
            <li>Registered: {registered(patient.created_at)}</li>
          </ul>
        </div>
        <div className="pd-actions">
          {can("patient:update") && (
            <button type="button" className="secondary pd-edit" onClick={() => setEditing(true)}>
              <Pencil size={18} aria-hidden="true" /> Edit
            </button>
          )}
          {can("appointment:create") && patient.is_active && (
            <Link to={`/appointments/book?patient=${patient.id}`} className="button pd-book">
              <CalendarPlus size={18} aria-hidden="true" /> Book Appointment
            </Link>
          )}
          {can("patient:deactivate") && (
            <button
              type="button"
              className={patient.is_active ? "danger" : "secondary"}
              onClick={() => {
                setStatusError("");
                setStatusOpen(true);
              }}
            >
              {patient.is_active ? "Deactivate" : "Reactivate"}
            </button>
          )}
        </div>
      </header>

      <nav className="pd-tabs" aria-label="Patient record sections">
        {SECTIONS.map((s) => (
          <a
            key={s.key}
            href={`#${s.target}`}
            className={section === s.key ? "active" : ""}
            aria-current={section === s.key ? "true" : undefined}
            onClick={(e) => {
              e.preventDefault();
              jump(s.key, s.target);
            }}
          >
            {s.label}
          </a>
        ))}
        {clinical ? (
          <a
            href="#pd-medical"
            className={section === "medical" ? "active" : ""}
            aria-current={section === "medical" ? "true" : undefined}
            onClick={(e) => {
              e.preventDefault();
              setSection("medical");
              medicalRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
            }}
          >
            Medical Information
          </a>
        ) : (
          <span className="pd-locked" aria-disabled="true" tabIndex={0} aria-describedby="pd-locked-note" title="Medical information is restricted to authorized clinical staff.">
            <Lock size={16} aria-hidden="true" /> Medical Information
            <span id="pd-locked-note" className="sr-only">
              Medical information is restricted to authorized clinical staff.
            </span>
          </span>
        )}
      </nav>

      <div aria-live="polite">
        <Alert kind="success">{notice}</Alert>
      </div>

      <div className="pd-grid">
        <section id="pd-personal" className="pd-section">
          <InfoCard
            title="Personal Information"
            icon={UserRound}
            rows={[
              { label: "Full Name", value: name },
              { label: "MRN", value: patient.mrn },
              {
                label: "Date of Birth",
                value: `${formatCalendarDate(patient.date_of_birth)}${age != null ? ` (${age} years)` : ""}`,
              },
              { label: "Gender", value: patient.sex_at_birth !== "unknown" ? sex : null },
              { label: "Preferred Language", value: patient.preferred_language },
              { label: "Registered On", value: registered(patient.created_at) },
            ]}
          />
        </section>
        <section id="pd-contact" className="pd-section">
          <InfoCard
            title="Contact Information"
            icon={Phone}
            rows={[
              { label: "Phone", value: patient.phone },
              { label: "Email", value: patient.email },
              { label: "Address", value: patient.address && <Multiline text={patient.address} /> },
              { label: "Emergency Contact", value: emergency },
              { label: "Emergency Phone", value: patient.emergency_contact_phone },
              { label: "Preferred Contact Method", value: CONTACT_METHODS[patient.preferred_contact_method] },
            ]}
          />
        </section>
      </div>

      {(can("appointment:read_any") || can("appointment:read_assigned")) && (
        <PatientAppointmentsCard patientId={patient.id} id="pd-appointments" />
      )}

      {clinical && (
        <div ref={medicalRef} id="pd-medical" className="pd-section">
          <PatientDocuments
            patientId={patient.id}
            canUpload={can("document:upload_assigned")}
            retract={can("document:retract_assigned") ? "any" : undefined}
          />
        </div>
      )}

      {can("patient:create") && !patient.has_account && (
        <PortalLogin
          patient={patient}
          onCreated={(updated) => {
            setPatient(updated);
            setNotice("Portal login created.");
          }}
        />
      )}

      {editing && (
        <EditPatientDialog
          patient={patient}
          onClose={() => setEditing(false)}
          onPhotoChanged={(updated) => setPatient(updated)}
          onSaved={(updated) => {
            setPatient(updated);
            setEditing(false);
            setNotice("The patient's details were saved.");
          }}
        />
      )}

      {statusOpen && (
        <ConfirmDialog
          title={patient.is_active ? "Deactivate patient?" : "Reactivate patient?"}
          confirmLabel={patient.is_active ? "Deactivate" : "Reactivate"}
          danger={patient.is_active}
          busy={statusBusy}
          error={statusError}
          onConfirm={changeStatus}
          onCancel={() => setStatusOpen(false)}
        >
          <p>
            {patient.is_active
              ? `${name} will no longer be offered for new bookings. The record is kept.`
              : `${name} can be booked again.`}
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
