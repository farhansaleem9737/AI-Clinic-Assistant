import { SearchX } from "lucide-react";
import { Link } from "react-router-dom";
import EmptyState from "../components/EmptyState";

// Shown for unknown routes and for records that do not exist (or are not public).
export default function NotFound({ message = "We could not find that page.", backTo = "/doctors", backLabel = "Find a doctor" }) {
  return (
    <div className="card not-found">
      <h1>Page not found</h1>
      <EmptyState
        icon={SearchX}
        action={
          <Link to={backTo} className="button secondary">
            {backLabel}
          </Link>
        }
      >
        {message}
      </EmptyState>
    </div>
  );
}
