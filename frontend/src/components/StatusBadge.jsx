import { CircleCheck, CircleDot, CircleX, Clock3, Hourglass, Stethoscope, UserCheck, UserX } from "lucide-react";
import { STATUS_LABELS, statusTone } from "../utils/appointments";

const ICONS = {
  requested: Hourglass,
  scheduled: Clock3,
  confirmed: CircleCheck,
  checked_in: UserCheck,
  in_progress: Stethoscope,
  completed: CircleDot,
  cancelled: CircleX,
  no_show: UserX,
};

// The status is always written out; the colour and optional icon only repeat it.
export default function StatusBadge({ status, icon = false }) {
  const Icon = icon ? ICONS[status] : null;
  return (
    <span className={`badge ${statusTone(status)}${Icon ? " with-icon" : ""}`}>
      {Icon && <Icon size={14} aria-hidden="true" />}
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}
