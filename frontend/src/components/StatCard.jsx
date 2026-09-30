import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

export default function StatCard({ icon: Icon, tone = "blue", label, value, good, to, linkLabel = "View all", note }) {
  return (
    <div className="card stat-card">
      <div className={`tile ${tone}`}>
        <Icon size={28} aria-hidden="true" />
      </div>
      <div className="body">
        <div className="label">{label}</div>
        <div className={`value ${good ? "good" : ""}`}>{value ?? "—"}</div>
        <div className="foot">
          {to ? (
            <Link className="link-more" to={to}>
              {linkLabel} <ArrowRight size={14} aria-hidden="true" />
            </Link>
          ) : (
            note
          )}
        </div>
      </div>
    </div>
  );
}
