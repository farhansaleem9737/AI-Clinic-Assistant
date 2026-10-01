import { ChevronRight, History } from "lucide-react";
import { Link } from "react-router-dom";
import { useFetch } from "../../hooks/useFetch";
import { listAppointments } from "../../services/appointmentService";
import { formatDateTime } from "../../utils/datetime";
import { doctorName } from "../../utils/format";
import Avatar from "../Avatar";
import EmptyState from "../EmptyState";
import SectionCard from "../SectionCard";
import StatusBadge from "../StatusBadge";

// The caller's latest appointments, newest first. The API already limits the
// list to what this user may see.
export default function RecentAppointments({ showPatient = false }) {
  const { data, loading, error } = useFetch(() => listAppointments({ newest_first: true, page_size: 5 }), []);
  const items = data?.items ?? [];

  return (
    <SectionCard title="Recent Appointments" icon={History} moreTo="/appointments" loading={loading} error={error}>
      {items.length === 0 ? (
        <EmptyState icon={History}>No appointments yet.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date &amp; Time</th>
                <th>{showPatient ? "Patient" : "Doctor"}</th>
                <th className="hide-sm">Specialization</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td className="small">{formatDateTime(a.starts_at, a.timezone)}</td>
                  <td>
                    <span className="row" style={{ flexWrap: "nowrap" }}>
                      <span className="hide-sm">
                        <Avatar name={showPatient ? a.patient.name : a.doctor.name} role={showPatient ? undefined : "doctor"} size={30} />
                      </span>
                      {showPatient ? a.patient.name : doctorName(a.doctor)}
                    </span>
                  </td>
                  <td className="muted small hide-sm">{a.doctor.specialization}</td>
                  <td>
                    <StatusBadge status={a.status} />
                  </td>
                  <td>
                    <Link className="link-more" to={`/appointments/${a.id}`} aria-label="View details">
                      <span className="hide-sm">View details</span> <ChevronRight size={14} aria-hidden="true" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}
