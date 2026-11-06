import api from "./api";

// Hybrid scheduling (D117): a doctor's scheduling policy and the day's queue.
// The server decides every rule; these only send requests.
export const getSchedulingPolicy = (doctorId) => api.get(`/doctors/${doctorId}/scheduling-policy`);
export const saveSchedulingPolicy = (doctorId, data) => api.put(`/doctors/${doctorId}/scheduling-policy`, data);
// The times a date would offer with a proposed length, and the bookings that would not fit (D120). Saves nothing.
export const previewSchedulingPolicy = (doctorId, data, config = {}) =>
  api.post(`/doctors/${doctorId}/scheduling-policy/preview`, data, config);

export const getQueueSessions = (date) => api.get("/queue/sessions", { params: date ? { date } : {} });
export const getQueueBoard = (doctorId, date) => api.get(`/queue/doctors/${doctorId}`, { params: date ? { date } : {} });
export const callNextPatient = (doctorId) => api.post(`/queue/doctors/${doctorId}/call-next`);
export const getMyQueue = () => api.get("/queue/me");
export const registerWalkIn = (data) => api.post("/queue/walk-ins", data);

// check-in | call | start | complete | defer | prioritize | absent | no-show | cancel
export const queueAction = (entryId, action, body) => api.post(`/queue/entries/${entryId}/${action}`, body);
