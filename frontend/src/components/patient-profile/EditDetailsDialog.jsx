import { useState } from "react";
import { getErrorMessage } from "../../services/api";
import { updateMyDetails } from "../../services/patientService";
import { CONTACT_FIELDS, EMPTY_PATIENT, IDENTITY_FIELDS, patientPayload } from "../../utils/patient";
import ConfirmDialog from "../ConfirmDialog";
import PatientFields from "../PatientFields";

const SECTIONS = {
  personal: { title: "Edit personal details", fields: IDENTITY_FIELDS, identity: true, contact: false },
  contact: { title: "Edit contact details", fields: CONTACT_FIELDS, identity: false, contact: true },
  all: { title: "Edit profile", fields: [...IDENTITY_FIELDS, ...CONTACT_FIELDS], identity: true, contact: true },
};

/**
 * Edit the patient's own details (PATCH /patients/me, D99): `section` is
 * "personal" (name, date of birth, gender), "contact" or "all". Only that
 * section's fields are sent; the MRN and account status are not editable.
 */
export default function EditDetailsDialog({ profile, section = "all", onSaved, onClose }) {
  const { title, fields, identity, contact } = SECTIONS[section];
  const [form, setForm] = useState({ ...EMPTY_PATIENT, ...profile });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    if (identity && (!form.first_name.trim() || !form.last_name.trim() || !form.date_of_birth)) {
      setError("First name, last name and date of birth are required.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await updateMyDetails(patientPayload(form, fields));
      onSaved(res.data, section);
    } catch (err) {
      setError(getErrorMessage(err, "Could not save your changes"));
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog title={title} confirmLabel="Save changes" busy={busy} error={error} onConfirm={save} onCancel={onClose}>
      {identity && (
        <p className="muted small">
          Your name, date of birth and gender are part of your medical record. Please make sure they match your
          identity documents; the clinic keeps a record of each change.
        </p>
      )}
      <PatientFields values={form} onChange={setForm} identity={identity} contact={contact} />
    </ConfirmDialog>
  );
}
