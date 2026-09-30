import { CalendarDays, ShieldQuestion } from "lucide-react";
import Alert from "../components/Alert";
import EmptyState from "../components/EmptyState";
import DoctorDashboard from "../components/dashboard/DoctorDashboard";
import FrontDeskDashboard from "../components/dashboard/FrontDeskDashboard";
import PatientDashboard from "../components/dashboard/PatientDashboard";
import { useAuth } from "../context/useAuth";
import { useFetch } from "../hooks/useFetch";
import { getDashboardSummary } from "../services/dashboardService";

const SUBTITLES = {
  patient: "Here's your healthcare overview.",
  doctor: "Here's your day at a glance.",
  front_desk: "Here's what's happening at the clinic today.",
};

function greeting(hour) {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/**
 * One dashboard for every role. The API returns only the sections this user
 * is entitled to; whichever sections arrive are the ones rendered, so the
 * page cannot show a role's data the server did not send.
 */
export default function Dashboard() {
  const { user } = useAuth();
  const { data: summary, loading, error } = useFetch(getDashboardSummary, []);
  const now = new Date();
  const firstName = user.name.replace(/^(Dr\.?|Prof\.?)\s+/i, "").split(" ")[0];

  const sections = summary
    ? [
        summary.patient && { key: "patient", element: <PatientDashboard summary={summary} /> },
        summary.doctor && { key: "doctor", element: <DoctorDashboard summary={summary} /> },
        summary.front_desk && { key: "front_desk", element: <FrontDeskDashboard summary={summary} /> },
      ].filter(Boolean)
    : [];

  return (
    <div>
      <div className="dash-head">
        <div>
          <h1>
            {greeting(now.getHours())}, {firstName}!
          </h1>
          <span className="muted">{SUBTITLES[sections[0]?.key] ?? "Welcome to Clinic AI Assistant."}</span>
        </div>
        <span className="date">
          <CalendarDays size={18} aria-hidden="true" />
          {new Intl.DateTimeFormat(undefined, { weekday: "long", month: "short", day: "numeric", year: "numeric" }).format(now)}
        </span>
      </div>

      <Alert>{error}</Alert>

      {loading && (
        <div className="stat-grid" role="status" aria-label="Loading dashboard">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card skeleton" style={{ height: 96, margin: 0 }} />
          ))}
        </div>
      )}

      {sections.map(({ key, element }) => (
        <div key={key}>{element}</div>
      ))}

      {summary && sections.length === 0 && (
        <div className="card">
          <EmptyState icon={ShieldQuestion}>
            Your account has no role with a dashboard yet. Ask an administrator to assign you one.
          </EmptyState>
        </div>
      )}
    </div>
  );
}
