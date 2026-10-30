import { Camera, HeartPulse, Info, Pencil, Phone, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import Alert from "../components/Alert";
import PatientDocuments from "../components/documents/PatientDocuments";
import EditDetailsDialog from "../components/patient-profile/EditDetailsDialog";
import InfoCard from "../components/patient-profile/InfoCard";
import ProfileSummary from "../components/patient-profile/ProfileSummary";
import PatientFields from "../components/PatientFields";
import PhotoUploader from "../components/PhotoUploader";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { getDashboardSummary } from "../services/dashboardService";
import {
  completeMyPatientProfile,
  getMyPatientProfile,
  removeMyPatientPhoto,
  uploadMyPatientPhoto,
} from "../services/patientService";
import { formatCalendarDate } from "../utils/datetime";
import { EMPTY_PATIENT, SEX_LABELS, ageFromDateOfBirth, patientFullName, patientPayload } from "../utils/patient";

const TABS = [
  { id: "personal", label: "Personal Information" },
  { id: "contact", label: "Contact Information" },
  { id: "medical", label: "Medical Information" },
];

// Active only when both the login and the patient record are active. The
// patient's own profile response deliberately omits `is_active`, so the
// status comes from the dashboard summary, which reports it for the caller.
function accountStatus(summary) {
  if (!summary?.account || !summary?.patient?.has_profile) return null;
  return { active: summary.account.is_active && summary.patient.profile_active };
}

function PageHead() {
  return (
    <header className="page-head">
      <div>
        <h1>My Profile</h1>
        <p className="muted">Manage your personal and healthcare information.</p>
      </div>
    </header>
  );
}

const SAVED = {
  personal: "Your personal details were saved",
  contact: "Your contact details were saved",
  all: "Your profile was saved",
};

function EditButton({ label, onClick }) {
  return (
    <button type="button" className="secondary small-button" onClick={onClick} aria-label={label}>
      <Pencil size={15} aria-hidden="true" /> Edit
    </button>
  );
}

function PersonalCard({ profile, onEdit }) {
  const age = ageFromDateOfBirth(profile.date_of_birth);
  const born = profile.date_of_birth && formatCalendarDate(profile.date_of_birth);
  return (
    <InfoCard
      title="Personal Information"
      icon={UserRound}
      rows={[
        { label: "Full Name", value: patientFullName(profile) },
        { label: "Date of Birth", value: born && (age === null ? born : `${born} (${age} years)`) },
        { label: "Gender", value: SEX_LABELS[profile.sex_at_birth] },
        { label: "Medical Record Number", value: profile.mrn },
      ]}
      action={<EditButton label="Edit personal details" onClick={onEdit} />}
      footnote="Your medical record number is assigned by the clinic and cannot be changed."
    />
  );
}

function ContactCard({ profile, onEdit }) {
  return (
    <InfoCard
      title="Contact Information"
      icon={Phone}
      rows={[
        { label: "Phone", value: profile.phone },
        { label: "Email", value: profile.email },
        { label: "Address", value: profile.address },
        { label: "Preferred Language", value: profile.preferred_language },
      ]}
      action={<EditButton label="Edit contact details" onClick={onEdit} />}
    />
  );
}

function MedicalPanel({ profile, can }) {
  return (
    <>
      <section className="card info-card" aria-labelledby="medical-info-title">
        <div className="section-head">
          <HeartPulse className="icon" size={22} aria-hidden="true" />
          <h3 id="medical-info-title">Medical Information</h3>
        </div>
        <p className="muted">
          Diagnoses, allergies, medications and other clinical records are not available in the app yet. Your
          reports and other documents are listed below.
        </p>
      </section>
      {can("document:read_own") && (
        <PatientDocuments
          patientId={profile.id}
          canUpload={can("document:upload_own")}
          retract={can("document:retract_own") ? "own" : undefined}
        />
      )}
    </>
  );
}

// Keyboard-operable tabs (arrow keys, Home, End), as on the other pages.
function ProfileTabs({ active, onChange }) {
  const onKeyDown = (event) => {
    const index = TABS.findIndex((t) => t.id === active);
    const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: TABS.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const target = TABS[(next + TABS.length) % TABS.length];
    onChange(target.id);
    document.getElementById(`profile-tab-${target.id}`)?.focus();
  };

  return (
    <div className="card tab-strip" role="tablist" aria-label="Profile sections" onKeyDown={onKeyDown}>
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          id={`profile-tab-${t.id}`}
          aria-selected={active === t.id}
          aria-controls="profile-tab-panel"
          tabIndex={active === t.id ? 0 : -1}
          className={active === t.id ? "active" : ""}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
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
    <div role="status" aria-label="Loading your profile">
      <div className="card skeleton" style={{ height: 180 }} />
      <div className="card skeleton" style={{ height: 56 }} />
      <div className="profile-layout">
        <div className="card skeleton" style={{ height: 260 }} />
        <div className="card skeleton" style={{ height: 260 }} />
      </div>
    </div>
  );
}

export default function MyPatientProfile() {
  const { fetchCurrentUser, can } = useAuth();
  const [attempt, setAttempt] = useState(0);
  const [profile, setProfile] = useState(null);
  const [missing, setMissing] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [status, setStatus] = useState(null);
  const [tab, setTab] = useState("personal");
  const [editing, setEditing] = useState(null); // "personal" | "contact" | "all"
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    getMyPatientProfile()
      .then((res) => {
        if (cancelled) return;
        setProfile(res.data);
        setLoadError("");
      })
      .catch((err) => {
        if (cancelled) return;
        if (err.response?.data?.error?.code === "NO_PATIENT_PROFILE") setMissing(true);
        else setLoadError(getErrorMessage(err, "Could not load your profile"));
      });
    // The status badge is optional: if this fails it is simply not shown.
    getDashboardSummary()
      .then((res) => !cancelled && setStatus(accountStatus(res.data)))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = () => {
    setLoadError("");
    setAttempt((n) => n + 1);
  };

  const onCreated = async (created) => {
    setProfile(created);
    setMissing(false);
    setNotice("Profile saved");
    await fetchCurrentUser(); // picks up the new patient_id
    setAttempt((n) => n + 1); // and the account status that goes with it
  };

  const onSaved = (updated, section) => {
    setProfile(updated);
    setEditing(null);
    setNotice(SAVED[section]);
  };

  if (missing) {
    return (
      <div className="my-profile">
        <PageHead />
        <CompleteProfile onCreated={onCreated} />
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="my-profile">
        <PageHead />
        {loadError ? (
          <div className="card" role="alert">
            <p>{loadError}</p>
            <button type="button" className="secondary" onClick={retry}>
              Try again
            </button>
          </div>
        ) : (
          <LoadingProfile />
        )}
      </div>
    );
  }

  const name = patientFullName(profile);
  const openEditor = (section) => () => {
    setNotice("");
    setEditing(section);
  };

  return (
    <div className="my-profile">
      <PageHead />
      <Alert kind="success">{notice}</Alert>

      <ProfileSummary profile={profile} status={status} onEdit={openEditor("all")} />
      <ProfileTabs active={tab} onChange={setTab} />

      <div className="profile-layout">
        <div className="profile-main" id="profile-tab-panel" role="tabpanel" aria-labelledby={`profile-tab-${tab}`}>
          {tab === "personal" && (
            <>
              <PersonalCard profile={profile} onEdit={openEditor("personal")} />
              <ContactCard profile={profile} onEdit={openEditor("contact")} />
            </>
          )}
          {tab === "contact" && <ContactCard profile={profile} onEdit={openEditor("contact")} />}
          {tab === "medical" && <MedicalPanel profile={profile} can={can} />}
        </div>

        <aside className="profile-side" aria-label="Profile picture and tips">
          <section className="card photo-card" aria-labelledby="profile-picture-title">
            <div className="section-head">
              <Camera className="icon" size={22} aria-hidden="true" />
              <h3 id="profile-picture-title">Profile Picture</h3>
            </div>
            <PhotoUploader
              layout="stacked"
              name={name}
              photoUrl={profile.photo_url}
              onUpload={async (file) => setProfile((await uploadMyPatientPhoto(file)).data)}
              onRemove={async () => setProfile((await removeMyPatientPhoto()).data)}
            />
          </section>
          <section className="card reminder-card" aria-labelledby="profile-reminder-title">
            <Info className="reminder-icon" size={24} aria-hidden="true" />
            <div>
              <h3 id="profile-reminder-title">Keep your information up to date</h3>
              <p className="muted small">
                Your information helps us provide better care and a smoother appointment experience.
              </p>
            </div>
          </section>
        </aside>
      </div>

      {editing && (
        <EditDetailsDialog profile={profile} section={editing} onSaved={onSaved} onClose={() => setEditing(null)} />
      )}
    </div>
  );
}
