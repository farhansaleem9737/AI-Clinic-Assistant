import { ArrowRight, Building2 } from "lucide-react";
import { Link } from "react-router-dom";
import Alert from "../components/Alert";
import EmptyState from "../components/EmptyState";
import { useFetch } from "../hooks/useFetch";
import { getPublicDepartments } from "../services/departmentService";

// Public list of active departments; each links to its doctors.
export default function Departments() {
  const { data, loading, error } = useFetch(getPublicDepartments, []);
  const departments = data?.items ?? [];

  return (
    <div>
      <h2>Departments</h2>
      <Alert>{error}</Alert>
      {loading && <p className="muted">Loading…</p>}
      {!loading && !error && departments.length === 0 && (
        <div className="card">
          <EmptyState icon={Building2}>No departments are listed yet.</EmptyState>
        </div>
      )}
      <div className="grid">
        {departments.map((d) => (
          <div key={d.id} className="card" style={{ margin: 0 }}>
            <div className="section-head">
              <Building2 className="icon" size={20} aria-hidden="true" />
              <h3>{d.name}</h3>
            </div>
            <p className="muted small">{d.description ?? "No description."}</p>
            <Link className="link-more" to={`/doctors?department=${d.id}`}>
              View doctors <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </div>
        ))}
      </div>
    </div>
  );
}
