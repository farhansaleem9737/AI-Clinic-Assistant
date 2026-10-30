import api from "./api";

export const listUsers = (params) => api.get("/users/", { params });
export const createUser = (data) => api.post("/users/", data);
export const updateUser = (id, data) => api.patch(`/users/${id}`, data);
export const deactivateUser = (id) => api.post(`/users/${id}/deactivate`);
export const activateUser = (id) => api.post(`/users/${id}/activate`);
export const setUserRoles = (id, roles) => api.put(`/users/${id}/roles`, { roles });
export const listRoles = () => api.get("/roles/");
export const getUser = (id) => api.get(`/users/${id}`);
export const bulkSetUserStatus = (userIds, isActive) =>
  api.post("/users/bulk-status", { user_ids: userIds, is_active: isActive });
