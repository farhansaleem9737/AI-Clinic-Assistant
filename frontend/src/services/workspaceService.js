import api from "./api";

// The signed-in workspace (D86): the caller's own notifications, global
// search, and the clinic's settings.
export const listNotifications = (limit = 20) => api.get("/notifications", { params: { limit } });
export const getUnreadCount = () => api.get("/notifications/unread-count");
export const markNotificationRead = (id) => api.post(`/notifications/${id}/read`);
export const markAllNotificationsRead = () => api.post("/notifications/read-all");

export const globalSearch = (q) => api.get("/search", { params: { q } });

export const getClinicSettings = () => api.get("/settings/clinic");
export const updateClinicSettings = (data) => api.put("/settings/clinic", data);
