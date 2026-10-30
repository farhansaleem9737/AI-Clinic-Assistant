import api from "./api";

// Role-aware figures: sections the caller may not see come back as null.
export const getDashboardSummary = () => api.get("/dashboard/summary");

// Administrators: clinic totals as of `day` (default today, clinic time), growth
// since the end of the previous month, and the newest accounts (D85).
export const getAdminDashboard = (day) => api.get("/dashboard/admin", { params: day ? { day } : {} });
