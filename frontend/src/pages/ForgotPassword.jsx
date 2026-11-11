import { ArrowLeft, CircleCheck, KeyRound, Mail, MailCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Alert from "../components/Alert";
import FormField from "../components/FormField";
import OtpInput from "../components/OtpInput";
import PasswordInput from "../components/PasswordInput";
import { requestPasswordReset, resetPassword, verifyResetCode } from "../services/authService";
import { EMAIL_PATTERN, PASSWORD_MAX, PASSWORD_MIN, errorProps } from "../utils/validation";

export const RESEND_SECONDS = 60;
const CODE_LENGTH = 6;
export const DONE = "Your password has been changed successfully. You can now sign in using your new password.";
const SIGN_IN_NOTICE = "Your password has been changed. Sign in with your new password.";
const OFFLINE = "We couldn't reach the server. Check your connection and try again.";
const RESET_CLOSED = new Set(["RESET_TOKEN_INVALID", "RESET_TOKEN_EXPIRED", "RESET_TOKEN_USED"]);

// Never a backend message: the page must read the same whether or not the account exists.
function requestError(err) {
  if (!err.response) return OFFLINE;
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
 * Forgot password (D127): email → 6-digit code → new password → done.
 *
 * - The answer to the email step is the same whether or not the account
 *   exists, and so is every refusal of a code.
 * - The code and the reset token the backend gives for it live in this
 *   component's state only: never in storage or the address bar. The token can
 *   only set a password; nobody is signed in afterwards.
 * - "Done" is shown only after the backend confirms the password was saved.
 */
export default function ForgotPassword() {
  const [step, setStep] = useState("email"); // email → code → password → done
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState("");
  const [formError, setFormError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);

  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState("");
  const [resendIn, setResendIn] = useState(0);
  const [resetToken, setResetToken] = useState(null);

  const [values, setValues] = useState({ next: "", confirm: "" });
  const [errors, setErrors] = useState({});

  // Counts down until another code may be requested.
  useEffect(() => {
    if (resendIn <= 0) return undefined;
    const timer = setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [resendIn]);

  useEffect(() => {
    if (step === "password") document.getElementById("reset-password-new")?.focus();
  }, [step]);

  // One request at a time, whatever the step.
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

  const sendCode = (resend) =>
    run(async () => {
      setFormError("");
      setNotice("");
      try {
        await requestPasswordReset(email.trim());
        setResendIn(RESEND_SECONDS);
        setCode("");
        setCodeError("");
        if (resend) setNotice("If an account exists for this address, a new code is on its way. Earlier codes no longer work.");
        setStep("code");
      } catch (err) {
        setFormError(requestError(err));
      }
    });

  const submitEmail = (e) => {
    e.preventDefault();
    if (!EMAIL_PATTERN.test(email.trim())) return setEmailError("Enter a valid email address.");
    setEmailError("");
    sendCode(false);
  };

  const verify = (entered = code) => {
    if (!new RegExp(`^\\d{${CODE_LENGTH}}$`).test(entered)) return setCodeError(`Enter the ${CODE_LENGTH}-digit code from the email.`);
    return run(async () => {
      setCodeError("");
      setFormError("");
      setNotice("");
      try {
        const { data } = await verifyResetCode(email.trim(), entered);
        setResetToken(data.reset_token);
        setCode("");
        setStep("password");
      } catch (err) {
        if (!err.response) setFormError(OFFLINE);
        else if (err.response.status === 429) setFormError("Too many attempts. Please wait a minute and try again.");
        else if (err.response.data?.error?.code === "RESET_CODE_INVALID" || err.response.status === 422) {
          setCodeError("That code is incorrect or has expired. Check the email, or request a new code.");
          setCode("");
          document.getElementById("reset-code")?.focus();
        } else setFormError("We couldn't check the code right now. Please try again.");
      }
    });
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

  const submitPassword = (e) => {
    e.preventDefault();
    const found = {};
    if (!values.next) found.next = "Enter a new password.";
    else if (live.next) found.next = live.next;
    if (!values.confirm) found.confirm = "Confirm your new password.";
    else if (live.confirm) found.confirm = live.confirm;
    setErrors(found);
    setFormError("");
    if (Object.keys(found).length) return;
    run(async () => {
      try {
        await resetPassword(resetToken, values.next);
        // Saved on the server: forget everything sensitive, then say so.
        setResetToken(null);
        setValues({ next: "", confirm: "" });
        setStep("done");
      } catch (err) {
        const closed = err.response?.data?.error?.code;
        if (RESET_CLOSED.has(closed)) {
          setResetToken(null);
          setValues({ next: "", confirm: "" });
          setStep("email");
          setFormError("Your password reset has expired or was replaced by a newer code. Request a new code to continue.");
        } else if (!err.response) setFormError(OFFLINE);
        else if (err.response.status === 422) setErrors({ next: `Use ${PASSWORD_MIN} to ${PASSWORD_MAX} characters.` });
        else if (err.response.status === 429) setFormError("Too many attempts. Please wait a minute and try again.");
        else setFormError("Your password could not be changed right now. Please try again.");
      }
    });
  };

  if (step === "done") {
    return (
      <div className="auth-state">
        <div className="auth-state-icon" aria-hidden="true">
          <CircleCheck size={28} />
        </div>
        <h2 className="auth-title">Password changed</h2>
        <p className="auth-subtitle" role="status">
          {DONE}
        </p>
        <Link to="/login" state={{ notice: SIGN_IN_NOTICE }} className="button block">
          Back to Sign In
        </Link>
      </div>
    );
  }

  if (step === "password") {
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
            onChange={(e) => {
              setValues((v) => ({ ...v, [name]: e.target.value }));
              setErrors((v) => ({ ...v, [name]: undefined }));
            }}
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
        <form className="auth-form" onSubmit={submitPassword} noValidate aria-busy={busy}>
          <div role="alert">{formError && <Alert>{formError}</Alert>}</div>
          {field("next", "reset-password-new", "New password", "Enter a new password")}
          {field("confirm", "reset-password-confirm", "Confirm new password", "Re-enter the new password")}
          <button type="submit" className="block large" disabled={busy}>
            {busy ? "Saving…" : "Reset Password"}
          </button>
        </form>
        <BackToSignIn />
      </>
    );
  }

  if (step === "code") {
    return (
      <>
        <div className="auth-state-icon" aria-hidden="true">
          <MailCheck size={28} />
        </div>
        <h2 className="auth-title">Enter the code</h2>
        <p className="auth-subtitle">
          If an account exists for <strong>{email.trim()}</strong>, we sent it a 6-digit code. Enter it below.
        </p>
        <form
          className="auth-form"
          onSubmit={(e) => {
            e.preventDefault();
            verify();
          }}
          noValidate
          aria-busy={busy}
        >
          <div role="alert">{formError && <Alert>{formError}</Alert>}</div>
          <div role="status">{notice && <Alert kind="success">{notice}</Alert>}</div>
          <FormField id="reset-code" label="Verification code" error={codeError}>
            <OtpInput
              id="reset-code"
              label="Verification code"
              value={code}
              onChange={(next) => {
                setCode(next);
                setCodeError("");
              }}
              onComplete={(full) => verify(full)}
              invalid={Boolean(codeError)}
              describedBy={codeError ? "reset-code-error" : "reset-code-hint"}
              disabled={busy}
              autoFocus
            />
          </FormField>
          <button type="submit" className="block large" disabled={busy}>
            {busy ? "Checking…" : "Verify code"}
          </button>
          <div className="register-code-actions">
            <button type="button" className="secondary" disabled={busy || resendIn > 0} onClick={() => sendCode(true)}>
              {resendIn > 0 ? `Resend code in ${resendIn}s` : "Resend code"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => {
                setStep("email");
                setCode("");
                setCodeError("");
                setNotice("");
                setFormError("");
              }}
            >
              Use a different email
            </button>
          </div>
          <p id="reset-code-hint" className="field-hint">
            The code expires in 10 minutes and allows 5 tries. Check your spam folder if it hasn&apos;t arrived.
          </p>
        </form>
        <BackToSignIn />
      </>
    );
  }

  return (
    <>
      <h2 className="auth-title">Forgot your password?</h2>
      <p className="auth-subtitle">
        Enter the email address you use to sign in. We&apos;ll email you a 6-digit code to reset your password.
      </p>

      <form className="auth-form" onSubmit={submitEmail} noValidate aria-busy={busy}>
        <div role="alert">{formError && <Alert>{formError}</Alert>}</div>
        <FormField id="forgot-email" label="Email address" error={emailError}>
          <div className={`input-icon${emailError ? " invalid" : ""}`}>
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
                setEmailError("");
              }}
              disabled={busy}
              {...errorProps("forgot-email", emailError)}
            />
          </div>
        </FormField>
        <button type="submit" className="block large" disabled={busy}>
          {busy ? "Sending…" : "Send code"}
        </button>
      </form>
      <BackToSignIn />
    </>
  );
}
