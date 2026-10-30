import { ArrowRight, RotateCw } from "lucide-react";
import { Link } from "react-router-dom";
import Alert from "./Alert";

/**
 * A titled dashboard card that also owns the loading and error states of the
 * data shown inside it, so every section behaves the same way. With `onRetry`,
 * a failed load offers "Try again" (an error is never shown as "nothing here").
 */
export default function SectionCard({ title, icon: Icon, moreTo, moreLabel = "View all", loading, error, onRetry, className = "", children }) {
  return (
    <section className={`card ${className}`.trim()} aria-label={title}>
      <div className="section-head">
        {Icon && <Icon className="icon" size={20} aria-hidden="true" />}
        <h3>{title}</h3>
        {moreTo && (
          <Link className="link-more" to={moreTo}>
            {moreLabel} <ArrowRight size={15} aria-hidden="true" />
          </Link>
        )}
      </div>
      {error ? (
        <div className="section-error">
          <Alert>{error}</Alert>
          {onRetry && (
            <button type="button" className="button secondary small" onClick={onRetry}>
              <RotateCw size={15} aria-hidden="true" /> Try again
            </button>
          )}
        </div>
      ) : loading ? (
        <div role="status" aria-label={`Loading ${title}`}>
          <div className="skeleton" style={{ height: 56, marginBottom: 8 }} />
          <div className="skeleton" style={{ height: 56 }} />
        </div>
      ) : (
        children
      )}
    </section>
  );
}
