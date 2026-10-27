import { BadgeCheck, BriefcaseMedical, CircleDollarSign } from "lucide-react";
import { Link } from "react-router-dom";
import { doctorName, formatFee } from "../../utils/format";
import Avatar from "../Avatar";
import AvailabilityBadge from "./AvailabilityBadge";
import BookButton from "./BookButton";

// One doctor in the directory. The same component serves the grid and the
// list view; only the CSS layout differs.
export default function DoctorCard({ doctor }) {
  const name = doctorName(doctor);
  const lastWord = name.lastIndexOf(" ") + 1;
  return (
    <article className="card doctor-card" aria-label={name}>
      <div className="doctor-card-head">
        <Avatar name={doctor.name} role="doctor" size={88} src={doctor.photo_url} />
        <div className="doctor-card-id">
          <h3>
            <Link to={`/doctors/${doctor.id}`}>
              {name.slice(0, lastWord)}
              {/* The verified mark stays on the line of the last word. */}
              <span className="nowrap">
                {name.slice(lastWord)}
                {doctor.is_verified && (
                  <BadgeCheck className="verified" size={20} role="img" aria-label="Verified: medical license on file" />
                )}
              </span>
            </Link>
          </h3>
          <p className="specialization">{doctor.specialization}</p>
          <p className="muted">{doctor.department_name}</p>
        </div>
        <AvailabilityBadge status={doctor.availability.status} />
      </div>

      <div className="doctor-card-facts">
        <span>
          <BriefcaseMedical size={20} aria-hidden="true" />
          {doctor.years_of_experience} years experience
        </span>
        <span>
          <CircleDollarSign size={24} aria-hidden="true" />
          <span className="fee">
            <strong>{formatFee(doctor.consultation_fee)}</strong>
            <small className="muted">Consultation fee</small>
          </span>
        </span>
      </div>

      <div className="doctor-card-actions">
        <Link to={`/doctors/${doctor.id}`} className="button secondary">
          View profile
        </Link>
        <BookButton doctor={doctor} />
      </div>
    </article>
  );
}
