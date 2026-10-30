import { CalendarDays, CheckCircle2, CircleAlert, Pencil, ShieldCheck, UserRound } from "lucide-react";
import { formatCalendarDate } from "../../utils/datetime";
import { SEX_LABELS, ageFromDateOfBirth, patientFullName } from "../../utils/patient";
import Avatar from "../Avatar";

// `status` comes from the dashboard summary; null means it is unknown, and
// then nothing is shown rather than a guess.
function AccountStatus({ status }) {
  if (!status) return null;
  return status.active ? (
    <span className="badge ok status-pill">
      <CheckCircle2 size={15} aria-hidden="true" /> Active
    </span>
  ) : (
    <span className="badge danger status-pill">
      <CircleAlert size={15} aria-hidden="true" /> Inactive
    </span>
  );
}

function SummaryFact({ icon: Icon, label, value, detail }) {
  return (
    <div className="summary-fact">
      <Icon size={30} strokeWidth={1.6} aria-hidden="true" />
      <div>
        <dt>{label}</dt>
        <dd>
          <strong>{value}</strong>
          {detail && <span>{detail}</span>}
        </dd>
      </div>
    </div>
  );
}

/** Photo, name, MRN, status and key facts at the top of My Profile. */
export default function ProfileSummary({ profile, status, onEdit }) {
  const name = patientFullName(profile);
  const age = ageFromDateOfBirth(profile.date_of_birth);
  return (
    <section className="card profile-summary" aria-label="Profile summary">
      <Avatar name={name} src={profile.photo_url} size={132} alt={`Photo of ${name}`} />
      <div className="profile-summary-id">
        <h2>{name}</h2>
        <p className="role">
          Patient · <span className="mrn">{profile.mrn}</span>
        </p>
        <AccountStatus status={status} />
      </div>
      <dl className="profile-summary-facts">
        <SummaryFact
          icon={CalendarDays}
          label="Date of Birth"
          value={age === null ? "Age unknown" : `${age} ${age === 1 ? "year" : "years"}`}
          detail={profile.date_of_birth && formatCalendarDate(profile.date_of_birth)}
        />
        <SummaryFact icon={UserRound} label="Gender" value={SEX_LABELS[profile.sex_at_birth] ?? "Not recorded"} />
        <SummaryFact icon={ShieldCheck} label="Account Type" value="Patient" />
      </dl>
      <button type="button" className="edit-profile" onClick={onEdit}>
        <Pencil size={16} aria-hidden="true" /> Edit Profile
      </button>
    </section>
  );
}
