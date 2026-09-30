import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";

const TITLES = { terms: "Terms of Service", privacy: "Privacy Policy" };

/**
 * Where the clinic's Terms of Service and Privacy Policy will be shown.
 *
 * The clinic has not supplied these documents yet. Legal text must come from
 * the clinic (and its counsel), not be invented by the software, so this page
 * says so plainly. To publish a document, render its content here.
 */
export default function LegalDocument({ document }) {
  const title = TITLES[document];
  return (
    <>
      <h2 className="auth-title">{title}</h2>
      <p className="auth-subtitle">This document has not been published yet.</p>
      <p>
        The clinic&apos;s {title} is not available online at the moment. Please ask the clinic for a copy before you
        create an account.
      </p>
      <p className="auth-footer">
        <Link to="/register" className="link-more">
          <ArrowLeft size={15} aria-hidden="true" /> Back to create account
        </Link>
      </p>
    </>
  );
}
