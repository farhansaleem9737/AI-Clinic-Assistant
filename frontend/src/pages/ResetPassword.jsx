import { ArrowLeft, CircleCheck, KeyRound, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Alert from "../components/Alert";
import FormField from "../components/FormField";
import PasswordInput from "../components/PasswordInput";
import { checkResetToken, resetPassword } from "../services/authService";
import { PASSWORD_MAX, PASSWORD_MIN } from "../utils/validation";

const CLOSED = {
  RESET_TOKEN_EXPIRED: {
    title: "This link has expired",
    text: "Password reset links work for 15 minutes. Request a new one and use it soon after it arrives.",
  },
  RESET_TOKEN_USED: {
    title: "This link was already used",
    text: "Each password reset link works once. If you still need to reset your password, request a new link.",
  },
  RESET_TOKEN_INVALID: {
    title: "This link isn't valid",
    text: "Open the link from your most recent password reset email, or request a new one. Only the newest link works.",
  },
};
const SIGN_IN_NOTICE = "Your password has been reset. Sign in with your new password.";

// The token travels in the URL fragment (#token=…), which browsers never send to
// a server or in a Referer header. Once read it is removed from the address bar
// and history (see the effect below), so it cannot be copied from there later.
const readToken = () => new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token");

// While this page is open, nothing it links to learns its address.
function useNoReferrer() {
  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "referrer";
    meta.content = "no-referrer";
    document.head.appendChild(meta);
    return () => meta.remove();
  }, []);
}

function closedKind(err) {
  const code = err?.response?.data?.error?.code;
  return CLOSED[code] ? code : null;
}

function Closed({ code }) {
  const { title, text } = CLOSED[code];
  return (
    <div className="auth-state">
      <div className="auth-state-icon warning" aria-hidden="true">
        <TriangleAlert size={28} />
      </div>
      <h2 className="auth-title">{title}</h2>
      <p className="auth-subtitle">{text}</p>
      <Link to="/forgot-password" className="button block">
        Request a new link
      </Link>
      <p className="auth-footer">
        <Link to="/login" className="link-more">
          <ArrowLeft size={15} aria-hidden="true" /> Back to sign in
        </Link>
      </p>
    </div>
  );
}

function Done() {
  return (
    <div className="auth-state">
      <div className="auth-state-icon" aria-hidden="true">
        <CircleCheck size={28} />
      </div>
      <h2 className="auth-title">Password reset</h2>
      <p className="auth-subtitle" role="status">
        Your password has been changed and you have been signed out everywhere. Sign in with your new password.
      </p>
      <Link to="/login" state={{ notice: SIGN_IN_NOTICE }} className="button block">
        Return to sign in
      </Link>
    </div>
  );
}

/**
 * Reset password (D126), opened from the emailed link. The link is checked
 * first, so an expired or used one is explained before a password is typed.
 * The password rule is the one used everywhere else (8–128 characters). The
 * new password lives only in component state; afterwards the user signs in.
 */
export default function ResetPassword() {
  useNoReferrer();
  const [token] = useState(readToken); // pure: React may call it twice in development
  const [phase, setPhase] = useState(token ? "checking" : "RESET_TOKEN_INVALID");
  const [values, setValues] = useState({ next: "", confirm: "" });
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);

  useEffect(() => {
    if (window.location.hash) window.history.replaceState(window.history.state, "", window.location.pathname);
  }, []);

  useEffect(() => {
    if (!token) return undefined;
    let cancelled = false;
    checkResetToken(token)
      .then(() => !cancelled && setPhase("form"))
      // Any other failure (e.g. offline): show the form; the reset checks the link again.
      .catch((err) => !cancelled && setPhase(closedKind(err) ?? "form"));
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (phase === "form") document.getElementById("reset-password-new")?.focus();
  }, [phase]);

  if (phase === "checking") {
    return (
      <p className="muted" role="status">
        Checking your reset link…
      </p>
    );
  }
  if (CLOSED[phase]) return <Closed code={phase} />;
  if (phase === "done") return <Done />;

  const set = (field) => (e) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    setErrors((v) => ({ ...v, [field]: undefined }));
  };
  const live = {
    next:
      values.next && values.next.length < PASSWORD_MIN
        ? `At least ${PASSWORD_MIN} characters (${values.next.length} so far).`
        : values.next.length > PASSWORD_MAX
          ? `At most ${PASSWORD_MAX} characters.`
          : undefined,
    confirm: values.confirm && values.confirm !== values.next ? "Passwords do not match." : undefined,
  };

  const submit = async (e) => {
    e.preventDefault();
    if (inFlight.current) return;
    const found = {};
    if (!values.next) found.next = "Enter a new password.";
    else if (live.next) found.next = live.next;
    if (!values.confirm) found.confirm = "Confirm your new password.";
    else if (live.confirm) found.confirm = live.confirm;
    setErrors(found);
    setFormError("");
    if (Object.keys(found).length) return;

    inFlight.current = true;
    setBusy(true);
    try {
      await resetPassword(token, values.next);
      setValues({ next: "", confirm: "" });
      setPhase("done");
    } catch (err) {
      const closed = closedKind(err);
      if (closed) return setPhase(closed);
      if (!err.response) setFormError("We couldn't reach the server. Check your connection and try again.");
      else if (err.response.status === 422) setErrors({ next: `Use ${PASSWORD_MIN} to ${PASSWORD_MAX} characters.` });
      else if (err.response.status === 429) setFormError("Too many attempts. Please wait a minute and try again.");
      else setFormError("Your password could not be reset right now. Please try again.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const field = (name, id, label, placeholder) => {
    const error = errors[name] ?? live[name];
    return (
      <FormField id={id} label={label} error={error}>
        <PasswordInput
          id={id}
          name={name === "next" ? "new-password" : "confirm-password"}
          autoComplete="new-password"
          placeholder={placeholder}
          value={values[name]}
          onChange={set(name)}
          invalid={Boolean(errors[name])}
          describedBy={error ? `${id}-error` : name === "next" ? "reset-password-hint" : undefined}
          disabled={busy}
        />
        {name === "next" && !error && (
          <p id="reset-password-hint" className="field-hint">
            {PASSWORD_MIN}–{PASSWORD_MAX} characters. Spaces and symbols are welcome; a long passphrase is best.
          </p>
        )}
      </FormField>
    );
  };

  return (
    <>
      <div className="auth-state-icon" aria-hidden="true">
        <KeyRound size={26} />
      </div>
      <h2 className="auth-title">Create a new password</h2>
      <p className="auth-subtitle">Choose a new password for your account. You&apos;ll sign in with it afterwards.</p>
      <form className="auth-form" onSubmit={submit} noValidate>
        <div role="alert">{formError && <Alert>{formError}</Alert>}</div>
        {field("next", "reset-password-new", "New password", "Enter a new password")}
        {field("confirm", "reset-password-confirm", "Confirm new password", "Re-enter the new password")}
        <button type="submit" className="block large" disabled={busy}>
          {busy ? "Resetting…" : "Reset password"}
        </button>
      </form>
      <p className="auth-footer">
        <Link to="/login" className="link-more">
          <ArrowLeft size={15} aria-hidden="true" /> Back to sign in
        </Link>
      </p>
    </>
  );
}
