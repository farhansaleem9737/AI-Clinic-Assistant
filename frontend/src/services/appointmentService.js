import api from "./api";

export const listAppointments = (params) =>
  // `status` may be an array: send it as repeated ?status=a&status=b.
  api.get("/appointments/", { params, paramsSerializer: { indexes: null } });
// Upcoming / past / all totals under the same filters as the list.
export const countAppointments = (params) => api.get("/appointments/counts", { params, paramsSerializer: { indexes: null } });
// The doctor's calendar view (D79): on `day`, after today, before today.
export const countAppointmentsByDay = (params) =>
  api.get("/appointments/day-counts", { params, paramsSerializer: { indexes: null } });
export const getAppointment = (id) => api.get(`/appointments/${id}`);
export const getAppointmentHistory = (id) => api.get(`/appointments/${id}/history`);
export const updateAppointment = (id, data) => api.patch(`/appointments/${id}`, data);
export const changeAppointmentStatus = (id, data) => api.post(`/appointments/${id}/status`, data);
export const rescheduleAppointment = (id, data) => api.post(`/appointments/${id}/reschedule`, data);

// The Idempotency-Key makes a double-clicked or retried "Book" safe: the
// server returns the first booking instead of creating a second one.
export const bookAppointment = (data, idempotencyKey) =>
  api.post("/appointments/", data, { headers: { "Idempotency-Key": idempotencyKey } });
// Automatic token booking (D120): the earliest free time with a doctor on a date and
// its estimated place in the day. Reserves nothing; book it with booking_mode "auto".
export const getNextAvailable = (doctorId, date, patientId, config = {}) =>
  api.get("/appointments/next-available", {
    ...config,
    params: { doctor_id: doctorId, date, ...(patientId ? { patient_id: patientId } : {}) },
  });
// A follow-up visit recorded as due by a date (D108): read by anyone who sees the
// appointment, recorded by its doctor or the clinic, dismissed by them or the patient.
export const getFollowUp = (appointmentId) => api.get(`/appointments/${appointmentId}/follow-up`);
export const saveFollowUp = (appointmentId, dueDate) => api.put(`/appointments/${appointmentId}/follow-up`, { due_date: dueDate });
export const dismissFollowUp = (followUpId) => api.post(`/follow-ups/${followUpId}/dismiss`);
