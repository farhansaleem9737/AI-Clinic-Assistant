import { STATUS_LABELS, statusTone } from "../utils/appointments";

export default function StatusBadge({ status }) {
  return <span className={`badge ${statusTone(status)}`}>{STATUS_LABELS[status] ?? status}</span>;
}
