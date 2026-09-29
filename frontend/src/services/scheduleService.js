import api from "./api";

export const getAvailability = (doctorId, dateFrom, dateTo) =>
  api.get(`/doctors/${doctorId}/availability`, { params: { date_from: dateFrom, date_to: dateTo } });

export const listTemplates = (doctorId, includeInactive = false) =>
  api.get("/schedules", { params: { doctor_id: doctorId, include_inactive: includeInactive } });
export const createTemplate = (data) => api.post("/schedules", data);
export const deactivateTemplate = (id) => api.post(`/schedules/${id}/deactivate`);

export const listExceptions = (doctorId, start, end) =>
  api.get("/schedule-exceptions", { params: { doctor_id: doctorId, start, end } });
export const createException = (data) => api.post("/schedule-exceptions", data);
export const deleteException = (id) => api.delete(`/schedule-exceptions/${id}`);
