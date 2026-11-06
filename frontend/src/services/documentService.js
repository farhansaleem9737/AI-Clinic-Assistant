import api from "./api";
import { fileForm } from "./files";

const base = (patientId) => `/patients/${patientId}/documents/`;

export const listDocuments = (patientId) => api.get(base(patientId));
// `onProgress(percent)` (optional) follows the upload.
export const uploadDocument = (patientId, file, fields, onProgress) =>
  api.post(base(patientId), fileForm(file, fields), {
    onUploadProgress: onProgress ? (e) => e.total && onProgress(Math.round((e.loaded / e.total) * 100)) : undefined,
  });
// A link that works for a few minutes, for anyone holding it. Ask for it on
// click and use it immediately; never store it. `inline`: the same link for
// showing the file (a preview) rather than saving it.
export const getDocumentDownload = (patientId, documentId, { inline = false } = {}) =>
  inline
    ? api.get(`${base(patientId)}${documentId}/download`, { params: { inline: true } })
    : api.get(`${base(patientId)}${documentId}/download`);
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
