import {
  Building2,
  CalendarClock,
  CalendarDays,
  CalendarPlus,
  LayoutDashboard,
  Settings2,
  ShieldCheck,
  Stethoscope,
  UserCog,
  UserRound,
  Users,
} from "lucide-react";

const APPOINTMENT_READ = ["appointment:read_own", "appointment:read_assigned", "appointment:read_any"];

// Sidebar menu. `permission` / `anyOf` only decide what is shown — the backend
// enforces access on every request. `public` items are shown to everyone.
export const NAV_ITEMS = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/appointments", label: "Appointments", icon: CalendarDays, anyOf: APPOINTMENT_READ, end: true },
  { to: "/appointments/book", label: "Book appointment", icon: CalendarPlus, anyOf: ["appointment:create", "appointment:create_own"] },
  { to: "/schedule", label: "Schedule", icon: CalendarClock, anyOf: ["schedule:manage_own", "schedule:manage_any"] },
  { to: "/doctors", label: "Doctors", icon: Stethoscope, public: true },
  { to: "/departments", label: "Departments", icon: Building2, public: true },
  { to: "/patients", label: "Patients", icon: Users, permission: "patient:read_any" },
  { to: "/profile", label: "My Profile", icon: UserRound, permission: "patient:read_own" },
  // Only for logins that actually have a doctor profile.
  { to: "/doctor/profile", label: "My Profile", icon: UserRound, permission: "doctor:update_own", when: (user) => Boolean(user.doctor_id) },
  { to: "/admin/doctors", label: "Manage doctors", icon: UserCog, permission: "doctor:read" },
  { to: "/admin/departments", label: "Manage departments", icon: Settings2, permission: "department:manage" },
  { to: "/admin/users", label: "Users", icon: ShieldCheck, permission: "user:read" },
];

export function visibleNavItems(user, can) {
  return NAV_ITEMS.filter((item) => {
    if (item.public) return true;
    if (!user) return false;
    if (item.when && !item.when(user)) return false;
    if (item.permission) return can(item.permission);
    if (item.anyOf) return item.anyOf.some(can);
    return true;
  });
}

// Every role lands on the same dashboard route; the page itself shows each
// role its own view from what the API returns.
export const HOME_PATH = "/dashboard";

// A path to return to after signing in, only if it is inside this app.
// Rejects absolute and protocol-relative URLs ("https://…", "//evil.example").
export function safeReturnPath(path) {
  if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) return null;
  if (path.startsWith("/login")) return null;
  return path;
}

// Where "my profile" lives for this user, if anywhere.
export function profilePath(user, can) {
  if (can("patient:read_own")) return "/profile";
  if (can("doctor:update_own") && user.doctor_id) return "/doctor/profile";
  return null;
}
