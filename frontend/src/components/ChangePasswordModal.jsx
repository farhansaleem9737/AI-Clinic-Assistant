import { useEffect, useRef, useState } from "react";
import { setAccessToken } from "../services/api";
import { changePassword, getPasswordStatus } from "../services/authService";
import ConfirmDialog from "./ConfirmDialog";
import FormField from "./FormField";
import PasswordInput from "./PasswordInput";
import { PASSWORD_MAX, PASSWORD_MIN } from "../utils/validation";

const PASSWORD_CHANGED = "Your password has been updated successfully.";

// What a failed request means for the user: { field, message } or a form-level message.
function failure(err) {
  const status = err.response?.status;
  const code = err.response?.data?.error?.code;
  if (!err.response) return { form: "We couldn't reach the server. Check your connection and try again." };
  if (code === "REAUTHENTICATION_REQUIRED") return { field: "current", message: "Enter your current password to continue.", needCurrent: true };
  if (code === "INCORRECT_PASSWORD") return { field: "current", message: "The current password is incorrect." };
  if (code === "PASSWORD_UNCHANGED") return { field: "next", message: "Choose a password different from your current one." };
  if (status === 422) return { field: "next", message: `Use ${PASSWORD_MIN} to ${PASSWORD_MAX} characters.` };
  if (status === 429) return { form: "Too many attempts. Please wait a minute and try again." };
  if (status === 401 || code === "SESSION_REQUIRED") return { form: "Your session has expired. Please sign in again, then change your password." };
  return { form: "Your password could not be changed right now. Please try again." };
}

/**
 * Change the signed-in user's password (D116). The server decides whether the
 * current password is needed (it is unless this session signed in moments
 * ago), ends every other session and gives this browser a new one, so the
 * user stays signed in. Used from Personal Information and the account menu.
 */
export default function ChangePasswordModal({ onClose, onChanged }) {
  const [needCurrent, setNeedCurrent] = useState(null); // null while asking the server
  const [values, setValues] = useState({ current: "", next: "", confirm: "" });
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);

  useEffect(() => {
    let cancelled = false;
    getPasswordStatus()
      .then((res) => !cancelled && setNeedCurrent(res.data.current_password_required))
      // Unknown: ask for it; the server checks again either way.
      .catch(() => !cancelled && setNeedCurrent(true));
    return () => {
      cancelled = true;
    };
  }, []);

  // The fields appear once the server has answered: put the cursor in the first one.
  useEffect(() => {
    if (needCurrent !== null) document.getElementById(needCurrent ? "change-password-current" : "change-password-new")?.focus();
  }, [needCurrent]);

  const set = (field) => (e) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    setErrors((v) => ({ ...v, [field]: undefined }));
  };

  // Shown while typing, once there is something to check.
  const live = {
    next:
      values.next && values.next.length < PASSWORD_MIN
        ? `At least ${PASSWORD_MIN} characters (${values.next.length} so far).`
        : values.next.length > PASSWORD_MAX
          ? `At most ${PASSWORD_MAX} characters.`
          : undefined,
    confirm: values.confirm && values.confirm !== values.next ? "Passwords do not match." : undefined,
  };

  const submit = async () => {
    if (inFlight.current || needCurrent === null) return;
    const found = {};
    if (needCurrent && !values.current) found.current = "Enter your current password.";
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
      const res = await changePassword({ new_password: values.next, ...(needCurrent && { current_password: values.current }) });
      setAccessToken(res.data.access_token); // the new session; the refresh cookie was replaced too
      onChanged?.(PASSWORD_CHANGED);
      onClose();
    } catch (err) {
      const problem = failure(err);
      if (problem.needCurrent) setNeedCurrent(true);
      if (problem.field) setErrors({ [problem.field]: problem.message });
      else setFormError(problem.form);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  const onEnter = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      submit();
    }
  };

  const field = (name, id, label, autoComplete, placeholder) => {
    const error = errors[name] ?? live[name];
    return (
      <FormField id={id} label={label} error={error}>
        <PasswordInput
          id={id}
          autoComplete={autoComplete}
          placeholder={placeholder}
          value={values[name]}
          onChange={set(name)}
          onKeyDown={onEnter}
          invalid={Boolean(errors[name])}
          describedBy={error ? `${id}-error` : name === "next" ? "change-password-hint" : undefined}
          disabled={busy}
        />
        {name === "next" && !error && (
          <p id="change-password-hint" className="field-hint">
            {PASSWORD_MIN}–{PASSWORD_MAX} characters. Spaces and symbols are welcome; a long passphrase is best.
          </p>
        )}
      </FormField>
    );
  };

  return (
    <ConfirmDialog
      title="Change Password"
      description="Update your account password to keep your information secure."
      showClose
      confirmLabel={busy ? "Updating…" : "Update Password"}
      busy={busy}
      error={formError}
      onConfirm={submit}
      onCancel={onClose}
      className="change-password-dialog"
    >
      {needCurrent === null ? (
        <p className="muted" role="status">
          Checking your session…
        </p>
      ) : (
        <>
          {needCurrent && field("current", "change-password-current", "Current password", "current-password", "Enter your current password")}
          {field("next", "change-password-new", "New password", "new-password", "Enter a new password")}
          {field("confirm", "change-password-confirm", "Confirm new password", "new-password", "Re-enter the new password")}
        </>
      )}
    </ConfirmDialog>
  );
}
