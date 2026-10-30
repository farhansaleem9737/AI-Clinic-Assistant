import api from "./api";

// Public (no login): active departments only.
export const getPublicDepartments = (params = {}) =>
  api.get("/public/departments/", { params: { page_size: 100, ...params } });

// Management (department:manage).
export const listDepartments = (params) => api.get("/departments/", { params });
export const createDepartment = (data) => api.post("/departments/", data);
export const updateDepartment = (id, data) => api.patch(`/departments/${id}`, data);
export const deactivateDepartment = (id) => api.post(`/departments/${id}/deactivate`);
export const activateDepartment = (id) => api.post(`/departments/${id}/activate`);
export const getDepartment = (id) => api.get(`/departments/${id}`);
// Clinic-wide totals for Admin > Departments (D93).
export const getDepartmentSummary = () => api.get("/departments/summary");
