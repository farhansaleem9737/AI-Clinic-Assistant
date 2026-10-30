import api from "./api";

// Administrator invitations and the admin role (D87). Invitation tokens only
// ever travel in request bodies, never in URLs.
export const listInvitations = (includeClosed = false) =>
  api.get("/admin/invitations", { params: includeClosed ? { include_closed: true } : {} });
export const createInvitation = (data) => api.post("/admin/invitations", data);
export const resendInvitation = (id) => api.post(`/admin/invitations/${id}/resend`);
export const revokeInvitation = (id) => api.post(`/admin/invitations/${id}/revoke`);
export const revokeAdminRole = (userId, currentPassword) =>
  api.post(`/admin/administrators/${userId}/revoke-role`, { current_password: currentPassword });

export const previewInvitation = (token) => api.post("/auth/admin-invitations/preview", { token });
export const acceptInvitation = (data) => api.post("/auth/admin-invitations/accept", data);
export const acceptInvitationAsSignedIn = (token, currentPassword) =>
  api.post("/auth/admin-invitations/accept-existing", { token, current_password: currentPassword });
