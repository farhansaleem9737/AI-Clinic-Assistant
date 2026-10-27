import api from "./api";
import { fileForm } from "./files";

// Own profile (patient:read_own / patient:update_own).
export const getMyPatientProfile = () => api.get("/patients/me");
export const completeMyPatientProfile = (data) =>
  api.post("/patients/me", data);
export const updateMyContactDetails = (data) => api.patch("/patients/me", data);

// Staff.
export const listPatients = (params) => api.get("/patients/", { params });
export const getPatient = (id) => api.get(`/patients/${id}`);
export const registerPatient = (data) => api.post("/patients/", data);
export const updatePatient = (id, data) => api.patch(`/patients/${id}`, data);
export const deactivatePatient = (id) => api.post(`/patients/${id}/deactivate`);
export const activatePatient = (id) => api.post(`/patients/${id}/activate`);
export const createPatientAccount = (id, data) =>
  api.post(`/patients/${id}/account`, data);

// Profile photo (patient:update_own for /me, patient:update for staff).
export const uploadMyPatientPhoto = (file) =>
  api.put("/patients/me/photo", fileForm(file));
export const removeMyPatientPhoto = () => api.delete("/patients/me/photo");
export const uploadPatientPhoto = (id, file) =>
  api.put(`/patients/${id}/photo`, fileForm(file));
export const removePatientPhoto = (id) => api.delete(`/patients/${id}/photo`);
