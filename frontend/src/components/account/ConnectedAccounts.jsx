import { Link2 } from "lucide-react";
import { useState } from "react";
import { useLocation } from "react-router-dom";
import { useFetch } from "../../hooks/useFetch";
import { getErrorMessage } from "../../services/api";
import { getGoogleIdentity, GOOGLE_MESSAGES, linkGoogle, unlinkGoogle } from "../../services/googleAuthService";
import Alert from "../Alert";
import FormField from "../FormField";
import PasswordInput from "../PasswordInput";

/**
 * Account › Connected accounts (D123): link or unlink Google. Both need a
 * recent sign-in, or the password; Google cannot be unlinked while it is the
 * account's only way to sign in. Linking happens on Google's page and comes
 * back here with ?google=linked (or the reason it did not).
 */
export default function ConnectedAccounts() {
  const location = useLocation();
  const [attempt, setAttempt] = useState(0);
  const status = useFetch(() => getGoogleIdentity(), [], { refresh: attempt, errorMessage: "Connected accounts could not be loaded." });
  const [action, setAction] = useState(null); // "link" | "unlink" while asking for the password
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const reason = new URLSearchParams(location.search).get("google");
  const message = reason ? GOOGLE_MESSAGES[reason] : null;
  const google = status.data;

  const run = async (kind) => {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (kind === "link") {
        const res = await linkGoogle(action === "link" ? password : null);
        window.location.assign(res.data.authorize_url); // on to Google
        return;
      }
      await unlinkGoogle(action === "unlink" ? password : null);
      setAction(null);
      setPassword("");
      setNotice("Google is no longer linked. Sign in with your email and password.");
      setAttempt((n) => n + 1);
    } catch (err) {
      const code = err.response?.data?.error?.code;
      if (code === "REAUTHENTICATION_REQUIRED") setAction(kind);
      else if (code === "INCORRECT_PASSWORD") setError("That password is incorrect.");
      else setError(getErrorMessage(err, "That didn't work. Please try again."));
    }
    setBusy(false);
  };

  let body;
  if (status.error) body = <Alert>{status.error}</Alert>;
  else if (!google) body = <p className="muted small" role="status">Loading…</p>;
  else if (!google.enabled && !google.linked) body = <p className="muted">Google sign-in is not set up for this clinic yet.</p>;
  else if (google.linked) {
    body = (
      <>
        <p>
          <strong>Google</strong> · connected as {google.email}
        </p>
        {google.has_password ? (
          <button type="button" className="secondary" onClick={() => run("unlink")} disabled={busy}>
            {busy && action !== "unlink" ? "Checking…" : "Unlink Google"}
          </button>
        ) : (
          <p className="muted small">
            Google is your only way to sign in. Set a password (account menu › Change password) before unlinking it.
          </p>
        )}
      </>
    );
  } else {
    body = (
      <>
        <p className="muted">Sign in with your Google account as well as your password.</p>
        <button type="button" onClick={() => run("link")} disabled={busy}>
          {busy && action !== "link" ? "Opening Google…" : "Link Google account"}
        </button>
      </>
    );
  }

  return (
    <section className="card connected-accounts" aria-labelledby="connected-title">
      <div className="card-title">
        <Link2 className="icon" size={22} aria-hidden="true" />
        <h2 id="connected-title">Connected accounts</h2>
      </div>
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {notice && <Alert kind="success">{notice}</Alert>}
      {body}
      {action && (
        <form
          className="connected-reauth"
          onSubmit={(e) => {
            e.preventDefault();
            run(action);
          }}
        >
          <FormField id="connected-password" label="Your password (for your security)">
            <PasswordInput
              id="connected-password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </FormField>
          <button type="submit" disabled={busy || !password}>
            {action === "link" ? "Continue to Google" : "Unlink Google"}
          </button>
        </form>
      )}
      <Alert>{error}</Alert>
    </section>
  );
}
