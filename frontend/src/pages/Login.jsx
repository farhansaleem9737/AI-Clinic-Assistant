import { Mail } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import Alert from "../components/Alert";
import PasswordInput from "../components/PasswordInput";
import { useAuth } from "../context/useAuth";
import { HOME_PATH, safeReturnPath } from "../routes/navigation";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Client-side checks are for convenience only; the backend decides.
function validate({ email, password }) {
  const errors = {};
  if (!EMAIL_PATTERN.test(email.trim())) errors.email = "Enter a valid email address.";
  if (!password) errors.password = "Password is required.";
  return errors;
}

/**
 * What to tell the user. Deliberately generic for anything credential-related
 * (an unknown email and a wrong password read the same), and a connection
 * problem is never presented as wrong credentials.
 */
function signInError(err) {
  if (!err.response) return "We couldn't reach the server. Check your connection and try again.";
  const { status, data } = err.response;
  if (data?.error?.code === "ACCOUNT_INACTIVE") return "This account has been deactivated. Please contact the clinic.";
  if (status === 401 || status === 422) return "Invalid email or password.";
  if (status >= 500) return "Something went wrong on our side. Please try again in a moment.";
  return "Sign-in failed. Please try again.";
}

function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.7 1.2 9.2 3.6l6.9-6.9C35.9 2.4 30.4 0 24 0 14.6 0 6.5 5.4 2.6 13.2l8 6.2C12.5 13.6 17.8 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.7 6c4.5-4.2 6.9-10.3 6.9-17.7z" />
      <path fill="#FBBC05" d="M10.6 28.6A14.5 14.5 0 0 1 9.8 24c0-1.6.3-3.1.8-4.6l-8-6.2A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.8l8-6.2z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.7-6c-2.1 1.4-4.9 2.3-8.2 2.3-6.2 0-11.5-4.1-13.4-9.9l-8 6.2C6.5 42.6 14.6 48 24 48z" />
    </svg>
  );
}

function MicrosoftLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 21 21" aria-hidden="true">
      <rect x="0" y="0" width="10" height="10" fill="#F25022" />
      <rect x="11" y="0" width="10" height="10" fill="#7FBA00" />
      <rect x="0" y="11" width="10" height="10" fill="#00A4EF" />
      <rect x="11" y="11" width="10" height="10" fill="#FFB900" />
    </svg>
  );
}

export default function Login() {
  const { user, initializing, login } = useAuth();
  const location = useLocation();
  const [form, setForm] = useState({ email: "", password: "", rememberMe: true });
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // A session may be restoring: don't flash the form at a signed-in user.
  if (initializing) return <p className="muted" role="status">Checking your session…</p>;

  // Signed in (already, or just now): go back to the page that asked for the
  // login, or to the dashboard — which shows each role its own view. Only
  // in-app paths are accepted, so this cannot be used as an open redirect.
  if (user) return <Navigate to={safeReturnPath(location.state?.from) ?? HOME_PATH} replace />;

  const set = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    const found = validate(form);
    setErrors(found);
    setFormError("");
    if (Object.keys(found).length > 0) return;

    setSubmitting(true);
    try {
      // Sets the user in the auth context, which triggers the redirect above.
      await login(form.email.trim(), form.password, form.rememberMe);
    } catch (err) {
      setFormError(signInError(err));
      setSubmitting(false);
    }
  };

  return (
    <>
      <h2 className="auth-title">Welcome back</h2>
      <p className="auth-subtitle">Sign in to manage your healthcare experience.</p>

      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <div role="alert">{formError && <Alert>{formError}</Alert>}</div>

        <div className="field">
          <label htmlFor="login-email">Email address</label>
          <div className={`input-icon${errors.email ? " invalid" : ""}`}>
            <Mail size={18} aria-hidden="true" />
            <input
              id="login-email"
              name="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              placeholder="Enter your email address"
              value={form.email}
              onChange={(e) => set("email", e.target.value)}
              aria-invalid={errors.email ? true : undefined}
              aria-describedby={errors.email ? "login-email-error" : undefined}
            />
          </div>
          {errors.email && (
            <p id="login-email-error" className="field-error">
              {errors.email}
            </p>
          )}
        </div>

        <div className="field">
          <label htmlFor="login-password">Password</label>
          <PasswordInput
            id="login-password"
            name="password"
            autoComplete="current-password"
            placeholder="Enter your password"
            value={form.password}
            onChange={(e) => set("password", e.target.value)}
            invalid={Boolean(errors.password)}
            describedBy={errors.password ? "login-password-error" : undefined}
          />
          {errors.password && (
            <p id="login-password-error" className="field-error">
              {errors.password}
            </p>
          )}
        </div>

        <div className="spread">
          <label className="check">
            <input type="checkbox" checked={form.rememberMe} onChange={(e) => set("rememberMe", e.target.checked)} />
            Remember me
          </label>
          <Link to="/forgot-password">Forgot password?</Link>
        </div>

        <button type="submit" className="block large" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <div className="auth-divider">or</div>

      {/* Single sign-on is not implemented on the backend, so these are shown
          as unavailable rather than pretending to work. */}
      <div className="auth-providers">
        <button type="button" className="secondary" disabled aria-describedby="sso-note">
          <GoogleLogo /> Continue with Google
        </button>
        <button type="button" className="secondary" disabled aria-describedby="sso-note">
          <MicrosoftLogo /> Continue with Microsoft
        </button>
      </div>
      <p id="sso-note" className="muted small auth-note">
        Google and Microsoft sign-in are not available yet.
      </p>

      <p className="auth-footer">
        Don&apos;t have an account? <Link to="/register">Create account</Link>
      </p>
    </>
  );
}
