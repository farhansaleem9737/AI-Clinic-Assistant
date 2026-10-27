import { CalendarClock, CalendarDays, ClipboardList, DoorOpen, Hourglass, List, Pencil, Stethoscope, UserRound, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { useFetch } from "../../hooks/useFetch";
import { listAppointments } from "../../services/appointmentService";
import { getMyDoctorProfile } from "../../services/doctorService";
import { ACTIVE_STATUSES } from "../../utils/appointments";
import { addDays } from "../../utils/datetime";
import { doctorName, formatFee } from "../../utils/format";
import Avatar from "../Avatar";
import EmptyState from "../EmptyState";
import SectionCard from "../SectionCard";
import StatCard from "../StatCard";
import AppointmentCalendar from "./AppointmentCalendar";
import AppointmentList from "./AppointmentList";
import QuickActions from "./QuickActions";

const ACTIONS = [
  { to: "/appointments", label: "Appointments", hint: "All my visits", icon: List },
  { to: "/schedule", label: "My Schedule", hint: "Hours and time off", icon: CalendarClock },
  { to: "/doctors", label: "Directory", hint: "Clinic doctors", icon: Stethoscope },
  { to: "/doctor/profile", label: "My Profile", hint: "Bio and contact", icon: UserRound },
];

// Everything on today's list except visits that were cancelled.
const TODAY_STATUSES = [...ACTIVE_STATUSES, "completed", "no_show"];

function ProfileCard() {
  const { data: profile, loading, error } = useFetch(getMyDoctorProfile, []);
  return (
    <SectionCard title="My Profile" icon={UserRound} moreTo="/doctor/profile" moreLabel="View profile" loading={loading} error={error}>
      {profile && (
        <>
          <div className="profile-head">
            <Avatar name={profile.name} role="doctor" size={72} src={profile.photo_url} />
            <div>
              <h3 style={{ marginBottom: "0.15rem" }}>{doctorName(profile)}</h3>
              <div className="muted">
                {profile.specialization} · {profile.department_name}
              </div>
            </div>
          </div>
          <dl className="profile-facts">
            <div>
              <dt>Room</dt>
              <dd>{profile.room_number ?? "—"}</dd>
            </div>
            <div>
              <dt>License</dt>
              <dd>{profile.license_number ?? "—"}</dd>
            </div>
            <div>
              <dt>Experience</dt>
              <dd>{profile.years_of_experience} years</dd>
            </div>
            <div>
              <dt>Fee</dt>
              <dd>{formatFee(profile.consultation_fee)}</dd>
            </div>
          </dl>
          <Link to="/doctor/profile">
            <button type="button" className="secondary block">
              <Pencil size={16} aria-hidden="true" /> Edit Profile
            </button>
          </Link>
        </>
      )}
    </SectionCard>
  );
}

function Workload({ figures }) {
  const today = figures.today;
  const todays = useFetch(
    () => listAppointments({ status: TODAY_STATUSES, date_from: today.date, date_to: today.date, page_size: 20 }),
    [today.date]
  );
  const upcoming = useFetch(
    () => listAppointments({ status: ACTIVE_STATUSES, date_from: addDays(today.date, 1), page_size: 5 }),
    [today.date]
  );

  return (
    <>
      <div className="stat-grid">
        <StatCard
          icon={CalendarDays}
          label="Today's Appointments"
          value={today.total - today.cancelled}
          to={`/appointments?date=${today.date}`}
        />
        <StatCard icon={DoorOpen} tone="amber" label="Waiting (checked in)" value={today.checked_in} note="Ready to be seen" />
        <StatCard icon={Hourglass} label="Upcoming Appointments" value={figures.upcoming_appointments} to="/appointments" />
        <StatCard icon={Users} tone="green" label="My Patients" value={figures.my_patients} note="With booked or past visits" />
      </div>

      <div className="dash-grid">
        <div className="dash-col">
          <SectionCard
            title="Today's Appointments"
            icon={ClipboardList}
            moreTo={`/appointments?date=${today.date}`}
            loading={todays.loading}
            error={todays.error}
          >
            <AppointmentList
              appointments={todays.data?.items ?? []}
              perspective="doctor"
              emptyText="No appointments today."
            />
          </SectionCard>
          <QuickActions actions={ACTIONS} />
          <SectionCard
            title="Upcoming Appointments"
            icon={CalendarDays}
            moreTo="/appointments"
            loading={upcoming.loading}
            error={upcoming.error}
          >
            <AppointmentList
              appointments={upcoming.data?.items ?? []}
              perspective="doctor"
              emptyText="Nothing booked after today."
            />
          </SectionCard>
        </div>
        <div className="dash-col">
          <AppointmentCalendar />
          <ProfileCard />
        </div>
      </div>
    </>
  );
}

export default function DoctorDashboard({ summary }) {
  if (!summary.doctor.has_profile) {
    return (
      <div className="card">
        <EmptyState icon={Stethoscope}>
          Your login has the doctor role but no doctor profile yet. Ask an administrator to create it.
        </EmptyState>
      </div>
    );
  }
  return <Workload figures={summary.doctor} />;
}
