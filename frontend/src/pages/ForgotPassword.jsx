import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";

/**
 * Online password reset is not built yet (it needs email delivery). This page
 * says so plainly instead of imitating a reset flow. When the backend gains a
 * reset endpoint, the request form goes here.
 */
export default function ForgotPassword() {
  return (
    <>
      <h2 className="auth-title">Forgot your password?</h2>
      <p className="auth-subtitle">Online password reset is not available yet.</p>
      <p>
        Please contact the clinic reception or your administrator. After confirming your identity, they can set a new
        password for your account.
      </p>
      <p className="auth-footer">
        <Link to="/login" className="link-more">
          <ArrowLeft size={15} aria-hidden="true" /> Back to sign in
        </Link>
      </p>
    </>
  );
}
