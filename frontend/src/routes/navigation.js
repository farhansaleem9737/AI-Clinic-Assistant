import {
  Building2,
  CalendarClock,
  CalendarDays,
  CalendarPlus,
  ClipboardCheck,
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
  // Staff book on a patient's behalf; patients start from a doctor (directory, profile, dashboard).
  { to: "/appointments/book", label: "Book appointment", icon: CalendarPlus, permission: "appointment:create" },
  // Front desk (books for patients, no schedule of its own) reaches hours
  // management from Doctors / Schedules instead (D83).
  {
    to: "/schedule",
    label: "Schedule",
    icon: CalendarClock,
    anyOf: ["schedule:manage_own", "schedule:manage_any"],
    when: (user, can) => can("schedule:manage_own") || !can("appointment:create"),
  },
  { to: "/doctor-schedules", label: "Doctors / Schedules", icon: Stethoscope, permission: "appointment:create" },
  { to: "/doctors", label: "Doctors", icon: Stethoscope, public: true, when: (user, can) => !user || !can("appointment:create") },
  { to: "/departments", label: "Departments", icon: Building2, public: true },
  { to: "/patients", label: "Patients", icon: Users, permission: "patient:read_any" },
  { to: "/profile", label: "My Profile", icon: UserRound, permission: "patient:read_own" },
  // Only for logins that actually have a doctor profile.
  { to: "/doctor/profile", label: "My Profile", icon: UserRound, permission: "doctor:update_own", when: (user) => Boolean(user.doctor_id) },
  // Self-registered doctors until an administrator verifies them (D77).
  { to: "/doctor/application", label: "My Application", icon: ClipboardCheck, permission: "doctor_application:manage_own" },
  { to: "/admin/doctors", label: "Manage doctors", icon: UserCog, permission: "doctor:read" },
  { to: "/admin/departments", label: "Manage departments", icon: Settings2, permission: "department:manage" },
  { to: "/admin/users", label: "Users", icon: ShieldCheck, permission: "user:read" },
];

// What makes someone an administrator here: the permissions behind the admin
// dashboard (users, every patient, every appointment). Roles are data; this
// asks what the account may do, not what its role is called.
export const ADMIN_PERMISSIONS = ["user:read", "patient:read_any", "appointment:read_any"];
export const isAdmin = (can) => ADMIN_PERMISSIONS.every((p) => can(p));

// The administrator's sidebar (D86), each item still behind its permission.
export const ADMIN_NAV = [
  { to: "/admin", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/admin/users", label: "Users", icon: ShieldCheck, permission: "user:read" },
  { to: "/admin/departments", label: "Departments", icon: Building2, permission: "department:manage" },
  { to: "/admin/doctors", label: "Doctors", icon: Stethoscope, permission: "doctor:read" },
  { to: "/patients", label: "Patients", icon: Users, permission: "patient:read_any", end: true },
  { to: "/appointments", label: "Appointments", icon: CalendarDays, anyOf: APPOINTMENT_READ, end: true },
  { to: "/account", label: "Profile", icon: UserRound },
];

export function visibleNavItems(user, can) {
  if (user && isAdmin(can)) return ADMIN_NAV.filter((item) => (item.permission ? can(item.permission) : item.anyOf ? item.anyOf.some(can) : true));
  return NAV_ITEMS.filter((item) => {
    if (item.public) return !item.when || item.when(user, can);
    if (!user) return false;
    if (item.when && !item.when(user, can)) return false;
    if (item.permission) return can(item.permission);
    if (item.anyOf) return item.anyOf.some(can);
    return true;
  });
}

// Every role lands on the same dashboard route; the page itself shows each
// role its own view from what the API returns (administrators are sent on
// to /admin).
export const HOME_PATH = "/dashboard";

// A path to return to after signing in, only if it is inside this app.
// Rejects absolute and protocol-relative URLs ("https://…", "//evil.example").
export function safeReturnPath(path) {
  if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) return null;
  if (path.startsWith("/login")) return null;
  return path;
}

const ROLE_LABELS = {
  patient: "Patient",
  doctor: "Doctor",
  doctor_applicant: "Doctor (pending verification)",
  receptionist: "Receptionist",
  admin: "Administrator",
};

// "Patient", "Doctor, Administrator", ... for the signed-in user's roles.
export function roleLabel(roles = []) {
  if (roles.length === 0) return "No role";
  return roles.map((r) => ROLE_LABELS[r] ?? r.charAt(0).toUpperCase() + r.slice(1).replace(/_/g, " ")).join(", ");
}

// Where "my profile" lives for this user.
export function profilePath(user, can) {
  if (can("patient:read_own")) return "/profile";
  if (can("doctor:update_own") && user.doctor_id) return "/doctor/profile";
  if (can("doctor_application:manage_own")) return "/doctor/application";
  // Everyone else (administrators, front desk): the account page.
  return "/account";
}
