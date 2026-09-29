import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";
import { useAuth } from "../context/useAuth";
import { listAppointments } from "../services/appointmentService";
import { ACTIVE_STATUSES } from "../utils/appointments";
import { formatDateTime, isoDateIn } from "../utils/datetime";
import { doctorName } from "../utils/format";

const READ = ["appointment:read_own", "appointment:read_assigned", "appointment:read_any"];

export default function Dashboard() {
  const { user, can } = useAuth();
  const canSeeAppointments = READ.some(can);
  const [upcoming, setUpcoming] = useState(null);

  useEffect(() => {
    if (!canSeeAppointments) return;
    listAppointments({ status: ACTIVE_STATUSES, date_from: isoDateIn(new Date()), page_size: 5 })
      .then((res) => setUpcoming(res.data))
      .catch(() => setUpcoming({ items: [], total: 0 }));
  }, [canSeeAppointments]);

  return (
    <div>
      <div className="card">
        <h2>Welcome, {user.name}</h2>
        <p className="muted">{user.email}</p>
        <p>
          {user.roles.length
            ? user.roles.map((r) => (
                <span key={r} className="badge">
                  {r}
                </span>
              ))
            : "No role assigned"}
        </p>
      </div>

      {canSeeAppointments && (
        <div className="card">
          <div className="spread">
            <h3>Upcoming appointments</h3>
            <Link to="/appointments">See all</Link>
          </div>
          {upcoming === null && <p className="muted">Loading…</p>}
          {upcoming?.items.length === 0 && <p className="muted">Nothing scheduled.</p>}
          {upcoming?.items.map((a) => (
            <p key={a.id} className="spread">
              <Link to={`/appointments/${a.id}`}>{formatDateTime(a.starts_at, a.timezone)}</Link>
              <span>
                {user.patient_id ? doctorName(a.doctor) : a.patient.name}
              </span>
              <StatusBadge status={a.status} />
            </p>
          ))}
          {(can("appointment:create") || can("appointment:create_own")) && (
            <Link to="/appointments/book">
              <button>Book an appointment</button>
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
