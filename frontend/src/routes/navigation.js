// Header menu. `permission` / `anyOf` only decide what is shown — the backend
// enforces access on every request.
export const NAV_ITEMS = [
  { to: "/doctors", label: "Doctors", public: true },
  { to: "/dashboard", label: "Dashboard" },
  { to: "/profile", label: "My profile", permission: "patient:read_own" },
  { to: "/doctor/profile", label: "My profile", permission: "doctor:update_own" },
  { to: "/patients", label: "Patients", permission: "patient:read_any" },
  { to: "/admin/doctors", label: "Manage doctors", permission: "doctor:read" },
  { to: "/admin/departments", label: "Departments", permission: "department:manage" },
  { to: "/admin/users", label: "Users", permission: "user:read" },
];
