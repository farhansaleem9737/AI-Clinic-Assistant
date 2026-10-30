import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { getErrorMessage } from "../../services/api";
import { createUser, getUser, setUserRoles, updateUser } from "../../services/userService";
import { avatarRole, byRank, joinedOn, roleStyle } from "../../utils/adminUsers";
import { EMAIL_PATTERN } from "../../utils/validation";
import Alert from "../Alert";
import Avatar from "../Avatar";
import ConfirmDialog from "../ConfirmDialog";
import FormField from "../FormField";

export function RoleBadges({ codes, roles }) {
  if (!codes.length) return <span className="muted">No role</span>;
  return (
    <span className="role-badges">
      {byRank(codes).map((code) => {
        const { label, tone } = roleStyle(code, roles);
        return (
          <span key={code} className={`badge role-badge ${tone}`}>
            {label}
          </span>
        );
      })}
    </span>
  );
}

/** View User: loads the current record, never secrets (the API has none to give). */
export function UserDetailsDialog({ user: listed, roles, onClose }) {
  const [user, setUser] = useState(listed);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    getUser(listed.id)
      .then((res) => live && setUser(res.data))
      .catch((err) => live && setError(getErrorMessage(err, "Could not load the latest details")));
    return () => {
      live = false;
    };
  }, [listed.id]);

  const rows = [
    ["Email", user.email],
    ["Phone", user.phone || <span className="muted">Not provided</span>],
    ["Roles", <RoleBadges key="r" codes={user.roles} roles={roles} />],
    ["Status", <span key="s" className={`badge ${user.is_active ? "ok" : "danger"}`}>{user.is_active ? "Active" : "Inactive"}</span>],
    ["Joined On", joinedOn(user.created_at)],
  ];
  return (
    <ConfirmDialog title="User details" confirmLabel="Close" cancelLabel="Back" onConfirm={onClose} onCancel={onClose} className="wide-dialog">
      <Alert>{error}</Alert>
      <div className="user-detail-head">
        <Avatar name={user.name} role={avatarRole(user)} src={user.photo_url} size={72} alt={`Photo of ${user.name}`} />
        <strong>{user.name}</strong>
      </div>
      <dl className="user-detail-list">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {(user.doctor_id || user.patient_id) && (
        <p className="user-detail-links">
          {user.doctor_id && <Link to={`/doctors/${user.doctor_id}`}>Open doctor profile</Link>}
          {user.patient_id && <Link to={`/patients/${user.patient_id}`}>Open patient record</Link>}
        </p>
      )}
      <p className="muted small">Phone numbers and photos belong to the doctor or patient profile and are edited there.</p>
    </ConfirmDialog>
  );
}

/** Edit User: name and email only; the API refuses anything else. */
export function EditUserDialog({ user, onClose, onSaved }) {
  const [form, setForm] = useState({ name: user.name, email: user.email });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    const found = {};
    if (!form.name.trim()) found.name = "Enter the full name.";
    if (!EMAIL_PATTERN.test(form.email.trim())) found.email = "Enter a valid email address.";
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError("");
    try {
      const res = await updateUser(user.id, { name: form.name.trim(), email: form.email.trim() });
      onSaved(res.data);
    } catch (err) {
      setError(getErrorMessage(err, "Could not save the changes"));
      setBusy(false);
    }
  };
  return (
    <ConfirmDialog title="Edit user" confirmLabel="Save changes" busy={busy} error={error} onConfirm={save} onCancel={onClose}>
      <FormField id="edit-user-name" label="Full name" error={errors.name}>
        <input id="edit-user-name" value={form.name} maxLength={100} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </FormField>
      <FormField id="edit-user-email" label="Email" error={errors.email}>
        <input id="edit-user-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
      </FormField>
      <p className="muted small">Roles are changed with Manage Roles, and status with Activate / Deactivate.</p>
    </ConfirmDialog>
  );
}

/**
 * Manage Roles. The Administrator role is never offered here: it is granted
 * by invitation and removed with "Remove administrator role" (password
 * required). An administrator's admin role is kept as it is.
 */
export function RolesDialog({ user, roles, onClose, onSaved }) {
  const isAdmin = user.roles.includes("admin");
  const [selected, setSelected] = useState(user.roles.filter((r) => r !== "admin"));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const choices = roles.filter((r) => r.code !== "admin");
  const toggle = (code) => setSelected((s) => (s.includes(code) ? s.filter((c) => c !== code) : [...s, code]));
  const next = isAdmin ? ["admin", ...selected] : selected;
  const removed = user.roles.filter((r) => !next.includes(r));

  const save = async () => {
    if (!next.length) return setError("A user needs at least one role. Deactivate the account instead.");
    setBusy(true);
    setError("");
    try {
      const res = await setUserRoles(user.id, next);
      onSaved(res.data);
    } catch (err) {
      setError(getErrorMessage(err, "Could not change the roles"));
      setBusy(false);
    }
  };
  return (
    <ConfirmDialog title={`Manage roles: ${user.name}`} confirmLabel="Save roles" busy={busy} error={error} onConfirm={save} onCancel={onClose}>
      <p className="muted">Current: <RoleBadges codes={user.roles} roles={roles} /></p>
      <fieldset className="role-choices">
        <legend>Roles</legend>
        {choices.map((r) => (
          <label key={r.code} className="checkbox-inline">
            <input type="checkbox" checked={selected.includes(r.code)} onChange={() => toggle(r.code)} />
            {r.name}
          </label>
        ))}
      </fieldset>
      {isAdmin && <p className="muted small">Administrator stays. Use “Remove administrator role” to take it away.</p>}
      {!isAdmin && <p className="muted small">Administrators are added by invitation: Add User &gt; Administrator.</p>}
      {removed.length > 0 && (
        <Alert kind="warn">
          Removing {removed.map((c) => roleStyle(c, roles).label).join(", ")} takes away that access immediately.
        </Alert>
      )}
    </ConfirmDialog>
  );
}

const ACCOUNT_TYPES = [
  { value: "receptionist", label: "Receptionist", hint: "Staff login. You set a temporary password and share it securely." },
  { value: "patient", label: "Patient", hint: "Registers a patient record (MRN assigned automatically)." },
  { value: "doctor", label: "Doctor", hint: "Opens Doctors, where a doctor profile is created with its department and credentials." },
  { value: "admin", label: "Administrator", hint: "Sends a secure, single-use invitation. No password is set here." },
];

/**
 * Add User: picks the account type, then uses that type's own workflow so
 * no rule is bypassed (MRN, doctor profile, admin invitation).
 */
export function AddUserDialog({ can, onClose, onCreated, onPatient, onAdmin, onDoctor }) {
  const allowed = ACCOUNT_TYPES.filter(
    (t) =>
      (t.value === "receptionist" && can("user:create") && can("user:assign_role")) ||
      (t.value === "patient" && can("patient:create")) ||
      (t.value === "doctor" && can("doctor:create")) ||
      (t.value === "admin" && can("admin_invitation:manage"))
  );
  const [type, setType] = useState(allowed[0]?.value ?? "");
  const [form, setForm] = useState({ name: "", email: "", password: "", confirm: "", active: "true" });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const submit = async () => {
    if (type === "patient") return onPatient();
    if (type === "doctor") return onDoctor();
    if (type === "admin") return onAdmin();
    const found = {};
    if (!form.name.trim()) found.name = "Enter the full name.";
    if (!EMAIL_PATTERN.test(form.email.trim())) found.email = "Enter a valid email address.";
    if (form.password.length < 8) found.password = "Use at least 8 characters.";
    if (form.confirm !== form.password) found.confirm = "The passwords do not match.";
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError("");
    try {
      const res = await createUser({ name: form.name.trim(), email: form.email.trim(), password: form.password, roles: [type] });
      onCreated(res.data, form.active === "true");
    } catch (err) {
      setError(getErrorMessage(err, "Could not create the account"));
      setBusy(false);
    }
  };

  const hint = ACCOUNT_TYPES.find((t) => t.value === type)?.hint;
  const label = { patient: "Continue", doctor: "Go to Doctors", admin: "Continue" }[type] ?? "Create user";
  return (
    <ConfirmDialog title="Add User" confirmLabel={label} busy={busy} error={error} onConfirm={submit} onCancel={onClose}>
      <FormField id="add-user-type" label="Role">
        <select id="add-user-type" value={type} onChange={(e) => setType(e.target.value)}>
          {allowed.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </FormField>
      {hint && <p className="muted small">{hint}</p>}
      {type === "receptionist" && (
        <>
          <FormField id="add-user-name" label="Full name" error={errors.name}>
            <input id="add-user-name" value={form.name} maxLength={100} onChange={set("name")} />
          </FormField>
          <FormField id="add-user-email" label="Email" error={errors.email}>
            <input id="add-user-email" type="email" autoComplete="off" value={form.email} onChange={set("email")} />
          </FormField>
          <FormField id="add-user-password" label="Temporary password" error={errors.password}>
            <input id="add-user-password" type="password" autoComplete="new-password" value={form.password} onChange={set("password")} />
          </FormField>
          <FormField id="add-user-confirm" label="Confirm password" error={errors.confirm}>
            <input id="add-user-confirm" type="password" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
          </FormField>
          <FormField id="add-user-status" label="Account status">
            <select id="add-user-status" value={form.active} onChange={set("active")}>
              <option value="true">Active</option>
              <option value="false">Inactive</option>
            </select>
          </FormField>
        </>
      )}
    </ConfirmDialog>
  );
}
