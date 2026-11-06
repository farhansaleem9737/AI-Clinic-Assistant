import api from "./api";

// The medical catalog (D118): specializations under departments.

/** Active specializations, with publicly listed doctor counts; of one department when given. */
export const getCatalogSpecializations = (departmentId) =>
  api.get("/public/specializations/", { params: departmentId ? { department_id: departmentId } : {} });

// Administration (department:manage).
export const listSpecializations = (params = {}) => api.get("/specializations/", { params });
export const createSpecialization = (data) => api.post("/specializations/", data);
export const updateSpecialization = (id, data) => api.patch(`/specializations/${id}`, data);

// A doctor's catalog specializations (read: doctor:read, change: doctor:update).
export const getDoctorSpecializations = (doctorId) => api.get(`/doctors/${doctorId}/specializations`);
export const setDoctorSpecializations = (doctorId, ids) =>
  api.put(`/doctors/${doctorId}/specializations`, { specialization_ids: ids });
