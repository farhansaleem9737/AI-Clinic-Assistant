import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import LegalMarkdown from "./legal/LegalMarkdown";
import privacyPolicy from "./legal/privacy-policy.md?raw";

const TITLES = { terms: "Terms of Service", privacy: "Privacy Policy", ai: "AI Disclaimer" };

/**
 * How the assistant behaves, as built (docs/AI_ASSISTANT.md). This describes
 * the software; it is not legal text and should be reviewed by the clinic.
 */
function AiDisclaimer() {
  return (
    <>
      <h2 className="auth-title">AI Disclaimer</h2>
      <p className="auth-subtitle">How the Clinic AI Assistant works and where its limits are.</p>
      <ul className="legal-list">
        <li>
          <strong>Not medical advice.</strong> The assistant gives general information and helps with clinic tasks. It
          does not diagnose, prescribe or replace a doctor.
        </li>
        <li>
          <strong>Emergencies.</strong> If you describe urgent symptoms, it shows emergency guidance instead of an answer.
          In an emergency, call your local emergency number.
        </li>
        <li>
          <strong>Your permissions only.</strong> It can only see and do what your own account can, using the
          clinic&apos;s data — not information it makes up.
        </li>
        <li>
          <strong>You confirm every change.</strong> Bookings, cancellations and moves are proposals until you press
          Confirm; the server checks them again before saving.
        </li>
        <li>
          <strong>Reports.</strong> Explanations of medical documents compare values only with the ranges printed on the
          report and may be incomplete. Discuss results with your doctor.
        </li>
        <li>
          <strong>Data and the AI provider.</strong> Messages are processed by an external language model (Google Gemini).
          Unless the clinic has an approved agreement for health data, patient records are not sent to it and personal
          identifiers in your messages are replaced first.
        </li>
        <li>
          <strong>It can be wrong.</strong> Check important details, such as dates and times, on the relevant page.
        </li>
      </ul>
      <p className="muted small">This page describes the software. The clinic should review it with its legal advisers.</p>
    </>
  );
}

/**
 * Where the clinic's Terms of Service and Privacy Policy will be shown.
 *
 * The clinic has not supplied these documents yet. Legal text must come from
 * the clinic (and its counsel), not be invented by the software, so this page
 * says so plainly. To publish a document, render its content here.
 */
export default function LegalDocument({ document }) {
  const title = TITLES[document];
  const back = document === "ai" ? (
    <Link to="/" className="link-more">
      <ArrowLeft size={15} aria-hidden="true" /> Back to home
    </Link>
  ) : (
    <Link to="/register" className="link-more">
      <ArrowLeft size={15} aria-hidden="true" /> Back to create account
    </Link>
  );
  return (
    <>
      {document === "ai" ? (
        <AiDisclaimer />
      ) : document === "privacy" ? (
        <LegalMarkdown source={privacyPolicy} />
      ) : (
        <>
          <h2 className="auth-title">{title}</h2>
          <p className="auth-subtitle">This document has not been published yet.</p>
          <p>
            The clinic&apos;s {title} is not available online at the moment. Please ask the clinic for a copy before you
            create an account.
          </p>
        </>
      )}
      <p className="auth-footer">{back}</p>
    </>
  );
}
