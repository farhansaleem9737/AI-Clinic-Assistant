import {
  Cake,
  CalendarDays,
  CalendarPlus,
  HeartPulse,
  List,
  Mail,
  MapPin,
  Pencil,
  Phone,
  Search,
  Stethoscope,
  UserRound,
  Users,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useFetch } from "../../hooks/useFetch";
import { listAppointments } from "../../services/appointmentService";
import { getMyPatientProfile } from "../../services/patientService";
import { ACTIVE_STATUSES } from "../../utils/appointments";
import { isoDateIn } from "../../utils/datetime";
import Avatar from "../Avatar";
import EmptyState from "../EmptyState";
import SectionCard from "../SectionCard";
import StatCard from "../StatCard";
import AppointmentCalendar from "./AppointmentCalendar";
import AppointmentList from "./AppointmentList";
import QuickActions from "./QuickActions";
import RecentAppointments from "./RecentAppointments";

const ACTIONS = [
  { to: "/appointments/book", label: "Book Appointment", hint: "Schedule with a doctor", icon: CalendarPlus },
  { to: "/doctors", label: "Find Doctor", hint: "Search by specialty", icon: Search },
  { to: "/appointments", label: "View Appointments", hint: "Check upcoming visits", icon: List },
  { to: "/profile", label: "My Profile", hint: "Update your information", icon: UserRound },
];

function accountStatus(summary) {
  if (!summary.patient.has_profile) return { value: "Incomplete", good: false, note: "Complete your profile" };
  if (!summary.account.is_active || !summary.patient.profile_active)
    return { value: "Inactive", good: false, note: "Contact reception" };
  return { value: "Active", good: true, note: "All good" };
}

function ProfileCard({ hasProfile }) {
  const { data: profile, loading, error } = useFetch(getMyPatientProfile, [], { enabled: hasProfile });

  return (
    <SectionCard title="My Profile" icon={UserRound} moreTo="/profile" moreLabel="View profile" loading={loading} error={error}>
      {!profile ? (
        <EmptyState
          icon={UserRound}
          action={
            <Link to="/profile">
              <button type="button">Complete profile</button>
            </Link>
          }
        >
          Your patient profile is not set up yet. Complete it to book appointments.
        </EmptyState>
      ) : (
        <>
          <div className="profile-head">
            <Avatar name={`${profile.first_name} ${profile.last_name}`} size={84} />
            <div>
              <h3 style={{ marginBottom: "0.15rem" }}>
                {profile.first_name} {profile.last_name}
              </h3>
              <div className="muted">{profile.mrn}</div>
            </div>
          </div>
          <dl className="profile-facts">
            <div>
              <dt>
                <Cake size={15} aria-hidden="true" /> Date of birth
              </dt>
              <dd>{profile.date_of_birth}</dd>
            </div>
            <div>
              <dt>
                <UserRound size={15} aria-hidden="true" /> Sex at birth
              </dt>
              <dd style={{ textTransform: "capitalize" }}>{profile.sex_at_birth}</dd>
            </div>
            <div>
              <dt>
                <Phone size={15} aria-hidden="true" /> Phone
              </dt>
              <dd>{profile.phone ?? "—"}</dd>
            </div>
            <div>
              <dt>
                <Mail size={15} aria-hidden="true" /> Email
              </dt>
              <dd>{profile.email ?? "—"}</dd>
            </div>
            <div>
              <dt>
                <MapPin size={15} aria-hidden="true" /> Address
              </dt>
              <dd>{profile.address ?? "—"}</dd>
            </div>
          </dl>
          <Link to="/profile">
            <button type="button" className="secondary block">
              <Pencil size={16} aria-hidden="true" /> Edit Profile
            </button>
          </Link>
        </>
      )}
    </SectionCard>
  );
}

export default function PatientDashboard({ summary }) {
  const figures = summary.patient;
  const status = accountStatus(summary);
  const upcoming = useFetch(
    () => listAppointments({ status: ACTIVE_STATUSES, date_from: isoDateIn(new Date()), page_size: 3 }),
    []
  );

  return (
    <>
      <div className="stat-grid">
        <StatCard icon={CalendarDays} label="Upcoming Appointments" value={figures.upcoming_appointments} to="/appointments" />
        <StatCard icon={Stethoscope} label="Total Appointments" value={figures.total_appointments} to="/appointments" />
        <StatCard icon={Users} label="My Doctors" value={figures.my_doctors} to="/doctors" linkLabel="View doctors" />
        <StatCard icon={HeartPulse} tone="green" label="Account Status" value={status.value} good={status.good} note={status.note} />
      </div>

      <div className="dash-grid">
        <div className="dash-col">
          <SectionCard
            title="Upcoming Appointments"
            icon={CalendarDays}
            moreTo="/appointments"
            loading={upcoming.loading}
            error={upcoming.error}
          >
            <AppointmentList
              appointments={upcoming.data?.items ?? []}
              emptyText="You have no upcoming appointments."
              emptyAction={
                <Link to="/appointments/book">
                  <button type="button">Book an appointment</button>
                </Link>
              }
            />
          </SectionCard>
          <QuickActions actions={ACTIONS} />
          <RecentAppointments />
        </div>

        <div className="dash-col">
          <div className="dash-pair">
            <AppointmentCalendar />
            <div className="dash-col">
              <section className="card" aria-label="Find a Doctor">
                <div className="section-head">
                  <Stethoscope className="icon" size={20} aria-hidden="true" />
                  <h3>Find a Doctor</h3>
                </div>
                <p className="muted small">Search and book appointments with our specialists.</p>
                <Link to="/doctors">
                  <button type="button" className="block">
                    <Search size={16} aria-hidden="true" /> Search Doctors
                  </button>
                </Link>
              </section>
              <section className="card" aria-label="Book Appointment">
                <div className="section-head">
                  <CalendarPlus className="icon" size={20} aria-hidden="true" />
                  <h3>Book Appointment</h3>
                </div>
                <p className="muted small">Schedule your next appointment quickly.</p>
                <Link to="/appointments/book">
                  <button type="button" className="soft block">
                    <CalendarPlus size={16} aria-hidden="true" /> Book Appointment
                  </button>
                </Link>
              </section>
            </div>
          </div>
          <ProfileCard hasProfile={figures.has_profile} />
        </div>
      </div>
    </>
  );
}
