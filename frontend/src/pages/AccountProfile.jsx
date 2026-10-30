import { IdCard, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import Avatar from "../components/Avatar";
import InfoCard from "../components/patient-profile/InfoCard";
import { useAuth } from "../context/useAuth";
import { roleLabel } from "../routes/navigation";

const joined = (iso) => (iso ? new Intl.DateTimeFormat("en-US", { dateStyle: "long" }).format(new Date(iso)) : null);

/**
 * The signed-in account (D86): who you are signed in as and what you may do.
 * For staff without a doctor or patient profile this is "My Profile"; people
 * who have one are pointed to it. Names and roles are changed by an
 * administrator in Users.
 */
export default function AccountProfile() {
  const { user, can } = useAuth();
  return (
    <div className="account-profile">
      <header className="schedule-head">
        <h1>My Profile</h1>
        <p className="muted">Your account details.</p>
      </header>
      <section className="card pd-header account-card" aria-label="Signed-in account">
        <Avatar name={user.name} role={user.doctor_id ? "doctor" : undefined} src={user.photo_url} size={96} />
        <div className="pd-identity">
          <div className="pd-title">
            <h2>{user.name}</h2>
            <span className={`badge ${user.is_active ? "ok" : "danger"}`}>{user.is_active ? "Active" : "Inactive"}</span>
          </div>
          <p className="muted">{roleLabel(user.roles)}</p>
        </div>
      </section>
      <div className="pd-grid">
        <InfoCard
          title="Account"
          icon={IdCard}
          rows={[
            { label: "Name", value: user.name },
            { label: "Email", value: user.email },
            { label: "Roles", value: roleLabel(user.roles) },
            { label: "Member since", value: joined(user.created_at) },
          ]}
          footnote="An administrator changes names, emails and roles in Users."
        />
        <InfoCard
          title="Access"
          icon={ShieldCheck}
          rows={[
            { label: "Permissions", value: `${user.permissions?.length ?? 0} granted by your roles` },
            {
              label: "Profiles",
              value:
                user.doctor_id || user.patient_id ? (
                  <span className="account-links">
                    {user.doctor_id && can("doctor:update_own") && <Link to="/doctor/profile">Doctor profile</Link>}
                    {user.patient_id && can("patient:read_own") && <Link to="/profile">Patient profile</Link>}
                  </span>
                ) : null,
            },
          ]}
        />
      </div>
    </div>
  );
}
