import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/useAuth";

/**
 * Route guard. `permission` (optional) hides pages the user can't use.
 * This is UX only — the backend rejects the underlying API calls regardless.
 */
export default function ProtectedRoute({ children, permission, anyOf }) {
  const { user, initializing, can } = useAuth();
  const location = useLocation();

  if (initializing) return <p className="muted">Loading…</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;

  const allowed = permission ? can(permission) : anyOf ? anyOf.some(can) : true;
  if (!allowed) return <Navigate to="/dashboard" replace />;

  return children;
}
