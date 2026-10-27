import api from "./api";
import { fileForm } from "./files";

const base = (patientId) => `/patients/${patientId}/documents/`;

export const listDocuments = (patientId) => api.get(base(patientId));
export const uploadDocument = (patientId, file, fields) =>
  api.post(base(patientId), fileForm(file, fields));
// A link that works for a few minutes, for anyone holding it. Ask for it on
// click and use it immediately; never store it.
export const getDocumentDownload = (patientId, documentId) =>
  api.get(`${base(patientId)}${documentId}/download`);
export const retractDocument = (patientId, documentId, reason) =>
  api.post(`${base(patientId)}${documentId}/retract`, { reason });

export const DOCUMENT_TYPES = [
  { value: "lab_report", label: "Lab report" },
  { value: "imaging", label: "Imaging report" },
  { value: "prescription", label: "Prescription" },
  { value: "referral", label: "Referral" },
  { value: "discharge_summary", label: "Discharge summary" },
  { value: "other", label: "Other" },
];
