import { ChevronRight, LogOut, Menu, Plus, Search } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import Avatar from "../components/Avatar";
import { useAuth } from "../context/useAuth";
import { profilePath, visibleNavItems } from "../routes/navigation";

// The application shell: sidebar navigation, top bar, page content.
export default function AppLayout() {
  const { user, can, logout } = useAuth();
  const navigate = useNavigate();
  const [navOpen, setNavOpen] = useState(false);
  const [query, setQuery] = useState("");

  // Menu visibility is cosmetic; the API enforces every permission.
  const items = visibleNavItems(user, can);
  const myProfile = user ? profilePath(user, can) : null;
  const role = user?.roles.join(", ") || "no role";

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const handleSearch = (e) => {
    e.preventDefault();
    navigate(`/doctors${query.trim() ? `?q=${encodeURIComponent(query.trim())}` : ""}`);
  };

  const userCard = user && (
    <>
      <Avatar name={user.name} size={36} />
      <span className="who">
        <strong>{user.name}</strong>
        <span>{role}</span>
      </span>
    </>
  );

  return (
    <div className={`shell${navOpen ? " nav-open" : ""}`}>
      <aside className="sidebar" aria-label="Main navigation">
        <Link to={user ? "/dashboard" : "/doctors"} className="brand">
          <span className="brand-mark">
            <Plus size={22} strokeWidth={3} aria-hidden="true" />
          </span>
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
        {user &&
          (myProfile ? (
            <Link to={myProfile} className="sidebar-user">
              {userCard}
              <ChevronRight size={16} aria-hidden="true" />
            </Link>
          ) : (
            <div className="sidebar-user">{userCard}</div>
          ))}
        {user && (
          <button type="button" className="sidebar-logout" onClick={handleLogout}>
            <LogOut size={19} aria-hidden="true" />
            Logout
          </button>
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
              placeholder="Search doctors…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </form>
          <span className="spacer" />
          {user ? (
            myProfile ? (
              <Link to={myProfile} className="topbar-user">
                {userCard}
              </Link>
            ) : (
              <span className="topbar-user">{userCard}</span>
            )
          ) : (
            <div className="row">
              <Link to="/login">
                <button type="button" className="secondary">
                  Log in
                </button>
              </Link>
              <Link to="/register">
                <button type="button">Register</button>
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
