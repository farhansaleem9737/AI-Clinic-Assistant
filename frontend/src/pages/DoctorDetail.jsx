import { BadgeCheck, BriefcaseMedical, Building2, CalendarPlus, CircleDollarSign } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import Alert from "../components/Alert";
import Avatar from "../components/Avatar";
import Breadcrumb from "../components/Breadcrumb";
import BookingPanel from "../components/doctors/BookingPanel";
import ProfileTabs from "../components/doctors/ProfileTabs";
import { useAuth } from "../context/useAuth";
import { useFetch } from "../hooks/useFetch";
import { HOME_PATH } from "../routes/navigation";
import { getPublicDoctor } from "../services/doctorService";
import { doctorName, formatFee } from "../utils/format";
import NotFound from "./NotFound";

// The API's availability status covers the coming week (see the directory).
const STATUS = {
  available: { label: "Available for appointments", tone: "ok" },
  busy: { label: "Fully booked this week", tone: "warn" },
  unavailable: { label: "No appointments this week", tone: "danger" },
};

function focusBooking(heading) {
  heading?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  heading?.focus({ preventScroll: true });
}

// Public doctor profile, loaded from the API by the id in the URL.
export default function DoctorDetail() {
  const { id } = useParams();
  const { hash } = useLocation();
  const { user, can } = useAuth();
  const [attempt, setAttempt] = useState(0);
  const { data: doctor, loading, error, status } = useFetch(() => getPublicDoctor(id), [id, attempt]);
  const bookingHeading = useRef(null);

  // "Change time" on the confirmation step links back to /doctors/:id#book.
  useEffect(() => {
    if (doctor && hash === "#book") focusBooking(bookingHeading.current);
  }, [doctor, hash]);

  if (status === 404 || status === 422) {
    return <NotFound message="This doctor does not exist or is not listed any more." backLabel="All doctors" />;
  }
  if (error) {
    return (
      <div className="card">
        <Alert>{error}</Alert>
        <div className="row">
          <button type="button" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
          <Link to="/doctors" className="button secondary">
            All doctors
          </Link>
        </div>
      </div>
    );
  }
  if (loading || !doctor) return <div className="card skeleton" style={{ height: 260 }} role="status" aria-label="Loading doctor" />;

  const name = doctorName(doctor);
  const badge = STATUS[doctor.availability.status] ?? STATUS.unavailable;
  const mayBook = !user || can("appointment:create") || can("appointment:create_own");

  return (
    <div className="doctor-profile">
      <Breadcrumb
        items={[
          { label: "Home", to: user ? HOME_PATH : "/" },
          { label: "Doctors", to: "/doctors" },
          { label: name },
        ]}
      />

      <section className="card doctor-summary" aria-label="Summary">
        <Avatar name={doctor.name} role="doctor" size={128} />
        <div className="doctor-summary-main">
          <h1>
            {name}
            {doctor.is_verified && (
              <BadgeCheck className="verified" size={26} role="img" aria-label="Verified: medical license on file" />
            )}
          </h1>
          <p className="specialization">{doctor.specialization}</p>
          <p className="muted">{doctor.department_name}</p>
          <ul className="doctor-summary-facts">
            {doctor.years_of_experience > 0 && (
              <li>
                <BriefcaseMedical size={22} aria-hidden="true" />
                <span>
                  <strong>{doctor.years_of_experience} years</strong>
                  <small className="muted">experience</small>
                </span>
              </li>
            )}
            <li>
              <Building2 size={22} aria-hidden="true" />
              <span>
                <Link to={`/doctors?department=${doctor.department_id}`}>
                  <strong>{doctor.department_name}</strong>
                </Link>
                <small className="muted">Department</small>
              </span>
            </li>
            {doctor.consultation_fee != null && (
              <li>
                <CircleDollarSign size={22} aria-hidden="true" />
                <span>
                  <strong>{formatFee(doctor.consultation_fee)}</strong>
                  <small className="muted">Consultation fee</small>
                </span>
              </li>
            )}
          </ul>
        </div>
        <div className="doctor-summary-side">
          <span className={`badge status ${badge.tone}`}>
            <span className="dot" aria-hidden="true" />
            {badge.label}
          </span>
          {mayBook && (
            <button type="button" className="large" onClick={() => focusBooking(bookingHeading.current)}>
              <CalendarPlus size={18} aria-hidden="true" /> Book appointment
            </button>
          )}
        </div>
      </section>

      <div className="doctor-profile-grid">
        <ProfileTabs doctor={doctor} name={name} />
        <BookingPanel doctor={doctor} headingRef={bookingHeading} />
      </div>
    </div>
  );
}
