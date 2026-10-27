import {
  BadgeCheck,
  Briefcase,
  Building2,
  CheckCircle2,
  CircleAlert,
  CircleDollarSign,
  ImageIcon,
  Pencil,
  UserRound,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Alert from "../components/Alert";
import Avatar from "../components/Avatar";
import CareerEditor from "../components/doctors/CareerEditor";
import EditDoctorProfileDialog from "../components/doctor-profile/EditDoctorProfileDialog";
import InfoCard from "../components/patient-profile/InfoCard";
import PhotoUploader from "../components/PhotoUploader";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import {
  getMyCareer,
  getMyDoctorProfile,
  removeMyDoctorPhoto,
  updateMyCareer,
  uploadMyDoctorPhoto,
} from "../services/doctorService";
import { doctorName, formatFee } from "../utils/format";

const fee = (profile) => (profile.consultation_fee == null ? null : formatFee(profile.consultation_fee));

function StatusBadge({ active }) {
  return active ? (
    <span className="badge ok status-pill">
      <CheckCircle2 size={15} aria-hidden="true" /> Active
    </span>
  ) : (
    <span className="badge danger status-pill">
      <CircleAlert size={15} aria-hidden="true" /> Inactive
    </span>
  );
}

function PageHead() {
  return (
    <header className="page-head">
      <div>
        <h1>My Professional Profile</h1>
        <p className="muted">Manage your professional information, availability and preferences.</p>
      </div>
    </header>
  );
}

// The biography as written: blank-line-separated paragraphs, shown as text.
function Bio({ text }) {
  const paragraphs = (text ?? "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  if (!paragraphs.length) return null;
  return (
    <>
      {paragraphs.map((p, i) => (
        <p key={i} className="prose bio-paragraph">
          {p}
        </p>
      ))}
    </>
  );
}

function Summary({ profile, onEdit }) {
  const name = doctorName(profile);
  return (
    <section className="card pro-summary" aria-label="Profile summary">
      <Avatar name={profile.name} role="doctor" src={profile.photo_url} size={176} alt={`Photo of ${name}`} />
      <div className="pro-summary-main">
        <h2>
          {name}
          {/* Verified only when a license number is on file (D58). */}
          {profile.is_verified && (
            <BadgeCheck className="verified" size={26} role="img" aria-label="Verified: medical license on file" />
          )}
        </h2>
        <p className="pro-specialization">{profile.specialization}</p>
        <p className="pro-department">{profile.department_name}</p>
        <div className="pro-facts">
          <StatusBadge active={profile.is_active} />
          <span className="pro-fact">
            <Briefcase size={24} aria-hidden="true" />
            <span>{profile.years_of_experience} years experience</span>
          </span>
          <span className="pro-fact">
            <Building2 size={24} aria-hidden="true" />
            <span>
              {profile.room_number ? `Room ${profile.room_number}` : profile.department_name}
              <small>{profile.department_name} Department</small>
            </span>
          </span>
          <span className="pro-fact">
            <CircleDollarSign size={24} aria-hidden="true" />
            <span>
              <strong>{fee(profile) ?? "Not set"}</strong>
              <small>Consultation fee</small>
            </span>
          </span>
        </div>
      </div>
      <button type="button" className="pro-edit" onClick={onEdit}>
        <Pencil size={16} aria-hidden="true" /> Edit Profile
      </button>
    </section>
  );
}

// Profile / Schedule / Appointments: links to the real pages, shown when the
// doctor may use them.
function PageTabs() {
  const { can } = useAuth();
  const tabs = [
    { to: "/doctor/profile", label: "Profile", current: true },
    can("schedule:manage_own") && { to: "/schedule", label: "Schedule" },
    can("appointment:read_assigned") && { to: "/appointments", label: "Appointments" },
  ].filter(Boolean);
  return (
    <nav className="card profile-nav" aria-label="Doctor pages">
      <ul>
        {tabs.map((t) => (
          <li key={t.to}>
            <Link to={t.to} className={t.current ? "active" : ""} aria-current={t.current ? "page" : undefined}>
              {t.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export default function MyDoctorProfile() {
  const { fetchCurrentUser } = useAuth();
  const [attempt, setAttempt] = useState(0);
  const [profile, setProfile] = useState(null);
  const [loadError, setLoadError] = useState({ message: "", missing: false });
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    getMyDoctorProfile()
      .then((res) => !cancelled && setProfile(res.data))
      .catch((err) => {
        if (cancelled) return;
        setLoadError({
          message: getErrorMessage(err, "Could not load your profile"),
          missing: err.response?.data?.error?.code === "NO_DOCTOR_PROFILE",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // A new photo also updates the header avatar (it comes from /auth/me).
  const photoChanged = async (res) => {
    setProfile(res.data);
    await fetchCurrentUser?.();
  };

  if (!profile) {
    return (
      <div className="doctor-pro-profile">
        <PageHead />
        {loadError.missing ? (
          <div className="card">
            <p>Your login does not have a doctor profile yet. The clinic administration creates doctor profiles.</p>
          </div>
        ) : loadError.message ? (
          <div className="card" role="alert">
            <p>{loadError.message}</p>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setLoadError({ message: "", missing: false });
                setAttempt((n) => n + 1);
              }}
            >
              Try again
            </button>
          </div>
        ) : (
          <div role="status" aria-label="Loading your profile">
            <div className="card skeleton" style={{ height: 210 }} />
            <div className="card skeleton" style={{ height: 56 }} />
            <div className="card skeleton" style={{ height: 380 }} />
          </div>
        )}
      </div>
    );
  }

  const name = doctorName(profile);
  return (
    <div className="doctor-pro-profile">
      <PageHead />
      <Alert kind="success">{notice}</Alert>
      <Summary
        profile={profile}
        onEdit={() => {
          setNotice("");
          setEditing(true);
        }}
      />
      <PageTabs />

      <div className="pro-layout">
        <InfoCard
          title="Professional Information"
          icon={UserRound}
          rows={[
            { label: "Full Name", value: name },
            { label: "Specialization", value: profile.specialization },
            { label: "Department", value: profile.department_name },
            { label: "Experience", value: `${profile.years_of_experience} years` },
            { label: "Consultation Fee", value: fee(profile) },
            { label: "License Number", value: profile.license_number },
            { label: "Languages", value: profile.languages },
            { label: "Qualifications", value: profile.qualifications },
            { label: "Bio", value: profile.bio && <Bio text={profile.bio} /> },
          ]}
        />

        <aside className="pro-side" aria-label="Photo and clinic">
          <section className="card photo-card" aria-labelledby="pro-photo-title">
            <div className="section-head">
              <ImageIcon className="icon" size={22} aria-hidden="true" />
              <h3 id="pro-photo-title">Profile Picture</h3>
            </div>
            <PhotoUploader
              layout="stacked"
              confirm
              name={name}
              role="doctor"
              photoUrl={profile.photo_url}
              onUpload={async (file) => photoChanged(await uploadMyDoctorPhoto(file))}
              onRemove={async () => photoChanged(await removeMyDoctorPhoto())}
            />
          </section>

          <InfoCard
            title="Clinic Information"
            icon={Building2}
            rows={[
              { label: "Department", value: profile.department_name },
              { label: "Room", value: profile.room_number },
              { label: "Consultation Fee", value: fee(profile) },
              { label: "Status", value: <StatusBadge active={profile.is_active} /> },
            ]}
            footnote="The clinic's name and address are not set up in the system yet. Department, room and fee are managed by the clinic administration."
          />
        </aside>
      </div>

      <section className="pro-career" aria-label="Experience and education">
        <CareerEditor load={getMyCareer} save={updateMyCareer} />
      </section>

      {editing && (
        <EditDoctorProfileDialog
          profile={profile}
          onClose={() => setEditing(false)}
          onSaved={(updated) => {
            setProfile(updated);
            setEditing(false);
            setNotice("Your profile was saved");
          }}
        />
      )}
    </div>
  );
}
