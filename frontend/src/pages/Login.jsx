import { Mail } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import Alert from "../components/Alert";
import FormField from "../components/FormField";
import PasswordInput from "../components/PasswordInput";
import SocialSignIn from "../components/SocialSignIn";
import { useAuth } from "../context/useAuth";
import { HOME_PATH, safeReturnPath } from "../routes/navigation";
import { EMAIL_PATTERN, errorProps } from "../utils/validation";

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
        {/* e.g. "Your account was created" when arriving from registration. */}
        {location.state?.notice && !formError && <Alert kind="success">{location.state.notice}</Alert>}
        <div role="alert">{formError && <Alert>{formError}</Alert>}</div>

        <FormField id="login-email" label="Email address" error={errors.email}>
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
              {...errorProps("login-email", errors.email)}
            />
          </div>
        </FormField>

        <FormField id="login-password" label="Password" error={errors.password}>
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
        </FormField>

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

      <SocialSignIn />

      <p className="auth-footer">
        Don&apos;t have an account? <Link to="/register">Create account</Link>
      </p>
    </>
  );
}
