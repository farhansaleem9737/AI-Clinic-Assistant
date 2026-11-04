import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/useAuth";
import { canOpen } from "../routes/pages";

/**
 * Route guard. `permission` (optional) hides pages the user can't use.
 * This is UX only — the backend rejects the underlying API calls regardless.
 */
export default function ProtectedRoute({ children, permission, anyOf, allOf }) {
  const { user, initializing, can } = useAuth();
  const location = useLocation();

  if (initializing) return <p className="muted">Loading…</p>;
  // Remember the full address (with its query) so sign-in can return here,
  // e.g. to the booking page for the doctor that was chosen.
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;

  // The same rule decides which pages a link may preload (routes/pages.js).
  const allowed = canOpen({ permission, anyOf, allOf }, can);
  if (!allowed) return <Navigate to="/dashboard" replace />;

  return children;
}
