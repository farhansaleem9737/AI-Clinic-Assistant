import { CalendarDays, CheckCircle2, Mail, Phone, UserRound, UsersRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import Alert from "../components/Alert";
import CredentialPicker from "../components/doctor-application/CredentialPicker";
import ProfessionalFields from "../components/doctor-application/ProfessionalFields";
import {
  EMPTY_PROFESSIONAL,
  professionalPayload,
  professionalServerErrors,
  uploadCredentials,
  validateProfessional,
} from "../components/doctor-application/professional";
import FormField from "../components/FormField";
import PasswordInput from "../components/PasswordInput";
import SocialSignIn from "../components/SocialSignIn";
import { useAuth } from "../context/useAuth";
import { HOME_PATH } from "../routes/navigation";
import { getPublicDepartments } from "../services/departmentService";
import {
  EMAIL_PATTERN,
  errorProps,
  FULL_NAME_MAX,
  PASSWORD_MAX,
  PASSWORD_MIN,
  splitFullName,
  todayIso,
} from "../utils/validation";

const EMPTY = {
  accountType: "",
  fullName: "",
  dateOfBirth: "",
  email: "",
  phone: "",
  password: "",
  confirmPassword: "",
  agreed: false,
};
const NO_FILES = { registration_certificate: null, degree_certificate: null, supporting_document: null };
const CONSENT_REQUIRED = "You must agree to the Terms of Service and Privacy Policy to create an account.";

// Convenience checks; the backend validates everything again.
function validate(form, professional) {
  const errors = {};
  if (!["patient", "doctor"].includes(form.accountType)) errors.accountType = "Choose an account type.";

  const name = form.fullName.trim();
  if (!name) errors.fullName = "Enter your full name.";
  else if (!splitFullName(name)) errors.fullName = "Enter your first and last name.";
  else if (name.length > FULL_NAME_MAX) errors.fullName = `Use at most ${FULL_NAME_MAX} characters.`;

  // A patient record cannot exist without a date of birth; a doctor account does not need one.
  if (form.accountType !== "doctor") {
    if (!form.dateOfBirth) errors.dateOfBirth = "Enter your date of birth.";
    else if (form.dateOfBirth > todayIso()) errors.dateOfBirth = "Date of birth cannot be in the future.";
    else if (form.dateOfBirth < "1900-01-01") errors.dateOfBirth = "Enter a valid date of birth.";
  }

  if (!EMAIL_PATTERN.test(form.email.trim())) errors.email = "Enter a valid email address.";

  if (!form.password) errors.password = "Create a password.";
  else if (form.password.length < PASSWORD_MIN) errors.password = `Use at least ${PASSWORD_MIN} characters.`;
  else if (form.password.length > PASSWORD_MAX) errors.password = `Use at most ${PASSWORD_MAX} characters.`;

  if (!form.confirmPassword) errors.confirmPassword = "Confirm your password.";
  else if (form.confirmPassword !== form.password) errors.confirmPassword = "Passwords do not match.";

  if (!form.agreed) errors.agreed = CONSENT_REQUIRED;

  return { errors, professional: form.accountType === "doctor" ? validateProfessional(professional) : {} };
}

// Which form field a backend validation error belongs to.
const FIELD_OF = {
  first_name: "fullName",
  last_name: "fullName",
  name: "fullName",
  date_of_birth: "dateOfBirth",
  email: "email",
  phone: "phone",
  password: "password",
};
const PATIENT_ONLY = ["first_name", "last_name", "date_of_birth"];
const DOCTOR_ONLY = ["name"];
const SERVER_MESSAGES = {
  fullName: "Enter your first and last name.",
  dateOfBirth: "Enter a valid date of birth.",
  email: "Enter a valid email address.",
  phone: "Enter a phone number of at most 30 characters.",
  password: `Use ${PASSWORD_MIN} to ${PASSWORD_MAX} characters.`,
};

/**
 * Turn a failed registration into safe messages: { fields, professional, form }.
 * Never shows server text (it could carry internals), and never blames the
 * user's input when the real problem is the connection or the server.
 */
function registrationErrors(err, isDoctor) {
  const unavailable = { fields: {}, professional: {}, form: "We couldn't create your account right now. Please try again." };
  if (!err.response) return unavailable;
  const { status, data } = err.response;
  if (data?.error?.code === "EMAIL_TAKEN")
    return { fields: { email: "An account with this email already exists. Sign in instead." }, professional: {}, form: "" };
  const professional = professionalServerErrors(err);
  if (status === 422 || data?.error?.code === "DEPARTMENT_UNAVAILABLE") {
    const fields = {};
    for (const item of data?.error?.details?.errors ?? []) {
      const name = item.loc?.at(-1);
      // Only fields of the request that was sent: a doctor request has no
      // first_name or date_of_birth, so such errors mean something else.
      if ((isDoctor ? PATIENT_ONLY : DOCTOR_ONLY).includes(name)) continue;
      const field = FIELD_OF[name];
      if (field) fields[field] = SERVER_MESSAGES[field];
    }
    if (Object.keys(fields).length + Object.keys(professional).length > 0) return { fields, professional, form: "" };
    return { fields: {}, professional: {}, form: "Please check your details and try again." };
  }
  return unavailable;
}

function DoctorAccountCreated({ uploads }) {
  const failed = uploads.filter((u) => !u.ok);
  return (
    <div className="register-done" role="status">
      <CheckCircle2 className="register-done-icon" size={48} aria-hidden="true" />
      <h2 className="auth-title">Doctor Account Created</h2>
      <p className="auth-subtitle">
        Your account has been created successfully. You can complete your professional details and submit your
        credentials for verification.
      </p>
      <Alert kind="info">
        Your account is pending verification. Patients cannot find or book you until the clinic administration
        has reviewed and approved your credentials.
      </Alert>
      {uploads.length > 0 && (
        <ul className="upload-results">
          {uploads.map((u) => (
            <li key={u.type} className={u.ok ? "ok" : "failed"}>
              <strong>{u.label}:</strong> {u.ok ? "uploaded" : `not uploaded. ${u.message}`}
            </li>
          ))}
        </ul>
      )}
      {failed.length > 0 && <p className="muted small">You can upload these documents again from your application.</p>}
      <Link to="/doctor/application" className="button block large">
        Continue to my application
      </Link>
    </div>
  );
}

/**
 * Self-registration as a patient or as a doctor. The account type is only a
 * request: the backend creates a patient, or a doctor *applicant* with no
 * clinical access until an administrator verifies the credentials (D77).
 */
export default function Register() {
  const { user, initializing, register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY);
  const [professional, setProfessional] = useState(EMPTY_PROFESSIONAL);
  const [files, setFiles] = useState(NO_FILES);
  const [progress, setProgress] = useState({});
  const [errors, setErrors] = useState({});
  const [professionalErrors, setProfessionalErrors] = useState({});
  const [formError, setFormError] = useState("");
  // form -> submitting -> (doctor only) done. Past "form", the session that
  // registration opens must not bounce the user away from this page.
  const [stage, setStage] = useState("form");
  const [uploads, setUploads] = useState([]);
  const [departments, setDepartments] = useState(null);
  const [departmentsError, setDepartmentsError] = useState("");
  // Bumped after a failed submit: move to the first problem, which on the
  // long doctor form may be far above the button.
  const [showProblem, setShowProblem] = useState(0);
  const formRef = useRef(null);
  const isDoctor = form.accountType === "doctor";

  useEffect(() => {
    if (!showProblem || !formRef.current) return;
    const target =
      formRef.current.querySelector('[aria-invalid="true"]') ?? formRef.current.querySelector(".register-form-alert");
    if (!target) return;
    target.scrollIntoView?.({ block: "center", behavior: "smooth" });
    target.focus({ preventScroll: true });
  }, [showProblem]);

  // Departments are needed only once someone chooses Doctor.
  useEffect(() => {
    if (!isDoctor || departments) return;
    let cancelled = false;
    getPublicDepartments()
      .then((res) => !cancelled && setDepartments(res.data.items ?? []))
      .catch(() => {
        if (cancelled) return;
        setDepartments([]);
        setDepartmentsError("Departments could not be loaded. You can add your department later.");
      });
    return () => {
      cancelled = true;
    };
  }, [isDoctor, departments]);

  if (initializing) return <p className="muted" role="status">Checking your session…</p>;
  if (stage === "done") return <DoctorAccountCreated uploads={uploads} />;
  // Already signed in (not by the registration in progress here).
  if (user && stage === "form") return <Navigate to={HOME_PATH} replace />;

  const submitting = stage === "submitting";
  const set = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };
  const bind = (field) => ({ value: form[field], onChange: (e) => set(field, e.target.value) });
  const setProfessionalField = (field, value) => {
    setProfessional((current) => ({ ...current, [field]: value }));
    setProfessionalErrors((current) => ({ ...current, [field]: undefined }));
  };

  // Only what the API needs for the chosen account type: no confirmation
  // copy, no consent flag, no role, and nothing from the other type's fields.
  const payload = () => {
    const common = { email: form.email.trim(), password: form.password };
    const phone = form.phone.trim();
    if (phone) common.phone = phone;
    if (isDoctor)
      return { account_type: "doctor", name: form.fullName.trim(), ...common, ...professionalPayload(professional) };
    return { account_type: "patient", ...splitFullName(form.fullName), date_of_birth: form.dateOfBirth, ...common };
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    const found = validate(form, professional);
    setErrors(found.errors);
    setProfessionalErrors(found.professional);
    setFormError("");
    if (Object.keys(found.errors).length + Object.keys(found.professional).length > 0) {
      setShowProblem((n) => n + 1);
      return;
    }

    setStage("submitting");
    try {
      await register(payload());
    } catch (err) {
      if (err.accountCreated) {
        // The account exists but the automatic sign-in did not go through.
        const notice = isDoctor
          ? "Your account was created. Please sign in to complete your application and upload your documents."
          : "Your account was created. Please sign in.";
        navigate("/login", { replace: true, state: { notice } });
        return;
      }
      const mapped = registrationErrors(err, isDoctor);
      setErrors(mapped.fields);
      setProfessionalErrors(mapped.professional);
      setFormError(mapped.form);
      setStage("form");
      setShowProblem((n) => n + 1);
      return;
    }

    if (!isDoctor) {
      navigate(HOME_PATH, { replace: true });
      return;
    }
    // Signed in now: send the chosen credentials, then say what happened to each.
    const results = await uploadCredentials(files, (type, percent) =>
      setProgress((current) => ({ ...current, [type]: percent }))
    );
    setUploads(results);
    setStage("done");
  };

  return (
    <>
      <h2 className="auth-title">Create your account</h2>
      <p className="auth-subtitle">Get started with Clinic AI Assistant.</p>

      <form ref={formRef} className="auth-form" onSubmit={handleSubmit} noValidate aria-busy={submitting}>
        <div role="alert" className="register-form-alert" tabIndex={-1}>
          {formError && <Alert>{formError}</Alert>}
        </div>

        <FormField id="register-account-type" label="Account Type" error={errors.accountType}>
          <div className={`input-icon${errors.accountType ? " invalid" : ""}`}>
            <UsersRound size={18} aria-hidden="true" />
            <select
              id="register-account-type"
              name="account-type"
              {...bind("accountType")}
              {...errorProps("register-account-type", errors.accountType)}
              disabled={submitting}
            >
              <option value="" disabled>
                Select your account type
              </option>
              <option value="patient">Patient</option>
              <option value="doctor">Doctor</option>
            </select>
          </div>
        </FormField>

        {isDoctor && (
          <h3 className="register-section-title" id="register-account-section">
            Basic Account Information
          </h3>
        )}

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
        {!isDoctor && (
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
        )}

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

        <FormField
          id="register-phone"
          label={
            <>
              Phone number <span className="optional">(optional)</span>
            </>
          }
          error={errors.phone}
        >
          <div className={`input-icon${errors.phone ? " invalid" : ""}`}>
            <Phone size={18} aria-hidden="true" />
            <input
              id="register-phone"
              name="tel"
              type="tel"
              autoComplete="tel"
              placeholder="Enter your phone number"
              maxLength={30}
              {...bind("phone")}
              {...errorProps("register-phone", errors.phone)}
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

        {isDoctor && (
          <>
            <section className="register-section" aria-labelledby="register-pro-title">
              <h3 className="register-section-title" id="register-pro-title">
                Professional Information
              </h3>
              <p className="field-hint">
                All professional details are optional now. You can add or change them later from your application.
              </p>
              <ProfessionalFields
                idPrefix="register"
                values={professional}
                errors={professionalErrors}
                onChange={setProfessionalField}
                departments={departments}
                departmentsError={departmentsError}
                disabled={submitting}
              />
            </section>

            <section className="register-section" aria-labelledby="register-docs-title">
              <h3 className="register-section-title" id="register-docs-title">
                Professional Verification Documents
              </h3>
              <p className="field-hint">
                Upload your professional documents to help us verify your medical credentials. You can also provide
                these later.
              </p>
              <CredentialPicker
                idPrefix="register-credential"
                files={files}
                progress={progress}
                disabled={submitting}
                onChange={(type, file) => setFiles((current) => ({ ...current, [type]: file }))}
              />
            </section>
          </>
        )}

        <button type="submit" className="block large" disabled={submitting}>
          {submitting ? (isDoctor ? "Creating account and uploading…" : "Creating account…") : "Create account"}
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
