import api from "./api";

export const getDoctors = () => api.get("/doctors/");
export const getDoctor = (id) => api.get(`/doctors/${id}`);
export const createDoctor = (data) => api.post("/doctors/", data);
export const updateDoctor = (id, data) => api.put(`/doctors/${id}`, data);
export const deleteDoctor = (id) => api.delete(`/doctors/${id}`);