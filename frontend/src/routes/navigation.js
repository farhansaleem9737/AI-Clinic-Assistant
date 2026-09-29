// Header menu. `permission` / `anyOf` only decide what is shown — the backend
// enforces access on every request.
export const NAV_ITEMS = [
  { to: "/doctors", label: "Doctors", public: true },
  { to: "/dashboard", label: "Dashboard" },
  { to: "/admin/users", label: "Users", permission: "user:read" },
  { to: "/admin/departments", label: "Departments", permission: "department:manage" },
  { to: "/admin/doctors", label: "Manage doctors", permission: "doctor:create" },
];
