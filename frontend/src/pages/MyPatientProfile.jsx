import { PhoneCall, UserRound } from "lucide-react";
import { useState } from "react";
import { useLocation } from "react-router-dom";
import Alert from "../components/Alert";
import PatientFields from "../components/PatientFields";
import ContactSection from "../components/patient-profile/ContactSection";
import PersonalSection from "../components/patient-profile/PersonalSection";
import { useAuth } from "../context/useAuth";
import { useFetch } from "../hooks/useFetch";
import { getErrorMessage } from "../services/api";
import { getDashboardSummary } from "../services/dashboardService";
import { completeMyPatientProfile, getMyPatientProfile } from "../services/patientService";
import { EMPTY_PATIENT, patientPayload } from "../utils/patient";

// Two sections at their own addresses (the sidebar links to them, D110/D111);
// Medical Information is its own page.
const SECTIONS = {
  personal: { title: "Personal Information", text: "Your basic details and identity information.", icon: UserRound },
  contact: { title: "Contact Information", text: "Your contact details to stay connected and receive important updates.", icon: PhoneCall },
};

// Active only when both the login and the patient record are active. The
// patient's own profile response deliberately omits `is_active`, so the
// status comes from the dashboard summary, which reports it for the caller.
function accountStatus(summary) {
  if (!summary?.account || !summary?.patient?.has_profile) return null;
  return { active: summary.account.is_active && summary.patient.profile_active };
}

function PageHead({ section }) {
  const { title, text, icon: Icon } = SECTIONS[section];
  return (
    <header className="pp-head">
      <span className="pp-head-icon" aria-hidden="true">
        <Icon size={28} />
      </span>
      <div>
        <h1>{title}</h1>
        <p className="muted">{text}</p>
      </div>
    </header>
  );
}

// First sign-in without a patient record: collect the identity once.
function CompleteProfile({ onCreated }) {
  const [form, setForm] = useState(EMPTY_PATIENT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onCreated((await completeMyPatientProfile(patientPayload(form))).data);
    } catch (err) {
      setError(getErrorMessage(err));
      setBusy(false);
    }
  };

  return (
    <section className="card" aria-labelledby="complete-profile-title">
      <h2 id="complete-profile-title">Complete your patient profile</h2>
      <p className="muted">We need a few details before you can book appointments.</p>
      <form className="stack" onSubmit={submit}>
        <PatientFields values={form} onChange={setForm} identity />
        <Alert>{error}</Alert>
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
      </form>
    </section>
  );
}

function LoadingProfile() {
  return (
    <div className="pp-layout" role="status" aria-label="Loading your profile">
      <div className="card skeleton" style={{ height: 320 }} />
      <div className="card skeleton" style={{ height: 320 }} />
    </div>
  );
}

/**
 * The patient's own profile (D111): Personal Information at /profile and
 * Contact Information at /profile/contact, from the real record; changes are
 * saved through PATCH /patients/me and shown once the server has them.
 */
export default function MyPatientProfile() {
  const { user, fetchCurrentUser } = useAuth();
  const { pathname } = useLocation();
  const section = pathname.startsWith("/profile/contact") ? "contact" : "personal";
  const [attempt, setAttempt] = useState(0);
  const [notice, setNotice] = useState("");

  // Shared with the dashboard's profile card and status (D107).
  const loaded = useFetch(getMyPatientProfile, [], {
    query: "profile/patient",
    refresh: attempt,
    errorMessage: "Could not load your profile",
  });
  // The status badge is optional: if this fails it is simply not shown.
  const summary = useFetch(getDashboardSummary, [], { query: "dashboard/summary", refresh: attempt });
  const [saved, setProfile] = useState(null); // the server's reply to a change made here
  const [created, setCreated] = useState(false);
  const missing = !created && loaded.code === "NO_PATIENT_PROFILE";
  const profile = saved ?? (loaded.loading ? null : loaded.data);
  const loadError = missing ? "" : loaded.error;
  const status = summary.data ? accountStatus(summary.data) : null;

  const onCreated = async (record) => {
    setProfile(record);
    setCreated(true);
    setNotice("Profile saved");
    await fetchCurrentUser(); // picks up the new patient_id
    setAttempt((n) => n + 1); // and the account status that goes with it
  };
  // The top bar shows the account's name and photo: refresh them after a change.
  const onSaved = (updated, message) => {
    setProfile(updated);
    setNotice(message);
    fetchCurrentUser().catch(() => {});
  };

  if (missing) {
    return (
      <div className="pp-page">
        <PageHead section={section} />
        <CompleteProfile onCreated={onCreated} />
      </div>
    );
  }

  return (
    <div className="pp-page">
      <PageHead section={section} />
      <div aria-live="polite">
        <Alert kind="success">{notice}</Alert>
      </div>
      {!profile ? (
        loadError ? (
          <div className="card" role="alert">
            <p>{loadError}</p>
            <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </button>
          </div>
        ) : (
          <LoadingProfile />
        )
      ) : section === "personal" ? (
        <PersonalSection profile={profile} status={status} memberSince={user?.created_at} onSaved={onSaved} onNotice={setNotice} />
      ) : (
        <ContactSection profile={profile} signInEmail={user?.email} onSaved={onSaved} />
      )}
    </div>
  );
}
