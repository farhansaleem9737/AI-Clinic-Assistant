import { ADMIN_PERMISSIONS } from "./navigation";

// Every page that loads on demand (code splitting), by name. App.jsx renders
// them through lazyPage(); pointing at a link to one starts the same import
// early (AppLayout). The browser loads each module once, whichever asks first.
// The dashboard, the home page of most roles, is in the main bundle (D107).
export const PAGES = {
  AcceptAdminInvite: () => import("../pages/AcceptAdminInvite"),
  AccountProfile: () => import("../pages/AccountProfile"),
  AdminDashboard: () => import("../components/dashboard/AdminDashboard"),
  AdminDepartments: () => import("../pages/AdminDepartments"),
  AdminDoctors: () => import("../pages/AdminDoctors"),
  AdminSettings: () => import("../pages/AdminSettings"),
  AdminUsers: () => import("../pages/AdminUsers"),
  AppointmentDetail: () => import("../pages/AppointmentDetail"),
  Appointments: () => import("../pages/Appointments"),
  BookAppointment: () => import("../pages/BookAppointment"),
  Departments: () => import("../pages/Departments"),
  DoctorApplication: () => import("../pages/DoctorApplication"),
  DoctorDetail: () => import("../pages/DoctorDetail"),
  DoctorSchedule: () => import("../pages/DoctorSchedule"),
  DoctorSchedules: () => import("../pages/DoctorSchedules"),
  ForgotPassword: () => import("../pages/ForgotPassword"),
  Help: () => import("../pages/Help"),
  Landing: () => import("../pages/Landing"),
  LegalDocument: () => import("../pages/LegalDocument"),
  MyDoctorProfile: () => import("../pages/MyDoctorProfile"),
  MedicalInformation: () => import("../pages/MedicalInformation"),
  MyPatientProfile: () => import("../pages/MyPatientProfile"),
  NotFound: () => import("../pages/NotFound"),
  PatientDetail: () => import("../pages/PatientDetail"),
  Patients: () => import("../pages/Patients"),
  Register: () => import("../pages/Register"),
  ResetPassword: () => import("../pages/ResetPassword"),
  // Continue with Google (D123): finishing a sign-in, and a new person's registration.
  GoogleComplete: () => import("../pages/GoogleComplete"),
  GoogleSignup: () => import("../pages/GoogleSignup"),
  GoogleLink: () => import("../pages/GoogleLink"),
};

// `permission` on a route only hides pages the user cannot use; the API
// enforces the same permission on every request.
const APPOINTMENT_READ = ["appointment:read_own", "appointment:read_assigned", "appointment:read_any"];

export const PROTECTED_ROUTES = [
  { path: "/dashboard", page: "Dashboard" },
  { path: "/help", page: "Help" },
  { path: "/appointments", page: "Appointments", anyOf: APPOINTMENT_READ },
  { path: "/appointments/book", page: "BookAppointment", anyOf: ["appointment:create", "appointment:create_own"] },
  { path: "/appointments/:id", page: "AppointmentDetail", anyOf: APPOINTMENT_READ },
  { path: "/schedule", page: "DoctorSchedule", anyOf: ["schedule:manage_own", "schedule:manage_any"] },
  { path: "/doctor-schedules", page: "DoctorSchedules", permission: "schedule:read" },
  { path: "/doctor/profile", page: "MyDoctorProfile", permission: "doctor:update_own" },
  { path: "/doctor/application", page: "DoctorApplication", permission: "doctor_application:manage_own" },
  { path: "/profile", page: "MyPatientProfile", permission: "patient:read_own" },
  { path: "/profile/contact", page: "MyPatientProfile", permission: "patient:read_own" },
  // The patient's own documents and clinical information (D110).
  { path: "/profile/medical-information", page: "MedicalInformation", permission: "patient:read_own" },
  { path: "/patients", page: "Patients", permission: "patient:read_any" },
  { path: "/patients/:id", page: "PatientDetail", anyOf: ["patient:read_any", "patient:read_assigned"] },
  // The administrator's dashboard (D85/D86); the backend checks the same permissions.
  { path: "/admin", page: "AdminDashboard", allOf: ADMIN_PERMISSIONS },
  { path: "/admin/settings", page: "AdminSettings", permission: "settings:manage" },
  { path: "/account", page: "AccountProfile" },
  { path: "/admin/users", page: "AdminUsers", permission: "user:read" },
  { path: "/admin/departments", page: "AdminDepartments", permission: "department:manage" },
  { path: "/admin/doctors", page: "AdminDoctors", permission: "doctor:read" },
];

// Lazily loaded pages anyone may open (the rest of the public pages are in the main bundle).
const PUBLIC_ROUTES = [
  { path: "/departments", page: "Departments" },
  { path: "/doctors/:id", page: "DoctorDetail" },
  { path: "/register", page: "Register" },
];

export function canOpen(route, can) {
  const { permission, anyOf, allOf } = route;
  return permission ? can(permission) : anyOf ? anyOf.some(can) : allOf ? allOf.every(can) : true;
}

const matches = (pattern, pathname) => {
  const a = pattern.split("/");
  const b = pathname.replace(/\/+$/, "").split("/");
  return a.length === b.length && a.every((part, i) => part.startsWith(":") ? b[i] !== "" : part === b[i]);
};

// The page loader behind an in-app path, if this user may open it (static paths win over ":id").
export function pageLoaderFor(pathname, can) {
  const candidates = [...PROTECTED_ROUTES, ...PUBLIC_ROUTES].filter((r) => matches(r.path, pathname));
  const route = candidates.find((r) => !r.path.includes(":")) ?? candidates[0];
  return route && canOpen(route, can) ? (PAGES[route.page] ?? null) : null;
}

