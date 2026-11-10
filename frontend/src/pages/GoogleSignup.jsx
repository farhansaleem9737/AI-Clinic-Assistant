import { CalendarDays, Mail, Phone, UserRound, UsersRound, VenusAndMars } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Alert from "../components/Alert";
import ProfessionalFields from "../components/doctor-application/ProfessionalFields";
import { EMPTY_PROFESSIONAL, professionalPayload, professionalServerErrors, validateProfessional } from "../components/doctor-application/professional";
import FormField from "../components/FormField";
import { useAuth } from "../context/useAuth";
import { HOME_PATH } from "../routes/navigation";
import { getPublicDepartments } from "../services/departmentService";
import { getGoogleSignup, googleSignup } from "../services/googleAuthService";
import {
  ADULT_AGE_YEARS,
  birthDateError,
  errorProps,
  FULL_NAME_MAX,
  GENDER_OPTIONS,
  isoYearsAgo,
  MAX_AGE_YEARS,
  splitFullName,
  todayIso,
} from "../utils/validation";

const CONSENT_REQUIRED = "You must agree to the Terms of Service and Privacy Policy to create an account.";

/**
 * Finishing a "Sign up with Google" (D123). Google verified the email address,
 * so there is no password and no emailed code; everything else is the normal
 * registration: patient by default, or a doctor application that an
 * administrator reviews. The ticket for this is an HttpOnly cookie the backend
 * set; nothing about it is in the URL.
 */
export default function GoogleSignup() {
  const { signInWithToken } = useAuth();
  const navigate = useNavigate();
  const [ticket, setTicket] = useState({ status: "loading", email: "" });
  const [form, setForm] = useState({ accountType: "patient", fullName: "", dateOfBirth: "", gender: "", phone: "", agreed: false });
  const [professional, setProfessional] = useState(EMPTY_PROFESSIONAL);
  const [errors, setErrors] = useState({});
  const [professionalErrors, setProfessionalErrors] = useState({});
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [departments, setDepartments] = useState(null);
  const isDoctor = form.accountType === "doctor";

  useEffect(() => {
    let cancelled = false;
    getGoogleSignup()
      .then((res) => {
        if (cancelled) return;
        const { email, given_name: given, family_name: family } = res.data;
        setTicket({ status: "ready", email });
        setForm((f) => ({ ...f, fullName: [given, family].filter(Boolean).join(" ") }));
      })
      .catch(() => !cancelled && setTicket({ status: "expired", email: "" }));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isDoctor || departments) return;
    let cancelled = false;
    getPublicDepartments()
      .then((res) => !cancelled && setDepartments(res.data.items ?? []))
      .catch(() => !cancelled && setDepartments([]));
    return () => {
      cancelled = true;
    };
  }, [isDoctor, departments]);

  if (ticket.status === "loading") return <p className="muted" role="status">Loading your Google details…</p>;
  if (ticket.status === "expired") {
    return (
      <>
        <h2 className="auth-title">Sign-up expired</h2>
        <Alert kind="warn">This Google sign-up has expired or was already completed. Please start again.</Alert>
        <p className="auth-footer">
          <Link to="/register">Back to create account</Link> · <Link to="/login">Sign in</Link>
        </p>
      </>
    );
  }

  const set = (field, value) => {
    setForm((f) => ({ ...f, [field]: value }));
    setErrors((e) => ({ ...e, [field]: undefined }));
  };
  const bind = (field) => ({ value: form[field], onChange: (e) => set(field, e.target.value) });

  const validate = () => {
    const found = {};
    const name = form.fullName.trim();
    if (!name) found.fullName = "Enter your full name.";
    else if (!splitFullName(name)) found.fullName = "Enter your first and last name.";
    else if (name.length > FULL_NAME_MAX) found.fullName = `Use at most ${FULL_NAME_MAX} characters.`;
    const dob = birthDateError(form.dateOfBirth, { minAge: isDoctor ? ADULT_AGE_YEARS : 0 });
    if (dob) found.dateOfBirth = dob;
    if (!form.gender) found.gender = "Select your gender.";
    if (!form.agreed) found.agreed = CONSENT_REQUIRED;
    return { found, professional: isDoctor ? validateProfessional(professional) : {} };
  };

  const payload = () => {
    const phone = form.phone.trim();
    const common = phone ? { phone } : {};
    if (isDoctor) {
      return { account_type: "doctor", name: form.fullName.trim(), date_of_birth: form.dateOfBirth, gender: form.gender, ...common, ...professionalPayload(professional) };
    }
    return { account_type: "patient", ...splitFullName(form.fullName), date_of_birth: form.dateOfBirth, sex_at_birth: form.gender, ...common };
  };

  const submit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    const { found, professional: pro } = validate();
    setErrors(found);
    setProfessionalErrors(pro);
    setFormError("");
    if (Object.keys(found).length + Object.keys(pro).length > 0) return;
    setSubmitting(true);
    try {
      const res = await googleSignup(payload());
      await signInWithToken(res.data.access_token);
      navigate(HOME_PATH, { replace: true });
    } catch (err) {
      setSubmitting(false);
      const code = err.response?.data?.error?.code;
      if (code === "GOOGLE_STATE_INVALID") setTicket({ status: "expired", email: "" });
      else if (code === "EMAIL_TAKEN" || code === "GOOGLE_IDENTITY_IN_USE")
        setFormError("An account for this Google address already exists. Sign in instead.");
      else if (err.response?.status === 422 || code === "DEPARTMENT_UNAVAILABLE") {
        setProfessionalErrors(professionalServerErrors(err));
        setFormError("Please check your details and try again.");
      } else setFormError("We couldn't create your account right now. Please try again.");
    }
  };

  return (
    <>
      <h2 className="auth-title">Finish creating your account</h2>
      <p className="auth-subtitle">Google confirmed your email address. Just a few more details.</p>
      <form className="auth-form" onSubmit={submit} noValidate aria-busy={submitting}>
        <div role="alert">{formError && <Alert>{formError}</Alert>}</div>

        <FormField id="google-email" label="Email address">
          <div className="input-icon">
            <Mail size={18} aria-hidden="true" />
            <input id="google-email" type="email" value={ticket.email} readOnly aria-readonly="true" />
          </div>
        </FormField>

        <FormField id="google-account-type" label="Account Type">
          <div className="input-icon">
            <UsersRound size={18} aria-hidden="true" />
            <select id="google-account-type" {...bind("accountType")} disabled={submitting}>
              <option value="patient">Patient</option>
              <option value="doctor">Doctor (reviewed by the clinic before you can see patients)</option>
            </select>
          </div>
        </FormField>

        <FormField id="google-name" label="Full name" error={errors.fullName}>
          <div className={`input-icon${errors.fullName ? " invalid" : ""}`}>
            <UserRound size={18} aria-hidden="true" />
            <input id="google-name" autoComplete="name" {...bind("fullName")} {...errorProps("google-name", errors.fullName)} disabled={submitting} />
          </div>
        </FormField>

        <FormField id="google-dob" label="Date of birth" error={errors.dateOfBirth}>
          <div className={`input-icon${errors.dateOfBirth ? " invalid" : ""}`}>
            <CalendarDays size={18} aria-hidden="true" />
            <input
              id="google-dob"
              type="date"
              min={isoYearsAgo(MAX_AGE_YEARS)}
              max={isDoctor ? isoYearsAgo(ADULT_AGE_YEARS) : todayIso()}
              {...bind("dateOfBirth")}
              {...errorProps("google-dob", errors.dateOfBirth)}
              disabled={submitting}
            />
          </div>
        </FormField>

        <FormField id="google-gender" label="Gender" error={errors.gender}>
          <div className={`input-icon${errors.gender ? " invalid" : ""}`}>
            <VenusAndMars size={18} aria-hidden="true" />
            <select id="google-gender" {...bind("gender")} {...errorProps("google-gender", errors.gender)} disabled={submitting}>
              <option value="">Select your gender</option>
              {GENDER_OPTIONS.map((g) => (
                <option key={g.value} value={g.value}>
                  {g.label}
                </option>
              ))}
            </select>
          </div>
        </FormField>

        <FormField id="google-phone" label="Phone (optional)">
          <div className="input-icon">
            <Phone size={18} aria-hidden="true" />
            <input id="google-phone" type="tel" autoComplete="tel" maxLength={30} {...bind("phone")} disabled={submitting} />
          </div>
        </FormField>

        {isDoctor && (
          <ProfessionalFields
            idPrefix="google"
            values={professional}
            errors={professionalErrors}
            onChange={(field, value) => {
              setProfessional((p) => ({ ...p, [field]: value }));
              setProfessionalErrors((p) => ({ ...p, [field]: undefined }));
            }}
            departments={departments}
            disabled={submitting}
          />
        )}

        <div className="field">
          <label className="check">
            <input id="google-agree" type="checkbox" checked={form.agreed} onChange={(e) => set("agreed", e.target.checked)} {...errorProps("google-agree", errors.agreed)} />
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
            <p id="google-agree-error" className="field-error">
              {errors.agreed}
            </p>
          )}
        </div>

        <button type="submit" className="block large" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </button>
        {isDoctor && <p className="field-hint">After signing in you can upload your credentials from your application page.</p>}
      </form>
    </>
  );
}
