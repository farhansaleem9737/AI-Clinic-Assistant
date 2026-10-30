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

// My Schedule (D78): the week as a whole, and single dates. Times are local
// wall-clock times in the doctor's department timezone.
export const getWeeklySchedule = (doctorId) => api.get(`/doctors/${doctorId}/weekly-schedule`);
export const saveWeeklySchedule = (doctorId, days) => api.put(`/doctors/${doctorId}/weekly-schedule`, { days });

export const listDateExceptions = (doctorId) => api.get(`/doctors/${doctorId}/date-exceptions`);
export const createDateException = (doctorId, data) => api.post(`/doctors/${doctorId}/date-exceptions`, data);
export const updateDateException = (doctorId, id, data) => api.put(`/doctors/${doctorId}/date-exceptions/${id}`, data);
export const deleteDateException = (doctorId, id) => api.delete(`/doctors/${doctorId}/date-exceptions/${id}`);

// One doctor's day for the staff schedule view (D83): every slot's status
// (never who booked it), breaks, slot length and the week around the date.
export const getDaySchedule = (doctorId, day) => api.get(`/doctors/${doctorId}/day-schedule`, { params: { day } });
