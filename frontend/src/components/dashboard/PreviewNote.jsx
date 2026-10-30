import { Link } from "react-router-dom";

/**
 * Says when a dashboard list is a preview: "Showing 5 of 12 … View all".
 * Renders nothing when every record is already on screen, so a capped list
 * never drops records silently.
 */
export default function PreviewNote({ shown, total, noun = "appointments", to }) {
  if (!total || total <= shown) return null;
  return (
    <p className="preview-note muted small">
      Showing {shown} of {total} {noun}. <Link to={to}>View all</Link>
    </p>
  );
}
