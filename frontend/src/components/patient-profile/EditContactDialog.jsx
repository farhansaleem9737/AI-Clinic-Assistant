import { useState } from "react";
import { getErrorMessage } from "../../services/api";
import { updateMyContactDetails } from "../../services/patientService";
import { CONTACT_FIELDS, EMPTY_PATIENT, patientPayload } from "../../utils/patient";
import ConfirmDialog from "../ConfirmDialog";
import PatientFields from "../PatientFields";

/**
 * Edit the patient's own contact details (PATCH /patients/me). Only the
 * contact fields are sent; the backend ignores anything else a patient
 * might add to the request.
 */
export default function EditContactDialog({ profile, onSaved, onClose }) {
  const [form, setForm] = useState({ ...EMPTY_PATIENT, ...profile });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await updateMyContactDetails(patientPayload(form, CONTACT_FIELDS));
      onSaved(res.data);
    } catch (err) {
      setError(getErrorMessage(err, "Could not save your changes"));
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      title="Edit contact details"
      confirmLabel="Save changes"
      busy={busy}
      error={error}
      onConfirm={save}
      onCancel={onClose}
    >
      <p className="muted small">
        Your name, date of birth and sex at birth are part of your medical record. To correct them, please contact
        reception.
      </p>
      <PatientFields values={form} onChange={setForm} identity={false} />
    </ConfirmDialog>
  );
}
