import { ArrowLeftRight, CircleAlert, CircleCheck, UserRoundSearch } from "lucide-react";
import { ageFromDateOfBirth, patientFullName, SEX_LABELS } from "../../utils/patient";
import Avatar from "../Avatar";

/**
 * The patient a staff member is booking for (D82), from the API record. With
 * no patient yet it asks for one; nothing can be booked without it.
 */
export default function SelectedPatientCard({ patient, loading, error, onChange }) {
  if (loading) return <div className="card skeleton selected-patient-skeleton" role="status" aria-label="Loading patient" />;
  if (!patient) {
    return (
      <section className="card selected-patient empty-patient" aria-label="Patient">
        <UserRoundSearch className="pd-icon" size={34} aria-hidden="true" />
        <div className="selected-patient-main">
          <h2>{error ? "Patient not available" : "No patient selected"}</h2>
          <p className="muted">{error || "Choose the patient this appointment is for."}</p>
        </div>
        <button type="button" onClick={onChange}>
          <UserRoundSearch size={18} aria-hidden="true" /> Select Patient
        </button>
      </section>
    );
  }

  const name = patientFullName(patient);
  const age = ageFromDateOfBirth(patient.date_of_birth);
  const facts = [
    age != null && `${age} years`,
    patient.sex_at_birth !== "unknown" && SEX_LABELS[patient.sex_at_birth],
    patient.phone,
    patient.email,
  ].filter(Boolean);
  return (
    <section className="card selected-patient" aria-label={`Patient: ${name}`}>
      <Avatar name={name} role="patient" src={patient.photo_url} size={104} alt={`Photo of ${name}`} />
      <div className="selected-patient-main">
        <h2>{name}</h2>
        <div className="selected-patient-badges">
          <span className="badge mrn-badge">MRN: {patient.mrn}</span>
          {patient.is_active ? (
            <span className="badge ok with-icon">
              <CircleCheck size={14} aria-hidden="true" /> Active
            </span>
          ) : (
            <span className="badge danger with-icon">
              <CircleAlert size={14} aria-hidden="true" /> Inactive
            </span>
          )}
        </div>
        {facts.length > 0 && (
          <ul className="pd-facts">
            {facts.map((fact) => (
              <li key={fact}>{fact}</li>
            ))}
          </ul>
        )}
      </div>
      <button type="button" className="secondary change-patient" onClick={onChange}>
        <ArrowLeftRight size={18} aria-hidden="true" /> Change Patient
      </button>
    </section>
  );
}
