import api from "./api";

// Public directory (no login).
export const getPublicDoctors = (params) => api.get("/public/doctors/", { params });
export const getPublicDoctor = (id) => api.get(`/public/doctors/${id}`);

// Staff (doctor:read / doctor:create / doctor:update / doctor:deactivate).
export const listDoctors = (params) => api.get("/doctors/", { params });
export const getDoctor = (id) => api.get(`/doctors/${id}`);
export const createDoctor = (data) => api.post("/doctors/", data);
export const updateDoctor = (id, data) => api.patch(`/doctors/${id}`, data);
export const deactivateDoctor = (id) => api.post(`/doctors/${id}/deactivate`);
export const activateDoctor = (id) => api.post(`/doctors/${id}/activate`);

// The logged-in doctor's own profile (doctor:update_own).
export const getMyDoctorProfile = () => api.get("/doctors/me");
export const updateMyDoctorProfile = (data) => api.patch("/doctors/me", data);
