import api from "./api";

// Role-aware figures: sections the caller may not see come back as null.
export const getDashboardSummary = () => api.get("/dashboard/summary");
