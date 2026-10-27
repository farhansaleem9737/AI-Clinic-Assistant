import api from "./api";
import { fileForm } from "./files";

// The signed-in doctor applicant's own application (doctor_application:manage_own).
export const getMyApplication = () => api.get("/doctor-applications/me");
export const updateMyApplication = (data) => api.patch("/doctor-applications/me", data);

// `onProgress(percent)` is called while the file is sent.
export const uploadApplicationDocument = (file, documentType, onProgress) =>
  api.post("/doctor-applications/me/documents", fileForm(file, { document_type: documentType }), {
    onUploadProgress: onProgress
      ? (event) => event.total && onProgress(Math.round((event.loaded / event.total) * 100))
      : undefined,
  });
export const removeApplicationDocument = (documentId) =>
  api.delete(`/doctor-applications/me/documents/${documentId}`);

export const CREDENTIAL_TYPES = [
  { value: "registration_certificate", label: "Medical Registration Certificate" },
  { value: "degree_certificate", label: "Medical Degree / Qualification Certificate" },
  { value: "supporting_document", label: "Additional Supporting Document" },
];

// Names the API uses in `missing_for_approval`, as people read them.
export const REQUIREMENT_LABELS = {
  specialization: "Specialization",
  department_id: "Department",
  license_number: "Medical license number",
  registration_authority: "Registration authority",
  years_of_experience: "Years of experience",
  qualifications: "Qualification / degree",
  institution: "Institution / university",
  bio: "Professional biography",
  consultation_fee: "Consultation fee",
  languages: "Languages spoken",
  phone: "Phone number",
  ...Object.fromEntries(CREDENTIAL_TYPES.map((t) => [t.value, t.label])),
};

export const APPLICATION_STATUS = {
  pending_review: { label: "Pending review", tone: "warn" },
  approved: { label: "Approved", tone: "ok" },
  rejected: { label: "Not approved", tone: "danger" },
};
