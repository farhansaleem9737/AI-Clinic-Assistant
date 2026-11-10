// Continue with Google (D123). The browser goes to the backend, which talks to
// Google; no Google script is loaded and no Google token reaches this app.
import api, { csrfHeaders } from "./api";

export const getSignInProviders = () => api.get("/auth/providers");

/** Where "Continue with Google" sends the browser (a full-page navigation). */
export const googleStartUrl = (intent = "login", remember = false) =>
  api.getUri({ url: "/auth/google/start", params: { intent, remember } });

// After Google: a known user's session (cookies are set by this same-site request).
export const completeGoogleSignIn = () => api.post("/auth/google/complete");
// A new person: what Google shared, then the registration form.
export const getGoogleSignup = () => api.get("/auth/google/signup");
export const googleSignup = (data) => api.post("/auth/google/signup", data);

// Account › Connected accounts. They read this browser's session cookie, hence CSRF.
export const getGoogleIdentity = () => api.get("/auth/google/identity");
export const linkGoogle = (currentPassword) =>
  api.post("/auth/google/link", { current_password: currentPassword || null }, { headers: csrfHeaders() });
export const unlinkGoogle = (currentPassword) =>
  api.post("/auth/google/unlink", { current_password: currentPassword || null }, { headers: csrfHeaders() });

/** The message for the `?google=` reason the backend redirects with. */
export const GOOGLE_MESSAGES = {
  cancelled: { kind: "info", text: "Google sign-in was cancelled. You can try again or use your email and password." },
  expired: { kind: "warn", text: "That Google sign-in took too long or was already used. Please try again." },
  failed: { kind: "error", text: "We couldn't sign you in with Google. Please try again." },
  unavailable: { kind: "warn", text: "Google sign-in isn't available right now. Please use your email and password." },
  unverified: { kind: "error", text: "Your Google account's email address isn't verified with Google, so it can't be used here." },
  inactive: { kind: "error", text: "This account can't sign in. Please contact the clinic." },
  link_required: {
    kind: "info",
    text: "An account with this email address already exists. Sign in with your password, then link Google from Account › Connected accounts.",
  },
  in_use: { kind: "error", text: "That Google account is already linked to another account." },
  already_linked: { kind: "error", text: "A different Google account is already linked. Unlink it first." },
  linked: { kind: "success", text: "Your Google account is now linked. You can use it to sign in." },
};
