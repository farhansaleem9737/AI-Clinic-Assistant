import api, { csrfHeaders } from "./api";

// Emails the six-digit code that registration needs (204, or 409 EMAIL_TAKEN / 429 CODE_RECENTLY_SENT).
export const sendVerificationCode = (email) => api.post("/auth/register/verification-code", { email });

// The signed-in user's password (D116). Both read this browser's session cookie, hence the CSRF header.
export const getPasswordStatus = () => api.get("/auth/password", { headers: csrfHeaders() });
export const changePassword = (data) => api.post("/auth/password", data, { headers: csrfHeaders() });
