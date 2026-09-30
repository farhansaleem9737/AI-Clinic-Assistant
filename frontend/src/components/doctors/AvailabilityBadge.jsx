import { AVAILABILITY } from "../../utils/doctors";

// Available / Busy / Unavailable, as computed by the API from the doctor's
// working hours, leave and existing bookings.
export default function AvailabilityBadge({ status }) {
  const { label, tone } = AVAILABILITY[status] ?? AVAILABILITY.unavailable;
  return (
    <span className={`badge status ${tone}`}>
      <span className="dot" aria-hidden="true" />
      {label}
    </span>
  );
}
