import { useState } from "react";
import { useFetch } from "../../hooks/useFetch";
import { getErrorMessage } from "../../services/api";
import { getDoctorCareer, getMyCareer, updateDoctor, updateDoctorCareer, updateMyCareer, updateMyDoctorProfile } from "../../services/doctorService";
import Alert from "../Alert";
import ConfirmDialog from "../ConfirmDialog";
import { careerError, toForm, toPayload } from "../../utils/career";
import { CareerFields } from "./CareerEditor";

const BIO_MAX = 1000;

/**
 * Edit the biography shown under "About". `own`: the doctor's own profile
 * (PATCH /doctors/me); otherwise an administrator editing this doctor.
 */
export function AboutDialog({ doctor, own, onClose, onSaved }) {
  const [bio, setBio] = useState(doctor.bio ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    if ((bio.trim() || null) === (doctor.bio ?? null)) return onClose();
    setBusy(true);
    setError("");
    try {
      const body = { bio: bio.trim() || null };
      await (own ? updateMyDoctorProfile(body) : updateDoctor(doctor.id, body));
      onSaved("About saved");
    } catch (err) {
      setError(getErrorMessage(err, "Could not save the biography"));
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog title="Edit About" confirmLabel="Save changes" busy={busy} error={error} onConfirm={save} onCancel={onClose} className="wide-dialog">
      <div className="edit-field">
        <label htmlFor="edit-about-bio">Professional biography</label>
        <textarea id="edit-about-bio" rows={8} maxLength={BIO_MAX} value={bio} disabled={busy} onChange={(e) => setBio(e.target.value)} aria-describedby="edit-about-bio-hint" />
        <small className="muted" id="edit-about-bio-hint">
          {bio.length}/{BIO_MAX} · leave a blank line between paragraphs
        </small>
      </div>
    </ConfirmDialog>
  );
}

const TITLES = { experience: "Edit Experience", education: "Edit Education" };

/**
 * Edit one career list (experience or education). The whole career is loaded
 * and saved, so the list not shown here is kept exactly as it was.
 */
export function CareerDialog({ doctorId, own, section, onClose, onSaved }) {
  const { data, loading, error: loadError } = useFetch(() => (own ? getMyCareer() : getDoctorCareer(doctorId)), [own, doctorId]);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const form = draft ?? (data ? toForm(data) : null);

  const save = async () => {
    if (!form) return;
    if (!draft) return onClose(); // nothing changed
    const problem = careerError(form);
    if (problem) return setError(problem);
    setBusy(true);
    setError("");
    try {
      const body = toPayload(form);
      await (own ? updateMyCareer(body) : updateDoctorCareer(doctorId, body));
      onSaved(section === "experience" ? "Experience saved" : "Education saved");
    } catch (err) {
      setError(getErrorMessage(err, "Could not save the changes"));
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog title={TITLES[section]} confirmLabel="Save changes" busy={busy} error={error} onConfirm={save} onCancel={onClose} className="wide-dialog career-dialog">
      {loadError ? (
        <Alert>{loadError}</Alert>
      ) : loading || !form ? (
        <div className="skeleton" style={{ height: 140 }} role="status" aria-label="Loading career history" />
      ) : (
        <>
          {section === "experience" && <p className="muted small">Newest first on the profile. Leave “To” blank for a current position.</p>}
          <CareerFields form={form} onChange={setDraft} section={section} />
        </>
      )}
    </ConfirmDialog>
  );
}
