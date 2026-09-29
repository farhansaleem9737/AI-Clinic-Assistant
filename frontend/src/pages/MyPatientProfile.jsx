import { useEffect, useState } from "react";
import Alert from "../components/Alert";
import PatientFields from "../components/PatientFields";
import { EMPTY_PATIENT, patientPayload } from "../utils/patient";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { completeMyPatientProfile, getMyPatientProfile, updateMyContactDetails } from "../services/patientService";

const CONTACT_FIELDS = ["phone", "email", "address", "preferred_language"];

export default function MyPatientProfile() {
  const { fetchCurrentUser } = useAuth();
  const [profile, setProfile] = useState(null);
  const [missing, setMissing] = useState(false);
  const [form, setForm] = useState(EMPTY_PATIENT);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    getMyPatientProfile()
      .then((res) => {
        setProfile(res.data);
        setForm({ ...EMPTY_PATIENT, ...res.data });
      })
      .catch((err) => {
        if (err.response?.data?.error?.code === "NO_PATIENT_PROFILE") setMissing(true);
        else setError(getErrorMessage(err, "Could not load your profile"));
      });
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setNotice("");
    try {
      const res = missing
        ? await completeMyPatientProfile(patientPayload(form))
        : await updateMyContactDetails(patientPayload(form, CONTACT_FIELDS));
      setProfile(res.data);
      setForm({ ...EMPTY_PATIENT, ...res.data });
      if (missing) {
        setMissing(false);
        await fetchCurrentUser(); // picks up the new patient_id
      }
      setNotice("Profile saved");
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  if (!profile && !missing) return error ? <Alert>{error}</Alert> : <p className="muted">Loading…</p>;

  return (
    <div>
      <h2>My profile</h2>
      <Alert>{error}</Alert>
      <Alert kind="success">{notice}</Alert>
      {profile && (
        <div className="card">
          <h3>
            {profile.first_name} {profile.last_name}
          </h3>
          <p className="muted small">
            Record number {profile.mrn} · Born {profile.date_of_birth}
          </p>
          <p className="muted small">To correct your name or date of birth, please contact reception.</p>
        </div>
      )}
      <form className="card stack" onSubmit={submit}>
        <h3>{missing ? "Complete your patient profile" : "Contact details"}</h3>
        <PatientFields values={form} onChange={setForm} identity={missing} />
        <button type="submit">Save</button>
      </form>
    </div>
  );
}
