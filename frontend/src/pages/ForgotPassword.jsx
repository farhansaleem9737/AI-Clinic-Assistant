import { ArrowLeft, Mail, MailCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import Alert from "../components/Alert";
import FormField from "../components/FormField";
import { requestPasswordReset } from "../services/authService";
import { EMAIL_PATTERN, errorProps } from "../utils/validation";

const SENT = "Check your email. If an account exists for this address, you'll receive a password reset link shortly.";

// Never a backend message: the page must read the same whether or not the account exists.
function requestError(err) {
  if (!err.response) return "We couldn't reach the server. Check your connection and try again.";
  if (err.response.status === 429) return "Too many requests. Please wait a minute and try again.";
  if (err.response.status === 422) return "Enter a valid email address.";
  return "We couldn't send the request right now. Please try again in a moment.";
}

function BackToSignIn() {
  return (
    <p className="auth-footer">
      <Link to="/login" className="link-more">
        <ArrowLeft size={15} aria-hidden="true" /> Back to sign in
      </Link>
    </p>
  );
}

/**
 * Forgot password (D126): asks for the account's email and always answers the
 * same way, so the page cannot be used to find out who has an account. The
 * emailed link opens /reset-password.
 */
export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const [sentTo, setSentTo] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    const address = email.trim();
    if (!EMAIL_PATTERN.test(address)) return setError("Enter a valid email address.");
    setError("");
    setFormError("");
    setBusy(true);
    try {
      await requestPasswordReset(address);
      setSentTo(address);
    } catch (err) {
      setFormError(requestError(err));
    } finally {
      setBusy(false);
    }
  };

  if (sentTo) {
    return (
      <>
        <div className="auth-state-icon" aria-hidden="true">
          <MailCheck size={28} />
        </div>
        <h2 className="auth-title">Check your email</h2>
        <p className="auth-subtitle" role="status">
          {SENT}
        </p>
        <p className="muted">
          The link expires in 15 minutes. Can&apos;t find it? Look in your spam folder, or{" "}
          <button type="button" className="link-button" onClick={() => setSentTo(null)}>
            try again
          </button>
          .
        </p>
        <BackToSignIn />
      </>
    );
  }

  return (
    <>
      <h2 className="auth-title">Forgot your password?</h2>
      <p className="auth-subtitle">Enter the email address you use to sign in. We&apos;ll email you a link to create a new password.</p>

      <form className="auth-form" onSubmit={submit} noValidate>
        <div role="alert">{formError && <Alert>{formError}</Alert>}</div>
        <FormField id="forgot-email" label="Email address" error={error}>
          <div className={`input-icon${error ? " invalid" : ""}`}>
            <Mail size={18} aria-hidden="true" />
            <input
              id="forgot-email"
              name="email"
              type="email"
              inputMode="email"
              autoComplete="username"
              placeholder="Enter your email address"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setError("");
              }}
              disabled={busy}
              {...errorProps("forgot-email", error)}
            />
          </div>
        </FormField>
        <button type="submit" className="block large" disabled={busy}>
          {busy ? "Sending…" : "Send reset link"}
        </button>
      </form>
      <BackToSignIn />
    </>
  );
}
