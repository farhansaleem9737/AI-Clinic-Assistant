import { Bell, Building2, CalendarDays, FileText, Home, LogIn, MessageSquareText, Search, Stethoscope, Users } from "lucide-react";
import { Link } from "react-router-dom";
import aiAvatar from "../../assets/clinic-ai-avatar.png";
import Avatar from "../../components/Avatar";
import BrandMark from "../../components/BrandMark";
import { DEMO_STATS } from "./content";

// Illustrative figures only: no real patients, records or API calls.
const APPOINTMENTS = [
  { when: ["Thu", "09:30"], name: "Jamie Demo", ref: "MRN-DEMO-01", status: "Confirmed" },
  { when: ["Thu", "12:00"], name: "Taylor Sample", ref: "MRN-DEMO-02", status: "Confirmed" },
  { when: ["Thu", "13:30"], name: "Morgan Example", ref: "MRN-DEMO-03", status: "Scheduled" },
];
const USERS = [
  { name: "Clinic Admin", role: "Administrator" },
  { name: "Alex Sample", role: "Doctor", doctor: true },
  { name: "Sara Demo", role: "Receptionist" },
];
const SIDEBAR = [
  { icon: Home, label: "Dashboard" },
  { icon: CalendarDays, label: "Appointments" },
  { icon: Users, label: "Patients" },
  { icon: Stethoscope, label: "Doctors" },
  { icon: Building2, label: "Departments" },
];

// Every shortcut leads somewhere real; protected pages send visitors to sign in first.
const SHORTCUTS = [
  { icon: Search, label: "Find a Doctor", to: "/doctors", tone: "blue" },
  { icon: CalendarDays, label: "Book Appointment", to: "/appointments/book", tone: "green" },
  { icon: FileText, label: "Explain a Report", to: "/profile", tone: "violet" },
  { icon: Building2, label: "Clinic Information", to: "/departments", tone: "amber" },
];

/**
 * The hero's picture of the product: an admin dashboard with the assistant
 * beside it. The dashboard is decorative demo content (hidden from screen
 * readers); the assistant's shortcuts are real links.
 */
export default function HeroPreview() {
  return (
    <div className="lp-preview">
      <div className="lp-dash" aria-hidden="true">
        <span className="lp-demo-tag">Demo data</span>
        <div className="lp-dash-side">
          <div className="lp-dash-brand">
            <BrandMark size={22} /> Clinic AI
          </div>
          {SIDEBAR.map(({ icon: Icon, label }, i) => (
            <div key={label} className={i === 0 ? "lp-dash-nav active" : "lp-dash-nav"}>
              <Icon size={14} /> {label}
            </div>
          ))}
        </div>
        <div className="lp-dash-main">
          <div className="lp-dash-top">
            <span className="lp-dash-search">
              <Search size={12} /> Search patients, doctors…
            </span>
            <Bell size={14} />
            <Avatar name="Clinic Admin" size={24} />
          </div>
          <div className="lp-dash-title">
            <strong>Admin Dashboard</strong>
            <small>Clinic operations overview at a glance.</small>
          </div>
          <div className="lp-dash-stats">
            {DEMO_STATS.map(({ label, value, icon: Icon, tone }) => (
              <div key={label} className="lp-dash-stat">
                <span className={`lp-tile sm tone-${tone}`}>
                  <Icon size={13} />
                </span>
                <small>{label}</small>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <div className="lp-dash-panels">
            <div className="lp-dash-panel">
              <strong>Recent appointments</strong>
              {APPOINTMENTS.map(({ when, name, ref, status }) => (
                <div key={ref} className="lp-dash-row">
                  <span className="lp-dash-when">
                    {when[0]}
                    <br />
                    {when[1]}
                  </span>
                  <Avatar name={name} size={22} />
                  <span className="lp-dash-who">
                    {name}
                    <small>{ref}</small>
                  </span>
                  <span className={`lp-pill ${status === "Confirmed" ? "ok" : "info"}`}>{status}</span>
                </div>
              ))}
            </div>
            <div className="lp-dash-panel lp-hide-sm">
              <strong>Recent users</strong>
              {USERS.map(({ name, role, doctor }) => (
                <div key={name} className="lp-dash-row">
                  <Avatar name={name} size={22} role={doctor ? "doctor" : undefined} />
                  <span className="lp-dash-who">
                    {name}
                    <small>{role}</small>
                  </span>
                  <span className="lp-pill ok">Active</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <section className="lp-chat" aria-labelledby="lp-chat-title">
        <div className="lp-chat-head">
          <img src={aiAvatar} alt="" width={34} height={34} />
          <span>
            <strong id="lp-chat-title">Clinic AI Assistant</strong>
            <small>Your clinic and appointment helper</small>
          </span>
        </div>
        <div className="lp-chat-body">
          <img className="lp-chat-hero" src={aiAvatar} alt="" width={96} height={96} />
          <p className="lp-chat-greeting">
            Hello! How can I help <span>you today?</span>
          </p>
          <div className="lp-chat-shortcuts">
            {SHORTCUTS.map(({ icon: Icon, label, to, tone }) => (
              <Link key={label} to={to} className="lp-chat-shortcut">
                <span className={`lp-tile sm tone-${tone}`}>
                  <Icon size={14} aria-hidden="true" />
                </span>
                {label}
              </Link>
            ))}
          </div>
        </div>
        {/* Visitors cannot chat: every assistant request requires signing in. */}
        <Link to="/login" state={{ from: "/dashboard" }} className="lp-chat-signin">
          <MessageSquareText size={16} aria-hidden="true" />
          <span>Sign in to chat with the assistant</span>
          <LogIn size={16} aria-hidden="true" />
        </Link>
      </section>
    </div>
  );
}
