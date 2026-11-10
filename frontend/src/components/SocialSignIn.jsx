import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { useFetch } from "../hooks/useFetch";
import { getSignInProviders, GOOGLE_MESSAGES, googleStartUrl } from "../services/googleAuthService";
import Alert from "./Alert";

function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.7 1.2 9.2 3.6l6.9-6.9C35.9 2.4 30.4 0 24 0 14.6 0 6.5 5.4 2.6 13.2l8 6.2C12.5 13.6 17.8 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.7 6c4.5-4.2 6.9-10.3 6.9-17.7z" />
      <path fill="#FBBC05" d="M10.6 28.6A14.5 14.5 0 0 1 9.8 24c0-1.6.3-3.1.8-4.6l-8-6.2A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.8l8-6.2z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.7-6c-2.1 1.4-4.9 2.3-8.2 2.3-6.2 0-11.5-4.1-13.4-9.9l-8 6.2C6.5 42.6 14.6 48 24 48z" />
    </svg>
  );
}

function MicrosoftLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 21 21" aria-hidden="true">
      <rect x="0" y="0" width="10" height="10" fill="#F25022" />
      <rect x="11" y="0" width="10" height="10" fill="#7FBA00" />
      <rect x="0" y="11" width="10" height="10" fill="#00A4EF" />
      <rect x="11" y="11" width="10" height="10" fill="#FFB900" />
    </svg>
  );
}

/**
 * Provider sign-in for the sign-in and create-account pages. Google works
 * when the clinic has configured it (D123): the button navigates to the
 * backend, which runs Google's OpenID Connect flow and returns to the app.
 * Microsoft is not built, so it stays visibly unavailable.
 *
 * `intent`: "login" or "register"; `remember`: the sign-in page's "Remember me".
 */
export default function SocialSignIn({ intent = "login", remember = false }) {
  const location = useLocation();
  const [leaving, setLeaving] = useState(false);
  const providers = useFetch(() => getSignInProviders(), [], { query: "auth/providers" });
  const google = Boolean(providers.data?.google);
  const reason = new URLSearchParams(location.search).get("google");
  const message = reason ? GOOGLE_MESSAGES[reason] : null;

  // Back from Google's page: the browser may restore this page as it was left.
  useEffect(() => {
    const restored = (e) => e.persisted && setLeaving(false);
    window.addEventListener("pageshow", restored);
    return () => window.removeEventListener("pageshow", restored);
  }, []);

  const continueWithGoogle = () => {
    if (leaving) return; // one navigation, however many clicks
    setLeaving(true);
    window.location.assign(googleStartUrl(intent, remember));
  };

  return (
    <>
      {message && (
        <div className="auth-provider-message" role={message.kind === "error" ? "alert" : "status"}>
          <Alert kind={message.kind}>{message.text}</Alert>
        </div>
      )}
      <div className="auth-divider">or</div>
      <div className="auth-providers">
        <button
          type="button"
          className="secondary"
          onClick={continueWithGoogle}
          disabled={!google || leaving}
          aria-busy={leaving}
          aria-describedby={google ? undefined : "sso-google-note"}
        >
          {leaving ? <span className="spinner" aria-hidden="true" /> : <GoogleLogo />}
          {leaving ? "Opening Google…" : intent === "register" ? "Sign up with Google" : "Continue with Google"}
        </button>
        <button type="button" className="secondary" disabled aria-describedby="sso-ms-note">
          <MicrosoftLogo /> Continue with Microsoft
        </button>
      </div>
      {!providers.loading && !google && (
        <p id="sso-google-note" className="muted small auth-note">
          Google sign-in is not set up for this clinic yet.
        </p>
      )}
      <p id="sso-ms-note" className="muted small auth-note">
        Microsoft sign-in is not available yet.
      </p>
    </>
  );
}
