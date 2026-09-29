import { useAuth } from "../context/useAuth";

export default function Dashboard() {
  const { user } = useAuth();

  return (
    <div className="card">
      <h2>Welcome, {user.name}</h2>
      <p className="muted">{user.email}</p>
      <p>
        Roles:{" "}
        {user.roles.length ? user.roles.map((r) => <span key={r} className="badge">{r}</span>) : "none"}
      </p>
    </div>
  );
}
