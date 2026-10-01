import { LifeBuoy, LogOut, Menu, Search } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import Avatar from "../components/Avatar";
import BrandMark from "../components/BrandMark";
import { useAuth } from "../context/useAuth";
import { profilePath, roleLabel, visibleNavItems } from "../routes/navigation";

// The application shell: sidebar navigation, top bar, page content.
export default function AppLayout() {
  const { user, can, logout } = useAuth();
  const navigate = useNavigate();
  const [navOpen, setNavOpen] = useState(false);
  const [query, setQuery] = useState("");

  // Menu visibility is cosmetic; the API enforces every permission.
  const items = visibleNavItems(user, can);
  const myProfile = user ? profilePath(user, can) : null;

  // Ends the server session (revokes the refresh token) before leaving.
  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  // The directory search matches doctor names, specialties and departments.
  const handleSearch = (e) => {
    e.preventDefault();
    navigate(`/doctors${query.trim() ? `?q=${encodeURIComponent(query.trim())}` : ""}`);
  };

  const userCard = user && (
    <>
      <Avatar name={user.name} role={user.doctor_id ? "doctor" : undefined} size={40} />
      <span className="who">
        <strong>{user.name}</strong>
        <span>{roleLabel(user.roles)}</span>
      </span>
    </>
  );

  return (
    <div className={`shell${navOpen ? " nav-open" : ""}`}>
      <aside className="sidebar" aria-label="Main navigation">
        <Link to={user ? "/dashboard" : "/doctors"} className="brand">
          <BrandMark />
          Clinic AI Assistant
        </Link>
        {/* On small screens the sidebar is a drawer: any click inside closes it. */}
        <nav onClick={() => setNavOpen(false)}>
          {items.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}>
              <Icon size={19} aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>
        {user && (
          <div className="sidebar-foot" onClick={() => setNavOpen(false)}>
            <NavLink to="/help">
              <LifeBuoy size={19} aria-hidden="true" />
              Help &amp; Support
            </NavLink>
            <button type="button" className="sidebar-logout" onClick={handleLogout}>
              <LogOut size={19} aria-hidden="true" />
              Logout
            </button>
          </div>
        )}
      </aside>
      <div className="backdrop" onClick={() => setNavOpen(false)} />

      <div className="shell-main">
        <header className="topbar">
          <button type="button" className="secondary menu-button" aria-label="Open menu" onClick={() => setNavOpen(true)}>
            <Menu size={18} />
          </button>
          <form className="search" role="search" onSubmit={handleSearch}>
            <Search size={18} aria-hidden="true" />
            <input
              type="search"
              aria-label="Search doctors"
              placeholder="Search doctors, specialties, departments…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </form>
          <span className="spacer" />
          {user ? (
            myProfile ? (
              <Link to={myProfile} className="topbar-user" aria-label={`${user.name}, ${roleLabel(user.roles)}: my profile`}>
                {userCard}
              </Link>
            ) : (
              <span className="topbar-user">{userCard}</span>
            )
          ) : (
            <div className="row">
              <Link to="/login" className="button secondary">
                Log in
              </Link>
              <Link to="/register" className="button">
                Register
              </Link>
            </div>
          )}
        </header>
        <main className="page">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
