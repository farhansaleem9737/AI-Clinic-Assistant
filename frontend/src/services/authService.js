import api, { csrfHeaders } from "./api";

// Emails the six-digit code that registration needs (204, or 409 EMAIL_TAKEN / 429 CODE_RECENTLY_SENT).
export const sendVerificationCode = (email) => api.post("/auth/register/verification-code", { email });

// The signed-in user's password (D116). Both read this browser's session cookie, hence the CSRF header.
export const getPasswordStatus = () => api.get("/auth/password", { headers: csrfHeaders() });
export const changePassword = (data) => api.post("/auth/password", data, { headers: csrfHeaders() });

// Forgot password (D126). Public; the answer to a request is the same whether or not the account exists.
export const requestPasswordReset = (email) => api.post("/auth/forgot-password", { email });
// POST, so the emailed token never appears in a URL the server or a proxy logs.
export const checkResetToken = (token) => api.post("/auth/reset-password/check", { token });
export const resetPassword = (token, newPassword) => api.post("/auth/reset-password", { token, new_password: newPassword });
