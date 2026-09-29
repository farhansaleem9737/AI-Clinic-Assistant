import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Alert from "../components/Alert";
import PatientFields from "../components/PatientFields";
import { EMPTY_PATIENT, patientPayload } from "../utils/patient";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import {
  activatePatient,
  createPatientAccount,
  deactivatePatient,
  getPatient,
  updatePatient,
} from "../services/patientService";

// Staff view of one patient: demographics, portal login, status.
export default function PatientDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const [patient, setPatient] = useState(null);
  const [form, setForm] = useState(EMPTY_PATIENT);
  const [account, setAccount] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(() => {
    getPatient(id)
      .then((res) => {
        setPatient(res.data);
        setForm({ ...EMPTY_PATIENT, ...res.data });
      })
      .catch((err) => setError(getErrorMessage(err, "Patient not found")));
  }, [id]);

  useEffect(load, [load]);

  const run = async (action, success) => {
    setError("");
    setNotice("");
    try {
      const res = await action();
      setPatient(res.data);
      setForm({ ...EMPTY_PATIENT, ...res.data });
      setNotice(success);
      return true;
    } catch (err) {
      setError(getErrorMessage(err));
      return false;
    }
  };

  if (!patient) return error ? <Alert>{error}</Alert> : <p className="muted">Loading…</p>;

  return (
    <div>
      <p>
        <Link to="/patients">← Patients</Link>
      </p>
      <div className="card spread">
        <div>
          <h2>
            {patient.first_name} {patient.last_name}
          </h2>
          <p className="muted small">
            {patient.mrn} · Born {patient.date_of_birth} · Portal login: {patient.has_account ? "yes" : "no"}
          </p>
        </div>
        <div className="row">
          {can("appointment:create") && (
            <Link to={`/appointments/book?patient=${patient.id}`}>
              <button>Book appointment</button>
            </Link>
          )}
          {can("patient:deactivate") &&
            (patient.is_active ? (
              <button className="danger" onClick={() => run(() => deactivatePatient(id), "Patient deactivated")}>
                Deactivate
              </button>
            ) : (
              <button className="secondary" onClick={() => run(() => activatePatient(id), "Patient activated")}>
                Activate
              </button>
            ))}
        </div>
      </div>
      <Alert>{error}</Alert>
      <Alert kind="success">{notice}</Alert>

      {can("patient:update") && (
        <form
          className="card stack"
          onSubmit={(e) => {
            e.preventDefault();
            run(() => updatePatient(id, patientPayload(form)), "Patient updated");
          }}
        >
          <h3>Details</h3>
          <PatientFields values={form} onChange={setForm} />
          <button type="submit">Save</button>
        </form>
      )}

      {can("patient:create") && !patient.has_account && (
        <form
          className="card stack"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await run(() => createPatientAccount(id, account), "Portal login created")) setAccount({ email: "", password: "" });
          }}
        >
          <h3>Create portal login</h3>
          <p className="muted small">Give the patient access to book and view their own appointments online.</p>
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
          <button type="submit">Create login</button>
        </form>
      )}
    </div>
  );
}
