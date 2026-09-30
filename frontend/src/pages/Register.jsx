import { CalendarDays, Mail, UserRound } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import Alert from "../components/Alert";
import FormField from "../components/FormField";
import PasswordInput from "../components/PasswordInput";
import SocialSignIn from "../components/SocialSignIn";
import { useAuth } from "../context/useAuth";
import { HOME_PATH } from "../routes/navigation";
import {
  EMAIL_PATTERN,
  errorProps,
  FULL_NAME_MAX,
  PASSWORD_MAX,
  PASSWORD_MIN,
  splitFullName,
  todayIso,
} from "../utils/validation";

const EMPTY = { fullName: "", dateOfBirth: "", email: "", password: "", confirmPassword: "", agreed: false };
const CONSENT_REQUIRED = "You must agree to the Terms of Service and Privacy Policy to create an account.";

// Convenience checks; the backend validates everything again.
function validate(form) {
  const errors = {};
  const name = form.fullName.trim();
  if (!name) errors.fullName = "Enter your full name.";
  else if (!splitFullName(name)) errors.fullName = "Enter your first and last name.";
  else if (name.length > FULL_NAME_MAX) errors.fullName = `Use at most ${FULL_NAME_MAX} characters.`;

  if (!form.dateOfBirth) errors.dateOfBirth = "Enter your date of birth.";
  else if (form.dateOfBirth > todayIso()) errors.dateOfBirth = "Date of birth cannot be in the future.";
  else if (form.dateOfBirth < "1900-01-01") errors.dateOfBirth = "Enter a valid date of birth.";

  if (!EMAIL_PATTERN.test(form.email.trim())) errors.email = "Enter a valid email address.";

  if (!form.password) errors.password = "Create a password.";
  else if (form.password.length < PASSWORD_MIN) errors.password = `Use at least ${PASSWORD_MIN} characters.`;
  else if (form.password.length > PASSWORD_MAX) errors.password = `Use at most ${PASSWORD_MAX} characters.`;

  if (!form.confirmPassword) errors.confirmPassword = "Confirm your password.";
  else if (form.confirmPassword !== form.password) errors.confirmPassword = "Passwords do not match.";

  if (!form.agreed) errors.agreed = CONSENT_REQUIRED;
  return errors;
}

// Which form field a backend validation error belongs to.
const FIELD_OF = {
  first_name: "fullName",
  last_name: "fullName",
  date_of_birth: "dateOfBirth",
  email: "email",
  password: "password",
};
const SERVER_MESSAGES = {
  fullName: "Enter your first and last name.",
  dateOfBirth: "Enter a valid date of birth.",
  email: "Enter a valid email address.",
  password: `Use ${PASSWORD_MIN} to ${PASSWORD_MAX} characters.`,
};

/**
 * Turn a failed registration into safe messages: { fields, form }.
 * Never shows server text (it could carry internals), and never blames the
 * user's input when the real problem is the connection or the server.
 */
function registrationErrors(err) {
  const unavailable = { fields: {}, form: "We couldn't create your account right now. Please try again." };
  if (!err.response) return unavailable;
  const { status, data } = err.response;
  if (data?.error?.code === "EMAIL_TAKEN")
    return { fields: { email: "An account with this email already exists. Sign in instead." }, form: "" };
  if (status === 422) {
    const fields = {};
    for (const item of data?.error?.details?.errors ?? []) {
      const field = FIELD_OF[item.loc?.at(-1)];
      if (field) fields[field] = SERVER_MESSAGES[field];
    }
    if (Object.keys(fields).length > 0) return { fields, form: "" };
    return { fields: {}, form: "Please check your details and try again." };
  }
  return unavailable;
}

// Patient self-registration. There is no role choice: the backend always
// creates a patient, whatever a request claims.
export default function Register() {
  const { user, initializing, register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (initializing) return <p className="muted" role="status">Checking your session…</p>;
  // Already signed in, or signed in by the registration that just finished.
  if (user) return <Navigate to={HOME_PATH} replace />;

  const set = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };
  const bind = (field) => ({ value: form[field], onChange: (e) => set(field, e.target.value) });

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    const found = validate(form);
    setErrors(found);
    setFormError("");
    if (Object.keys(found).length > 0) return;

    setSubmitting(true);
    try {
      // Only what the API needs: no confirmation copy, no consent flag, no role.
      await register({
        ...splitFullName(form.fullName),
        date_of_birth: form.dateOfBirth,
        email: form.email.trim(),
        password: form.password,
      });
    } catch (err) {
      if (err.accountCreated) {
        // The account exists but the automatic sign-in did not go through.
        navigate("/login", { replace: true, state: { notice: "Your account was created. Please sign in." } });
        return;
      }
      const mapped = registrationErrors(err);
      setErrors(mapped.fields);
      setFormError(mapped.form);
      setSubmitting(false);
    }
  };

  return (
    <>
      <h2 className="auth-title">Create your account</h2>
      <p className="auth-subtitle">Get started with Clinic AI Assistant.</p>

      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <div role="alert">{formError && <Alert>{formError}</Alert>}</div>

        <FormField id="register-name" label="Full name" error={errors.fullName}>
          <div className={`input-icon${errors.fullName ? " invalid" : ""}`}>
            <UserRound size={18} aria-hidden="true" />
            <input
              id="register-name"
              name="name"
              type="text"
              autoComplete="name"
              placeholder="Enter your full name"
              maxLength={FULL_NAME_MAX}
              {...bind("fullName")}
              {...errorProps("register-name", errors.fullName)}
            />
          </div>
        </FormField>

        {/* Not in the visual reference: the patient record cannot exist without it. */}
        <FormField id="register-dob" label="Date of birth" error={errors.dateOfBirth}>
          <div className={`input-icon${errors.dateOfBirth ? " invalid" : ""}`}>
            <CalendarDays size={18} aria-hidden="true" />
            <input
              id="register-dob"
              name="bday"
              type="date"
              autoComplete="bday"
              min="1900-01-01"
              max={todayIso()}
              {...bind("dateOfBirth")}
              {...errorProps("register-dob", errors.dateOfBirth)}
            />
          </div>
        </FormField>

        <FormField id="register-email" label="Email address" error={errors.email}>
          <div className={`input-icon${errors.email ? " invalid" : ""}`}>
            <Mail size={18} aria-hidden="true" />
            <input
              id="register-email"
              name="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              placeholder="Enter your email address"
              {...bind("email")}
              {...errorProps("register-email", errors.email)}
            />
          </div>
        </FormField>

        <FormField id="register-password" label="Password" error={errors.password}>
          <PasswordInput
            id="register-password"
            name="new-password"
            autoComplete="new-password"
            placeholder="Create a password"
            {...bind("password")}
            invalid={Boolean(errors.password)}
            describedBy={errors.password ? "register-password-error" : "register-password-hint"}
          />
          {!errors.password && (
            <p id="register-password-hint" className="field-hint">
              At least {PASSWORD_MIN} characters.
            </p>
          )}
        </FormField>

        <FormField id="register-confirm" label="Confirm password" error={errors.confirmPassword}>
          <PasswordInput
            id="register-confirm"
            name="confirm-password"
            autoComplete="new-password"
            placeholder="Confirm your password"
            {...bind("confirmPassword")}
            invalid={Boolean(errors.confirmPassword)}
            describedBy={errors.confirmPassword ? "register-confirm-error" : undefined}
          />
        </FormField>

        <button type="submit" className="block large" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </button>

        <div className="field">
          <label className="check">
            <input
              id="register-agree"
              type="checkbox"
              checked={form.agreed}
              onChange={(e) => set("agreed", e.target.checked)}
              {...errorProps("register-agree", errors.agreed)}
            />
            <span>
              I agree to the{" "}
              <Link to="/terms" target="_blank" rel="noopener">
                Terms of Service
              </Link>{" "}
              and{" "}
              <Link to="/privacy" target="_blank" rel="noopener">
                Privacy Policy
              </Link>
            </span>
          </label>
          {errors.agreed && (
            <p id="register-agree-error" className="field-error">
              {errors.agreed}
            </p>
          )}
        </div>
      </form>

      <SocialSignIn />

      <p className="auth-footer">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </>
  );
}
