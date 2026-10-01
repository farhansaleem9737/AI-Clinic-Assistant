import {
  CalendarDays,
  CalendarPlus,
  Cake,
  CheckCircle2,
  CircleAlert,
  Headset,
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
import Avatar from "../Avatar";
import EmptyState from "../EmptyState";
import SectionCard from "../SectionCard";
import StatCard from "../StatCard";
import AppointmentList from "./AppointmentList";
import QuickActions from "./QuickActions";

const ACTIONS = [
  { to: "/appointments/book", label: "Book Appointment", hint: "Schedule with a doctor", icon: CalendarPlus },
  { to: "/doctors", label: "Find Doctor", hint: "Search by specialty", icon: Search },
  { to: "/appointments", label: "View Appointments", hint: "Check your visits", icon: List },
  { to: "/profile", label: "My Profile", hint: "Update your information", icon: UserRound },
];

const SEX_LABELS = { male: "Male", female: "Female", intersex: "Intersex", unknown: "Not recorded" };

function accountStatus(summary) {
  if (!summary.patient.has_profile) return { value: "Incomplete", good: false, note: "Complete your profile" };
  if (!summary.account.is_active || !summary.patient.profile_active)
    return { value: "Inactive", good: false, note: "Contact reception" };
  return { value: "Active", good: true, note: "All good" };
}

// "1990-01-01" -> "Jan 1, 1990", without any timezone shift.
function formatBirthDate(isoDate) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${isoDate}T00:00:00Z`));
}

function Fact({ icon: Icon, label, children }) {
  return (
    <div>
      <dt>
        <Icon size={16} aria-hidden="true" /> {label}
      </dt>
      <dd>{children || <span className="muted">Not provided</span>}</dd>
    </div>
  );
}

function ProfileCard({ hasProfile, active }) {
  const { data: profile, loading, error } = useFetch(getMyPatientProfile, [], { enabled: hasProfile });

  return (
    <SectionCard title="My Profile" icon={UserRound} moreTo="/profile" moreLabel="View profile" loading={loading} error={error}>
      {!profile ? (
        <EmptyState
          icon={UserRound}
          action={
            <Link to="/profile" className="button">
              Complete profile
            </Link>
          }
        >
          Your patient profile is not set up yet. Complete it to book appointments.
        </EmptyState>
      ) : (
        <>
          <div className="profile-head">
            <Avatar name={`${profile.first_name} ${profile.last_name}`} size={92} />
            <div>
              <h3>
                {profile.first_name} {profile.last_name}
              </h3>
              <div className="mrn">{profile.mrn}</div>
              {active ? (
                <span className="badge ok status-pill">
                  <CheckCircle2 size={15} aria-hidden="true" /> Active
                </span>
              ) : (
                <span className="badge danger status-pill">
                  <CircleAlert size={15} aria-hidden="true" /> Inactive
                </span>
              )}
            </div>
          </div>
          <dl className="profile-facts list">
            <Fact icon={Cake} label="Date of birth">
              {profile.date_of_birth && formatBirthDate(profile.date_of_birth)}
            </Fact>
            <Fact icon={UserRound} label="Sex at birth">
              {SEX_LABELS[profile.sex_at_birth] ?? profile.sex_at_birth}
            </Fact>
            <Fact icon={Phone} label="Phone">
              {profile.phone}
            </Fact>
            <Fact icon={Mail} label="Email">
              {profile.email}
            </Fact>
            <Fact icon={MapPin} label="Address">
              {profile.address}
            </Fact>
          </dl>
          <Link to="/profile" className="button secondary block">
            <Pencil size={16} aria-hidden="true" /> Edit Profile
          </Link>
        </>
      )}
    </SectionCard>
  );
}

function HelpCard() {
  return (
    <section className="card help-card" aria-label="Need Help?">
      <div className="help-head">
        <span className="help-icon">
          <Headset size={22} aria-hidden="true" />
        </span>
        <div>
          <h3>Need Help?</h3>
          <p className="muted small">Answers about booking, changing appointments and your account, and how to reach the clinic.</p>
        </div>
      </div>
      <Link to="/help#contact" className="button secondary block">
        <Headset size={17} aria-hidden="true" /> Contact Support
      </Link>
    </section>
  );
}

/**
 * The patient's home page. Counts come from the dashboard summary; the
 * upcoming list uses the appointment list's `upcoming` filter, which is the
 * same definition the count uses, so the two always agree.
 */
export default function PatientDashboard({ summary }) {
  const figures = summary.patient;
  const status = accountStatus(summary);
  const upcoming = useFetch(() => listAppointments({ scope: "upcoming", page_size: 3 }), [], {
    enabled: figures.has_profile,
  });

  return (
    <>
      <div className="stat-grid">
        <StatCard icon={CalendarDays} label="Upcoming Appointments" value={figures.upcoming_appointments} to="/appointments" />
        <StatCard icon={Stethoscope} label="Total Appointments" value={figures.total_appointments} to="/appointments" />
        <StatCard icon={Users} label="My Doctors" value={figures.my_doctors} to="/doctors" linkLabel="View doctors" />
        <StatCard icon={HeartPulse} tone="green" label="Account Status" value={status.value} good={status.good} note={status.note} />
      </div>

      <div className="patient-grid">
        <SectionCard
          title="Upcoming Appointments"
          icon={CalendarDays}
          moreTo="/appointments"
          loading={upcoming.loading}
          error={upcoming.error}
        >
          <AppointmentList
            appointments={upcoming.data?.items ?? []}
            emptyText="No upcoming appointments."
            emptyAction={
              <Link to="/doctors" className="button">
                <Search size={16} aria-hidden="true" /> Find a doctor
              </Link>
            }
          />
        </SectionCard>
        <ProfileCard hasProfile={figures.has_profile} active={summary.account.is_active && figures.profile_active} />
        <QuickActions actions={ACTIONS} />
        <HelpCard />
      </div>
    </>
  );
}
