import api from "./api";
import { fileForm } from "./files";

// Public directory (no login).
export const getPublicDoctors = (params) =>
  api.get("/public/doctors/", { params });
export const getPublicDoctor = (id) => api.get(`/public/doctors/${id}`);
// Distinct specializations of the listed doctors: options for the filter,
// optionally only those in one department.
export const getPublicSpecializations = (departmentId) =>
  api.get("/public/doctors/specializations", {
    params: departmentId ? { department_id: departmentId } : {},
  });
// Free appointment times for the profile's booking calendar, grouped by the
// clinic's local date. Seeing a time reserves nothing; booking re-checks it.
export const getPublicAvailability = (id, dateFrom, dateTo) =>
  api.get(`/public/doctors/${id}/availability`, {
    params: { date_from: dateFrom, date_to: dateTo },
  });

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

// Career history shown on the public profile. PUT replaces the whole list.
export const getMyCareer = () => api.get("/doctors/me/career");
export const updateMyCareer = (data) => api.put("/doctors/me/career", data);
export const getDoctorCareer = (id) => api.get(`/doctors/${id}/career`);
export const updateDoctorCareer = (id, data) => api.put(`/doctors/${id}/career`, data);

// Profile photo (doctor:update_own for /me, doctor:update for any doctor).
export const uploadMyDoctorPhoto = (file) =>
  api.put("/doctors/me/photo", fileForm(file));
export const removeMyDoctorPhoto = () => api.delete("/doctors/me/photo");
export const uploadDoctorPhoto = (id, file) =>
  api.put(`/doctors/${id}/photo`, fileForm(file));
export const removeDoctorPhoto = (id) => api.delete(`/doctors/${id}/photo`);
// Every specialization in use, inactive doctors included (staff filter options).
export const listAllSpecializations = () => api.get("/doctors/specializations");
