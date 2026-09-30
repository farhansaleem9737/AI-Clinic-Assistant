import { ArrowLeft, BadgeCheck, BriefcaseMedical, Building2, CalendarClock, CircleDollarSign, GraduationCap } from "lucide-react";
import { useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import Alert from "../components/Alert";
import Avatar from "../components/Avatar";
import AvailabilityBadge from "../components/doctors/AvailabilityBadge";
import BookButton from "../components/doctors/BookButton";
import SlotPicker from "../components/SlotPicker";
import { useAuth } from "../context/useAuth";
import { useFetch } from "../hooks/useFetch";
import { getPublicDoctor } from "../services/doctorService";
import { formatDateTime } from "../utils/datetime";
import { doctorName, formatFee } from "../utils/format";

const STATUS_TEXT = {
  available: "Taking appointments",
  busy: "Fully booked for the coming week; later dates may be free",
  unavailable: "Not taking appointments at the moment",
};

// Public doctor profile, loaded from the API by the id in the URL.
export default function DoctorDetail() {
  const { id } = useParams();
  const location = useLocation();
  const { user, can } = useAuth();
  const { data: doctor, loading, error } = useFetch(() => getPublicDoctor(id), [id]);
  const [slot, setSlot] = useState(null);

  if (error) {
    return (
      <div className="card">
        <Alert>{error}</Alert>
        <Link to="/doctors">← All doctors</Link>
      </div>
    );
  }
  if (loading || !doctor) return <div className="card skeleton" style={{ height: 260 }} role="status" aria-label="Loading doctor" />;

  const name = doctorName(doctor);
  const { status, next_available: nextAvailable } = doctor.availability;
  const canSeeSlots = user && can("availability:read");

  return (
    <div className="doctor-profile">
      <p>
        <Link to="/doctors" className="link-more">
          <ArrowLeft size={15} aria-hidden="true" /> All doctors
        </Link>
      </p>

      <section className="card doctor-profile-head">
        <Avatar name={doctor.name} size={120} />
        <div className="doctor-card-id">
          <h1>
            {name}
            {doctor.is_verified && (
              <BadgeCheck className="verified" size={24} role="img" aria-label="Verified: medical license on file" />
            )}
          </h1>
          <p className="specialization">{doctor.specialization}</p>
          <p className="muted">{doctor.department_name}</p>
          <p>
            <AvailabilityBadge status={status} /> <span className="muted small">{STATUS_TEXT[status]}</span>
          </p>
        </div>
        <div className="doctor-profile-cta">
          <BookButton doctor={doctor} className="large" />
        </div>
      </section>

      <div className="doctor-profile-body">
        <div className="dash-col">
          <section className="card" aria-label="About">
            <h3>About</h3>
            <p>{doctor.bio ?? "This doctor has not added a biography yet."}</p>
          </section>

          <section className="card" aria-label="Appointment times">
            <div className="section-head">
              <CalendarClock className="icon" size={20} aria-hidden="true" />
              <h3>Appointment times</h3>
            </div>
            {status === "unavailable" ? (
              <p className="muted">This doctor has no bookable times at the moment.</p>
            ) : canSeeSlots ? (
              <>
                <SlotPicker doctorId={doctor.id} selected={slot} onSelect={setSlot} />
                {slot && (
                  <div className="row">
                    <span>
                      Selected: <strong>{formatDateTime(slot.starts_at, slot.timezone)}</strong>
                    </span>
                    <BookButton doctor={doctor} slot={slot} />
                  </div>
                )}
              </>
            ) : (
              <>
                {nextAvailable && <p>Next free time from {formatDateTime(nextAvailable)}.</p>}
                <p className="muted">Sign in to see all available times and book an appointment.</p>
                <div className="row">
                  <Link to="/login" state={{ from: location.pathname }} className="button">
                    Sign in
                  </Link>
                  <Link to="/register" className="button secondary">
                    Create account
                  </Link>
                </div>
              </>
            )}
          </section>
        </div>

        <aside className="card" aria-label="Details">
          <h3>Details</h3>
          <ul className="doctor-facts">
            <li>
              <Building2 size={18} aria-hidden="true" />
              <span>
                <small className="muted">Department</small>
                <Link to={`/doctors?department=${doctor.department_id}`}>{doctor.department_name}</Link>
              </span>
            </li>
            <li>
              <BriefcaseMedical size={18} aria-hidden="true" />
              <span>
                <small className="muted">Experience</small>
                {doctor.years_of_experience} years
              </span>
            </li>
            <li>
              <CircleDollarSign size={18} aria-hidden="true" />
              <span>
                <small className="muted">Consultation fee</small>
                {formatFee(doctor.consultation_fee)}
              </span>
            </li>
            <li>
              <GraduationCap size={18} aria-hidden="true" />
              <span>
                <small className="muted">Qualifications</small>
                {doctor.qualifications ?? "Not listed"}
              </span>
            </li>
          </ul>
        </aside>
      </div>
    </div>
  );
}
