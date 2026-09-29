import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/useAuth";
import { NAV_ITEMS } from "../routes/navigation";

export default function AppLayout() {
  const { user, can, logout } = useAuth();
  const navigate = useNavigate();

  // Menu visibility is cosmetic; the API enforces every permission.
  const items = NAV_ITEMS.filter((item) => {
    if (item.public) return true;
    if (!user) return false;
    if (item.permission) return can(item.permission);
    if (item.anyOf) return item.anyOf.some(can);
    return true;
  });

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <>
      <header className="app-header">
        <NavLink to={user ? "/dashboard" : "/"} className="brand">
          Clinic AI Assistant
        </NavLink>
        <nav>
          {items.map((item) => (
            <NavLink key={item.to} to={item.to}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        {user ? (
          <div className="row">
            <span className="who">
              {user.name} · {user.roles.join(", ") || "no role"}
            </span>
            <button className="secondary" onClick={handleLogout}>
              Log out
            </button>
          </div>
        ) : (
          <div className="row">
            <NavLink to="/login">Log in</NavLink>
            <NavLink to="/register">Register</NavLink>
          </div>
        )}
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  );
}
