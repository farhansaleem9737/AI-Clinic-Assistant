import { CircleCheck, KeyRound, Link2, Mail, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Alert from "../components/Alert";
import FormField from "../components/FormField";
import OtpInput from "../components/OtpInput";
import PasswordInput from "../components/PasswordInput";
import { useAuth } from "../context/useAuth";
import { HOME_PATH } from "../routes/navigation";
import { cancelGoogleLink, getGoogleLinkTicket, sendGoogleLinkCode, verifyGoogleLink } from "../services/googleAuthService";

export const LINKED = "Google sign-in is now connected to your account.";
const OFFLINE = "We couldn't reach the server. Check your connection and try again.";

function Expired() {
  return (
    <div className="auth-state">
      <div className="auth-state-icon warning" aria-hidden="true">
        <TriangleAlert size={28} />
      </div>
      <h2 className="auth-title">This step has expired</h2>
      <p className="auth-subtitle">
        Linking Google has to be finished within 15 minutes, with at most 5 tries. Continue with Google again to start over, or
        sign in with your password.
      </p>
      <Link to="/login" className="button block">
        Back to sign in
      </Link>
    </div>
  );
}

/**
 * Google confirmed an email address that already has an account here (D128).
 * Nothing is linked yet: the owner proves the account is theirs with its
 * password or (patients and applicants) a code emailed to it. Then the backend
 * links Google to that same account and starts the normal session. The step
 * lives in an HttpOnly cookie; this page holds no token.
 */
export default function GoogleLink() {
  const { signInWithToken } = useAuth();
  const navigate = useNavigate();
  const [ticket, setTicket] = useState(null);
  const [phase, setPhase] = useState("loading"); // loading → form → linked | expired
  const [method, setMethod] = useState("password");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [resendIn, setResendIn] = useState(0);
  const [fieldError, setFieldError] = useState("");
  const [formError, setFormError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const started = useRef(false); // once, although development mode runs effects twice

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    getGoogleLinkTicket()
      .then(({ data }) => {
        setTicket(data);
        setMethod(data.methods.includes("password") ? "password" : "email_code");
        setCodeSent(data.code_sent);
        setResendIn(data.resend_in);
        setPhase("form");
      })
      .catch((err) => (err.response ? setPhase("expired") : setFormError(OFFLINE)));
  }, []);

  useEffect(() => {
    if (resendIn <= 0) return undefined;
    const timer = setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [resendIn]);

  const run = async (work) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      await work();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const failed = (err) => {
    const error = err.response?.data?.error;
    if (!err.response) return setFormError(OFFLINE);
    if (error?.code === "GOOGLE_STATE_INVALID") return setPhase("expired");
    if (error?.code === "ACCOUNT_INACTIVE") return setFormError("This account can't sign in. Please contact the clinic.");
    if (error?.code === "GOOGLE_IDENTITY_IN_USE") return setFormError("That Google account is already linked to another account.");
    if (error?.code === "GOOGLE_ALREADY_LINKED") return setFormError("A different Google account is already linked to this account.");
    if (error?.code === "CODE_RECENTLY_SENT") {
      setResendIn(error.details?.retry_after_seconds ?? 60);
      return setNotice("A code was sent moments ago. Use that one, or wait to send another.");
    }
    if (error?.code === "LINK_PROOF_INVALID") {
      const left = error.details?.attempts_left;
      const tries = left ? ` ${left} ${left === 1 ? "try" : "tries"} left.` : "";
      setFieldError(
        (method === "password" ? "The password is incorrect." : "That code is incorrect or has expired.") + tries
      );
      if (method === "email_code") setCode("");
      return undefined;
    }
    if (err.response.status === 429) return setFormError("Too many attempts. Please wait a minute and try again.");
    if (error?.code === "EMAIL_NOT_SENT") return setFormError("We couldn't send the code right now. Please try again.");
    return setFormError("We couldn't link Google right now. Please try again.");
  };

  const sendCode = () =>
    run(async () => {
      setFormError("");
      setNotice("");
      setFieldError("");
      try {
        await sendGoogleLinkCode();
        setCodeSent(true);
        setResendIn(60);
        setCode("");
        setNotice(`We sent a 6-digit code to ${ticket.email}.`);
      } catch (err) {
        failed(err);
      }
    });

  const prove = (proof) =>
    run(async () => {
      setFormError("");
      setFieldError("");
      try {
        const { data } = await verifyGoogleLink(proof);
        setPassword("");
        await signInWithToken(data.access_token);
        setPhase("linked");
      } catch (err) {
        failed(err);
      }
    });

  const submit = (e) => {
    e.preventDefault();
    if (method === "password") {
      if (!password) return setFieldError("Enter your password.");
      return prove({ password });
    }
    if (!/^\d{6}$/.test(code)) return setFieldError("Enter the 6-digit code from the email.");
    return prove({ code });
  };

  const cancel = async () => {
    try {
      await cancelGoogleLink();
    } catch {
      // Nothing was linked either way; the step expires on its own.
    }
    navigate("/login", { replace: true });
  };

  const choose = (next) => {
    setMethod(next);
    setFieldError("");
    setFormError("");
    setNotice("");
  };

  if (phase === "loading") {
    return formError ? (
      <>
        <Alert>{formError}</Alert>
        <p className="auth-footer">
          <Link to="/login">Back to sign in</Link>
        </p>
      </>
    ) : (
      <p className="muted" role="status">
        Checking your Google sign-in…
      </p>
    );
  }
  if (phase === "expired") return <Expired />;
  if (phase === "linked") {
    return (
      <div className="auth-state">
        <div className="auth-state-icon" aria-hidden="true">
          <CircleCheck size={28} />
        </div>
        <h2 className="auth-title">Google connected</h2>
        <p className="auth-subtitle" role="status">
          {LINKED} Next time, Continue with Google signs you straight in. Your password keeps working too.
        </p>
        <button type="button" className="block large" onClick={() => navigate(HOME_PATH, { replace: true })}>
          Continue to your dashboard
        </button>
      </div>
    );
  }

  const methods = ticket.methods;
  return (
    <>
      <div className="auth-state-icon" aria-hidden="true">
        <Link2 size={26} />
      </div>
      <h2 className="auth-title">Link your Google account</h2>
      <p className="auth-subtitle">
        An account already exists with this email address (<strong>{ticket.email}</strong>). Verify your existing account to use
        Google for future sign-ins.
      </p>

      {methods.length === 0 ? (
        <>
          <Alert kind="warn">
            This account can&apos;t be linked here. Sign in with your usual method, then link Google from Account › Connected
            accounts.
          </Alert>
          <button type="button" className="secondary block" onClick={cancel}>
            Back to sign in
          </button>
        </>
      ) : (
        <form className="auth-form" onSubmit={submit} noValidate aria-busy={busy}>
          {methods.length > 1 && (
            <div className="link-methods" role="radiogroup" aria-label="How to verify">
              <button
                type="button"
                role="radio"
                aria-checked={method === "password"}
                className={method === "password" ? "" : "secondary"}
                onClick={() => choose("password")}
                disabled={busy}
              >
                <KeyRound size={16} aria-hidden="true" /> Password
              </button>
              <button
                type="button"
                role="radio"
                aria-checked={method === "email_code"}
                className={method === "email_code" ? "" : "secondary"}
                onClick={() => choose("email_code")}
                disabled={busy}
              >
                <Mail size={16} aria-hidden="true" /> Email code
              </button>
            </div>
          )}
          <div role="alert">{formError && <Alert>{formError}</Alert>}</div>
          <div role="status">{notice && <Alert kind="success">{notice}</Alert>}</div>

          {method === "password" ? (
            <FormField id="link-password" label="Password for this account" error={fieldError}>
              <PasswordInput
                id="link-password"
                name="current-password"
                autoComplete="current-password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setFieldError("");
                }}
                invalid={Boolean(fieldError)}
                describedBy={fieldError ? "link-password-error" : undefined}
                disabled={busy}
              />
            </FormField>
          ) : !codeSent ? (
            <>
              <p className="muted">We&apos;ll email a 6-digit code to {ticket.email}.</p>
              <button type="button" className="block large" onClick={sendCode} disabled={busy}>
                {busy ? "Sending…" : "Send code"}
              </button>
            </>
          ) : (
            <>
              <FormField id="link-code" label="Verification code" error={fieldError}>
                <OtpInput
                  id="link-code"
                  label="Verification code"
                  value={code}
                  onChange={(next) => {
                    setCode(next);
                    setFieldError("");
                  }}
                  onComplete={(full) => prove({ code: full })}
                  invalid={Boolean(fieldError)}
                  describedBy={fieldError ? "link-code-error" : undefined}
                  disabled={busy}
                  autoFocus
                />
              </FormField>
              <button type="button" className="secondary" onClick={sendCode} disabled={busy || resendIn > 0}>
                {resendIn > 0 ? `Resend code in ${resendIn}s` : "Resend code"}
              </button>
            </>
          )}

          {(method === "password" || codeSent) && (
            <button type="submit" className="block large" disabled={busy}>
              {busy ? "Verifying…" : "Verify and link Google"}
            </button>
          )}
          <button type="button" className="link-button" onClick={cancel} disabled={busy}>
            Don&apos;t link, go back to sign in
          </button>
        </form>
      )}
      <p className="auth-footer">
        <Link to="/forgot-password">Forgot your password?</Link>
      </p>
    </>
  );
}
