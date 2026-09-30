import { Zap } from "lucide-react";
import { Link } from "react-router-dom";

// `actions`: [{ to, label, hint, icon }]. Every target is an existing page.
export default function QuickActions({ actions }) {
  return (
    <section className="card" aria-label="Quick Actions">
      <div className="section-head">
        <Zap className="icon" size={20} aria-hidden="true" />
        <h3>Quick Actions</h3>
      </div>
      <div className="quick-grid">
        {actions.map(({ to, label, hint, icon: Icon }) => (
          <Link key={to} to={to} className="quick-action">
            <Icon size={26} aria-hidden="true" />
            {label}
            <small>{hint}</small>
          </Link>
        ))}
      </div>
    </section>
  );
}
