import { CalendarPlus } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../../context/useAuth";

/**
 * "Book appointment" for one doctor.
 *
 * - Doctor unavailable: shown disabled (the API would refuse the booking too).
 * - Visitor not signed in: links to the booking page, which sends them
 *   through sign-in and back.
 * - Signed in without permission to book (e.g. a doctor): not shown.
 */
export default function BookButton({ doctor, slot, className = "" }) {
  const { user, can } = useAuth();
  if (user && !can("appointment:create") && !can("appointment:create_own")) return null;

  const label = (
    <>
      <CalendarPlus size={17} aria-hidden="true" /> Book appointment
    </>
  );
  if (doctor.availability.status === "unavailable") {
    return (
      <button type="button" className={className} disabled title="This doctor is not taking appointments at the moment">
        {label}
      </button>
    );
  }
  const query = new URLSearchParams({ doctor: doctor.id });
  if (slot) query.set("slot", slot.starts_at);
  return (
    <Link to={`/appointments/book?${query}`} className={`button ${className}`}>
      {label}
    </Link>
  );
}
