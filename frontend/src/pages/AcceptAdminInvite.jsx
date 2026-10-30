import { ArrowLeft, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import Alert from "../components/Alert";
import FormField from "../components/FormField";
import PasswordInput from "../components/PasswordInput";
import { useAuth } from "../context/useAuth";
import { acceptInvitation, acceptInvitationAsSignedIn, previewInvitation } from "../services/adminService";
import { getErrorMessage } from "../services/api";

const CLOSED = {
  accepted: { title: "Invitation already used", text: "This invitation has already been accepted. Sign in to continue." },
  revoked: { title: "Invitation revoked", text: "This invitation was withdrawn. Ask an administrator for a new one." },
  expired: { title: "Invitation expired", text: "This invitation link has expired. Ask an administrator to resend it." },
  invalid: {
    title: "Invitation not valid",
    text: "This invitation link is not valid. Open the link from your email again, or ask an administrator for a new invitation.",
  },
};
const CLOSED_CODES = { INVITATION_USED: "accepted", INVITATION_REVOKED: "revoked", INVITATION_EXPIRED: "expired", INVITATION_INVALID: "invalid" };

// The token arrives in the URL fragment (#token=...), which browsers never
// send to a server or in a Referer header.
const tokenFrom = (hash) => new URLSearchParams(hash.replace(/^#/, "")).get("token");

function Closed({ kind }) {
  const { title, text } = CLOSED[kind];
  return (
    <>
      <h2 className="auth-title">{title}</h2>
      <p className="auth-subtitle">{text}</p>
      <p className="auth-footer">
        <Link to="/login" className="link-more">
          <ArrowLeft size={15} aria-hidden="true" /> Go to sign in
        </Link>
      </p>
    </>
  );
}

function NewAccountForm({ token, invitation, onAccepted, onClosed }) {
  const [form, setForm] = useState({ name: invitation.name ?? "", password: "", confirm: "" });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    const found = {};
    if (!form.name.trim()) found.name = "Enter your full name.";
    if (form.password.length < 8) found.password = "Use at least 8 characters.";
    else if (form.password.length > 128) found.password = "Use at most 128 characters.";
    if (form.confirm !== form.password) found.confirm = "The passwords do not match.";
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError("");
    try {
      await acceptInvitation({ token, name: form.name.trim(), password: form.password });
      await onAccepted(form.password);
    } catch (err) {
      const closed = CLOSED_CODES[err?.response?.data?.error?.code];
      if (closed) return onClosed(closed);
      setError(getErrorMessage(err, "Could not accept the invitation"));
      setBusy(false);
    }
  };

  const described = (field) => (errors[field] ? { invalid: true, describedBy: `accept-${field}-error` } : {});
  return (
    <form className="stack" noValidate onSubmit={submit}>
      <Alert>{error}</Alert>
      <FormField id="accept-email" label="Email">
        <input id="accept-email" value={invitation.email} readOnly />
      </FormField>
      <FormField id="accept-name" label="Full name" error={errors.name}>
        <input
          id="accept-name"
          autoComplete="name"
          value={form.name}
          onChange={set("name")}
          aria-invalid={errors.name ? true : undefined}
          aria-describedby={errors.name ? "accept-name-error" : undefined}
        />
      </FormField>
      <FormField id="accept-password" label="Password" error={errors.password}>
        <PasswordInput id="accept-password" autoComplete="new-password" value={form.password} onChange={set("password")} {...described("password")} />
      </FormField>
      <FormField id="accept-confirm" label="Confirm Password" error={errors.confirm}>
        <PasswordInput id="accept-confirm" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} {...described("confirm")} />
      </FormField>
      <button type="submit" className="large block" disabled={busy}>
        {busy ? "Accepting…" : "Accept Invitation"}
      </button>
    </form>
  );
}

function ExistingAccountForm({ token, invitation, onAccepted, onClosed }) {
  const { user, login, logout } = useAuth();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user && user.email !== invitation.email) {
    return (
      <div className="stack">
        <Alert kind="info">
          You are signed in as {user.email}. This invitation is for {invitation.email}. Sign out, then open the link again.
        </Alert>
        <button type="button" className="secondary" onClick={() => logout()}>
          Sign out
        </button>
      </div>
    );
  }

  const submit = async (e) => {
    e.preventDefault();
    if (!password) return setError("Enter your password.");
    setBusy(true);
    setError("");
    try {
      // Proves ownership: a session for exactly this email, and the password now.
      if (!user) await login(invitation.email, password);
      await acceptInvitationAsSignedIn(token, password);
      await onAccepted();
    } catch (err) {
      const closed = CLOSED_CODES[err?.response?.data?.error?.code];
      if (closed) return onClosed(closed);
      setError(getErrorMessage(err, "Could not accept the invitation"));
      setBusy(false);
    }
  };

  return (
    <form className="stack" noValidate onSubmit={submit}>
      <p>
        {invitation.email} already has an account. {user ? "Confirm" : "Sign in with"} your password to add administrator
        access to it. Your password and existing access stay as they are.
      </p>
      <Alert>{error}</Alert>
      <FormField id="accept-existing-password" label="Password">
        <PasswordInput id="accept-existing-password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </FormField>
      <button type="submit" className="large block" disabled={busy}>
        {busy ? "Accepting…" : "Accept Invitation"}
      </button>
    </form>
  );
}

/**
 * Accept an administrator invitation (D87). Public: reached from the emailed
 * link. A new account sets its password here; an existing account must sign
 * in as itself. The server decides everything; this page only asks.
 */
export default function AcceptAdminInvite() {
  const location = useLocation();
  const navigate = useNavigate();
  const { login, fetchCurrentUser } = useAuth();
  // Read once, then taken out of the address bar and history (below).
  const [token] = useState(() => tokenFrom(location.hash));
  const [state, setState] = useState(() => (token ? { kind: "loading" } : { kind: "closed", closed: "invalid" }));

  useEffect(() => {
    if (location.hash) navigate(location.pathname, { replace: true });
  }, [location.hash, location.pathname, navigate]);

  useEffect(() => {
    if (!token) return;
    let live = true;
    previewInvitation(token)
      .then((res) => {
        if (!live) return;
        const invitation = res.data;
        setState(invitation.status === "pending" ? { kind: "open", invitation } : { kind: "closed", closed: invitation.status });
      })
      .catch((err) => {
        if (!live) return;
        const closed = CLOSED_CODES[err?.response?.data?.error?.code];
        setState(closed ? { kind: "closed", closed } : { kind: "error", message: getErrorMessage(err, "Could not check the invitation") });
      });
    return () => {
      live = false;
    };
  }, [token]);

  const closeAs = (closed) => setState({ kind: "closed", closed });

  const acceptedNew = async (password) => {
    try {
      await login(state.invitation.email, password);
      navigate("/admin", { replace: true });
    } catch {
      navigate("/login", { replace: true, state: { notice: "Your administrator account is ready. Please sign in." } });
    }
  };
  const acceptedExisting = async () => {
    await fetchCurrentUser();
    navigate("/admin", { replace: true });
  };

  if (state.kind === "closed") return <Closed kind={state.closed} />;
  return (
    <>
      <h2 className="auth-title">
        <ShieldCheck size={28} aria-hidden="true" className="invite-title-icon" /> Administrator Invitation
      </h2>
      {state.kind === "loading" && (
        <p className="auth-subtitle" role="status">
          Checking your invitation…
        </p>
      )}
      {state.kind === "error" && <Alert>{state.message}</Alert>}
      {state.kind === "open" && (
        <>
          <p className="auth-subtitle">
            You have been invited to administer Clinic AI Assistant as <strong>{state.invitation.email}</strong>.
          </p>
          {state.invitation.account_exists ? (
            <ExistingAccountForm token={token} invitation={state.invitation} onAccepted={acceptedExisting} onClosed={closeAs} />
          ) : (
            <NewAccountForm token={token} invitation={state.invitation} onAccepted={acceptedNew} onClosed={closeAs} />
          )}
        </>
      )}
    </>
  );
}
