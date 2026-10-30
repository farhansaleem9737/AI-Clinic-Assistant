import {
  Building2,
  CalendarCheck,
  CalendarClock,
  CalendarDays,
  CalendarPlus,
  ClipboardList,
  DoorOpen,
  Hourglass,
  LayoutGrid,
  List,
  ShieldCheck,
  Stethoscope,
  UserPlus,
  Users,
} from "lucide-react";
import { useAuth } from "../../context/useAuth";
import { useFetch } from "../../hooks/useFetch";
import { listAppointments } from "../../services/appointmentService";
import { ACTIVE_STATUSES } from "../../utils/appointments";
import SectionCard from "../SectionCard";
import StatCard from "../StatCard";
import AppointmentList from "./AppointmentList";
import PreviewNote from "./PreviewNote";
import QuickActions from "./QuickActions";
import RecentAppointments from "./RecentAppointments";

const ALL_ACTIONS = [
  { to: "/appointments/book", label: "Book Appointment", hint: "For any patient", icon: CalendarPlus, permission: "appointment:create" },
  { to: "/patients", label: "Patients", hint: "Find or register", icon: UserPlus, permission: "patient:read_any" },
  { to: "/schedule", label: "Doctor Schedules", hint: "Hours and time off", icon: CalendarClock, permission: "schedule:manage_any" },
  { to: "/appointments", label: "All Appointments", hint: "Search and manage", icon: List, permission: "appointment:read_any" },
];

// Clinic totals. A figure is shown only if the API returned it, which it does
// only when this user is allowed to list those records.
const OVERVIEW = [
  { key: "users_active", label: "Active users", icon: ShieldCheck, to: "/admin/users", of: "users_total" },
  { key: "doctors_active", label: "Active doctors", icon: Stethoscope, to: "/admin/doctors" },
  { key: "departments_active", label: "Departments", icon: Building2, to: "/admin/departments" },
  { key: "patients_active", label: "Active patients", icon: Users, to: "/patients", of: "patients_total" },
  { key: "appointments_total", label: "Appointments (all time)", icon: CalendarDays, to: "/appointments" },
];

export default function FrontDeskDashboard({ summary }) {
  const { can } = useAuth();
  const { today, upcoming_appointments: upcoming } = summary.front_desk;
  const overview = summary.overview ?? {};
  const figures = OVERVIEW.filter((item) => overview[item.key] != null);
  const actions = ALL_ACTIONS.filter((action) => can(action.permission));

  // People still to be seen today, in time order: the check-in worklist.
  const worklist = useFetch(
    () => listAppointments({ status: ACTIVE_STATUSES, date_from: today.date, date_to: today.date, page_size: 20 }),
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
        <StatCard icon={Hourglass} tone="amber" label="Awaiting Check-in" value={today.awaiting_check_in} note="Not arrived yet" />
        <StatCard icon={DoorOpen} label="Checked In" value={today.checked_in + today.in_progress} note={`${today.in_progress} in consultation`} />
        <StatCard icon={CalendarCheck} tone="green" label="Completed Today" value={today.completed} note={`${upcoming} upcoming in total`} />
      </div>

      <div className="dash-grid">
        <div className="dash-col">
          <SectionCard
            title="Today's Worklist"
            icon={ClipboardList}
            moreTo={`/appointments?date=${today.date}`}
            loading={worklist.loading}
            error={worklist.error}
          >
            <AppointmentList
              appointments={worklist.data?.items ?? []}
              perspective="front_desk"
              emptyText="No patients waiting or expected for the rest of today."
            />
            <PreviewNote shown={worklist.data?.items.length ?? 0} total={worklist.data?.total} noun="appointments on the worklist" to={`/appointments?date=${today.date}`} />
          </SectionCard>
          {actions.length > 0 && <QuickActions actions={actions} />}
        </div>

        <div className="dash-col">
          {figures.length > 0 && (
            <section className="card" aria-label="Clinic Overview">
              <div className="section-head">
                <LayoutGrid className="icon" size={20} aria-hidden="true" />
                <h3>Clinic Overview</h3>
              </div>
              <div className="dash-pair">
                {figures.map(({ key, label, icon, to, of }) => (
                  <StatCard
                    key={key}
                    icon={icon}
                    label={label}
                    value={overview[key]}
                    to={to}
                    linkLabel={of && overview[of] != null ? `of ${overview[of]} · open` : "Open"}
                  />
                ))}
              </div>
            </section>
          )}
          <RecentAppointments showPatient />
        </div>
      </div>
    </>
  );
}
