import api from "./api";

// Allergies, diagnoses and medications in a patient's record (D112). The API
// decides who may add, edit or remove what; responses say so (`can_add_*`,
// each entry's `can_edit`).
const base = (patientId) => `/patients/${patientId}/health-records`;

export const getHealthRecords = (patientId) => api.get(base(patientId));
export const addHealthRecord = (patientId, kind, entry) => api.post(`${base(patientId)}/${kind}`, entry);
export const updateHealthRecord = (patientId, kind, id, entry) => api.put(`${base(patientId)}/${kind}/${id}`, entry);
export const removeHealthRecord = (patientId, kind, id) => api.delete(`${base(patientId)}/${kind}/${id}`);
