import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Alert from "../components/Alert";
import { useAuth } from "../context/useAuth";
import { HOME_PATH } from "../routes/navigation";
import { completeGoogleSignIn } from "../services/googleAuthService";

/**
 * Back from Google with a known account (D123). This same-site request trades
 * the backend's short, single-use handoff cookie for the normal session (the
 * Strict refresh cookie and an access token); no token is ever in the URL.
 */
export default function GoogleComplete() {
  const { signInWithToken } = useAuth();
  const navigate = useNavigate();
  const [failed, setFailed] = useState(false);
  const started = useRef(false); // once, although development mode runs effects twice

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    completeGoogleSignIn()
      .then((res) => signInWithToken(res.data.access_token))
      .then(() => navigate(HOME_PATH, { replace: true }))
      .catch(() => setFailed(true));
  }, [signInWithToken, navigate]);

  if (failed) {
    return (
      <>
        <h2 className="auth-title">Sign-in didn&apos;t finish</h2>
        <Alert kind="warn">That Google sign-in expired or was already used. Please try again.</Alert>
        <p className="auth-footer">
          <Link to="/login">Back to sign in</Link>
        </p>
      </>
    );
  }
  return (
    <p className="muted" role="status">
      Signing you in…
    </p>
  );
}
