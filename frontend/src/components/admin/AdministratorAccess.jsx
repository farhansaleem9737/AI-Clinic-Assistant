import { MailPlus } from "lucide-react";
import { useEffect, useState } from "react";
import {
  createInvitation,
  listInvitations,
  resendInvitation,
  revokeAdminRole,
  revokeInvitation,
} from "../../services/adminService";
import { getErrorMessage } from "../../services/api";
import Alert from "../Alert";
import ConfirmDialog from "../ConfirmDialog";
import FormField from "../FormField";
import { INVITATION_STATUS, deliveryLabel, formatDateTime, inviteNotice, validateInvite } from "./adminAccess";

const EMPTY_INVITE = { email: "", name: "", current_password: "" };

export function InviteDialog({ onClose, onInvited }) {
  const [form, setForm] = useState(EMPTY_INVITE);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const submit = async () => {
    const found = validateInvite(form);
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError("");
    try {
      const res = await createInvitation({
        email: form.email.trim(),
        name: form.name.trim() || null,
        role: "admin",
        current_password: form.current_password,
      });
      onInvited(res.data);
    } catch (err) {
      setError(getErrorMessage(err, "Could not create the invitation"));
      setBusy(false);
    }
  };

  const err = (field) => (errors[field] ? { "aria-invalid": true, "aria-describedby": `invite-${field}-error` } : {});
  return (
    <ConfirmDialog
      title="Invite Administrator"
      confirmLabel="Send Invitation"
      busy={busy}
      error={error}
      onConfirm={submit}
      onCancel={onClose}
    >
      <p className="muted">
        The invitee receives a single-use link that expires. Administrators can manage every account and record in
        the clinic.
      </p>
      <form
        className="stack"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <FormField id="invite-email" label="Email address" error={errors.email}>
          <input id="invite-email" type="email" autoComplete="off" value={form.email} onChange={set("email")} {...err("email")} />
        </FormField>
        <FormField id="invite-name" label="Name (optional)" error={errors.name}>
          <input id="invite-name" value={form.name} onChange={set("name")} {...err("name")} />
        </FormField>
        <FormField id="invite-role" label="Role">
          <select id="invite-role" value="admin" disabled>
            <option value="admin">Administrator</option>
          </select>
        </FormField>
        <FormField id="invite-current_password" label="Your password" error={errors.current_password}>
          <input
            id="invite-current_password"
            type="password"
            autoComplete="current-password"
            value={form.current_password}
            onChange={set("current_password")}
            {...err("current_password")}
          />
        </FormField>
        {/* Enter submits from any field. */}
        <button type="submit" hidden aria-hidden="true" tabIndex={-1} />
      </form>
    </ConfirmDialog>
  );
}

export function RevokeRoleDialog({ admin, onClose, onDone }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async () => {
    if (!password) return setError("Enter your password to confirm.");
    setBusy(true);
    setError("");
    try {
      await revokeAdminRole(admin.id, password);
      onDone(`${admin.name} is no longer an administrator.`);
    } catch (err) {
      setError(getErrorMessage(err, "Could not remove the administrator role"));
      setBusy(false);
    }
  };
  return (
    <ConfirmDialog
      title="Remove administrator role?"
      confirmLabel="Remove role"
      danger
      busy={busy}
      error={error}
      onConfirm={submit}
      onCancel={onClose}
    >
      <p>
        {admin.name} ({admin.email}) will lose administrator access immediately. Their account and any other roles stay.
      </p>
      <label>
        Your password
        <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
    </ConfirmDialog>
  );
}

/**
 * Pending administrator invitations (D87) with resend / revoke, and the
 * Invite Administrator dialog. Shown on Users to holders of
 * admin_invitation:manage; every action is enforced again by the API.
 * `inviting` / `onInviteClose` let the page open the dialog (Add User >
 * Administrator); `refreshKey` reloads after an invitation is sent there.
 */
export default function AdministratorAccess({ inviting = false, onInviteClose = () => {}, onNotice = () => {} }) {
  const [invitations, setInvitations] = useState(null);
  const [showClosed, setShowClosed] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [revoking, setRevoking] = useState(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    listInvitations(showClosed)
      .then((res) => {
        if (!live) return;
        setInvitations(res.data);
        setLoadError("");
      })
      .catch((err) => live && setLoadError(getErrorMessage(err, "Could not load invitations")));
    return () => {
      live = false;
    };
  }, [showClosed, attempt]);

  const reload = () => setAttempt((n) => n + 1);
  const act = async (action, message) => {
    setError("");
    setBusy(true);
    try {
      const res = await action();
      setRevoking(null);
      onNotice(typeof message === "function" ? message(res.data) : message);
      reload();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const pending = invitations?.filter((i) => i.status === "pending").length ?? 0;
  return (
    <section className="card admin-access" aria-label="Administrator invitations">
      <div className="section-head">
        <MailPlus className="icon" size={20} aria-hidden="true" />
        <h3>Administrator Invitations{pending ? ` (${pending} pending)` : ""}</h3>
        <label className="checkbox-inline">
          <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
          Show accepted and revoked
        </label>
      </div>
      {!revoking && <Alert>{error}</Alert>}
      {loadError ? (
        <div role="alert" className="appt-error">
          <p>{loadError}</p>
          <button type="button" className="secondary" onClick={reload}>
            Try again
          </button>
        </div>
      ) : invitations === null ? (
        <p role="status">Loading invitations…</p>
      ) : invitations.length === 0 ? (
        <p className="muted">No invitations. Add User &gt; Administrator sends one.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Invited by</th>
                <th>Status</th>
                <th>Expires</th>
                <th>Email delivery</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {invitations.map((i) => {
                const status = INVITATION_STATUS[i.status];
                const open = i.status === "pending" || i.status === "expired";
                return (
                  <tr key={i.id}>
                    <td>
                      {i.email}
                      {i.name && <div className="muted">{i.name}</div>}
                    </td>
                    <td>{i.invited_by_name ?? "—"}</td>
                    <td>
                      <span className={`badge ${status.tone}`}>{status.label}</span>
                    </td>
                    <td>{formatDateTime(i.expires_at)}</td>
                    <td>{deliveryLabel(i.delivery_status)}</td>
                    <td className="row">
                      {open && (
                        <>
                          <button type="button" className="secondary small-button" disabled={busy}
                            aria-label={`Resend invitation to ${i.email}`}
                            onClick={() => act(() => resendInvitation(i.id), inviteNotice)}>
                            Resend
                          </button>
                          <button type="button" className="danger small-button" disabled={busy}
                            aria-label={`Revoke invitation to ${i.email}`}
                            onClick={() => {
                              setError("");
                              setRevoking(i);
                            }}>
                            Revoke
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {inviting && (
        <InviteDialog
          onClose={onInviteClose}
          onInvited={(invitation) => {
            onInviteClose();
            onNotice(inviteNotice(invitation));
            reload();
          }}
        />
      )}
      {revoking && (
        <ConfirmDialog
          title="Revoke invitation?"
          confirmLabel="Revoke invitation"
          danger
          busy={busy}
          error={error}
          onConfirm={() => act(() => revokeInvitation(revoking.id), `The invitation to ${revoking.email} was revoked.`)}
          onCancel={() => setRevoking(null)}
        >
          <p>The link sent to {revoking.email} will stop working.</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
