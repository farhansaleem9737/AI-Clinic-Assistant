import api from "./api";

export const listAppointments = (params) =>
  // `status` may be an array: send it as repeated ?status=a&status=b.
  api.get("/appointments/", { params, paramsSerializer: { indexes: null } });
export const getAppointment = (id) => api.get(`/appointments/${id}`);
export const getAppointmentHistory = (id) => api.get(`/appointments/${id}/history`);
export const updateAppointment = (id, data) => api.patch(`/appointments/${id}`, data);
export const changeAppointmentStatus = (id, data) => api.post(`/appointments/${id}/status`, data);
export const rescheduleAppointment = (id, data) => api.post(`/appointments/${id}/reschedule`, data);

// The Idempotency-Key makes a double-clicked or retried "Book" safe: the
// server returns the first booking instead of creating a second one.
export const bookAppointment = (data, idempotencyKey) =>
  api.post("/appointments/", data, { headers: { "Idempotency-Key": idempotencyKey } });
