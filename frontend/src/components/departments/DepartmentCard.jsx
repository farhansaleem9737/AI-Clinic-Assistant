import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { doctorLabel } from "../../utils/departments";
import Avatar from "../Avatar";
import DepartmentIcon from "./DepartmentIcon";

/** Up to three doctors' avatars, "+N" for the rest, and the count (same doctors). */
export function DoctorAvatarGroup({ count, preview }) {
  // An older server sends no doctor fields: say so instead of guessing (or crashing).
  if (typeof count !== "number" || !Array.isArray(preview)) {
    return (
      <div className="dept-card-doctors">
        <span className="muted">Doctor count unavailable</span>
      </div>
    );
  }
  const more = count - preview.length;
  return (
    <div className="dept-card-doctors">
      {count > 0 && (
        <span className="avatar-stack" aria-hidden="true">
          {preview.map((d) => (
            <span key={d.id} className="avatar-stack-item" title={doctorLabel(d)}>
              <Avatar name={d.name} role="doctor" src={d.photo_url} size={36} />
            </span>
          ))}
          {more > 0 && <span className="avatar-stack-more">+{more}</span>}
        </span>
      )}
      <span className="muted">
        {count} doctor{count === 1 ? "" : "s"}
      </span>
    </div>
  );
}

/**
 * One department as a card (D93 / D94), shared by Admin > Departments and the
 * patient / visitor page. `doctorsTo` is where View Doctors goes. Admin-only
 * pieces come in through props: `status` (badge), `menu` (actions) and
 * `onOpen` (name opens the details); the patient card has none of them.
 */
export default function DepartmentCard({ department: d, doctorsTo, emptyDescription, status, menu, onOpen }) {
  return (
    <li className="card dept-card" aria-label={d.name}>
      <div className="dept-card-head">
        <DepartmentIcon department={d} size={58} square />
        <div className="dept-card-title">
          <h2>
            {onOpen ? (
              <button type="button" className="link-button" onClick={onOpen}>
                {d.name}
              </button>
            ) : (
              d.name
            )}
          </h2>
          {status}
          {!status && (
            <p className={`dept-card-description${d.description ? "" : " muted"}`}>{d.description || emptyDescription}</p>
          )}
        </div>
        {menu}
      </div>
      {status && <p className={`dept-card-description${d.description ? "" : " muted"}`}>{d.description || emptyDescription}</p>}
      <DoctorAvatarGroup count={d.doctor_count} preview={d.doctors_preview} />
      <Link to={doctorsTo} className="button dept-view-doctors" aria-label={`View doctors in ${d.name}`}>
        View Doctors <ArrowRight size={18} aria-hidden="true" />
      </Link>
    </li>
  );
}
