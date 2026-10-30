import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { getErrorMessage } from "../../services/api";
import { listPatients } from "../../services/patientService";
import { ageFromDateOfBirth, patientFullName } from "../../utils/patient";
import Avatar from "../Avatar";
import ConfirmDialog from "../ConfirmDialog";

const SEARCH_DELAY_MS = 300;
const MIN_QUERY = 2;

/**
 * Search active patients (name, MRN, phone or email, on the server) and pick
 * one. `hasDraft`: a doctor or time is already chosen, which the change
 * clears, so the dialog says so before confirming.
 */
export default function PatientPickerDialog({ currentId, hasDraft, onSelect, onClose }) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState({ query: "", items: [], error: "" });
  const [chosen, setChosen] = useState(null);
  const term = query.trim();

  useEffect(() => {
    if (term.length < MIN_QUERY) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      listPatients({ q: term, is_active: true, page_size: 8 })
        .then((res) => !cancelled && setResult({ query: term, items: res.data.items, error: "" }))
        .catch((err) => !cancelled && setResult({ query: term, items: [], error: getErrorMessage(err, "Could not search patients") }));
    }, SEARCH_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [term]);

  const searching = term.length >= MIN_QUERY && result.query !== term;
  const items = term.length >= MIN_QUERY && result.query === term ? result.items : [];
  const [error, setError] = useState("");

  return (
    <ConfirmDialog
      title={currentId ? "Change patient" : "Select patient"}
      confirmLabel="Use this patient"
      error={error || result.error}
      onConfirm={() => {
        if (!chosen) return setError("Choose a patient from the results.");
        onSelect(chosen);
      }}
      onCancel={onClose}
      className="wide-dialog"
    >
      <div className="input-icon patient-picker-search">
        <Search size={18} aria-hidden="true" />
        <input
          type="search"
          aria-label="Search patients by name, MRN, phone or email"
          placeholder="Search by name, MRN, phone or email..."
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setError("");
          }}
        />
      </div>
      {hasDraft && (
        <p className="alert warn">Changing the patient clears the doctor and time chosen so far.</p>
      )}
      <div aria-live="polite" className="patient-picker-status muted small">
        {term.length < MIN_QUERY
          ? "Type at least two characters to search."
          : searching
            ? "Searching…"
            : `${items.length} patient${items.length === 1 ? "" : "s"} found`}
      </div>
      {items.length > 0 && (
        <ul className="patient-picker-list" role="radiogroup" aria-label="Patients">
          {items.map((p) => {
            const name = patientFullName(p);
            const age = ageFromDateOfBirth(p.date_of_birth);
            return (
              <li key={p.id}>
                <label className={`patient-option${chosen?.id === p.id ? " selected" : ""}`}>
                  <input
                    type="radio"
                    name="booking-patient"
                    checked={chosen?.id === p.id}
                    onChange={() => {
                      setChosen(p);
                      setError("");
                    }}
                  />
                  <Avatar name={name} role="patient" src={p.photo_url} size={40} />
                  <span>
                    <strong>{name}</strong>
                    <span className="muted small">
                      {[p.mrn, age != null && `${age} years`, p.id === currentId && "current patient"].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </ConfirmDialog>
  );
}
