import api from "./api";

// The signed-in workspace (D86): the caller's own notifications, global
// search, and the clinic's settings.
// Newest first; `offset` pages further back (the answer says whether more exist).
export const listNotifications = (limit = 20, offset = 0) => api.get("/notifications", { params: { limit, offset } });
export const getUnreadCount = () => api.get("/notifications/unread-count");
export const markNotificationRead = (id) => api.post(`/notifications/${id}/read`);
export const markAllNotificationsRead = () => api.post("/notifications/read-all");
// Optional categories the caller may switch off (D108).
export const getNotificationPreferences = () => api.get("/notifications/preferences");
export const updateNotificationPreferences = (changes) => api.put("/notifications/preferences", changes);

export const globalSearch = (q) => api.get("/search", { params: { q } });

export const getClinicSettings = () => api.get("/settings/clinic");
export const updateClinicSettings = (data) => api.put("/settings/clinic", data);
