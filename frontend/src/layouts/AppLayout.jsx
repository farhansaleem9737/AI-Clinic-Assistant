import { LifeBuoy, LogOut, Menu, Search, Settings } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import BrandMark from "../components/BrandMark";
import ErrorBoundary from "../components/ErrorBoundary";
import ClinicAssistant from "../components/assistant/ClinicAssistant";
import AccountMenu from "../components/layout/AccountMenu";
import GlobalSearch from "../components/layout/GlobalSearch";
import NotificationBell from "../components/layout/NotificationBell";
import { useAuth } from "../context/useAuth";
import { isAdmin, visibleNavItems } from "../routes/navigation";

// The application shell: sidebar navigation, top bar, page content.
export default function AppLayout() {
  const { user, can, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [navOpen, setNavOpen] = useState(false);
  const [query, setQuery] = useState("");

  // Menu visibility is cosmetic; the API enforces every permission.
  const items = visibleNavItems(user, can);
  const admin = Boolean(user) && isAdmin(can);

  // Ends the server session (revokes the refresh token) before leaving.
  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  // Visitors search the doctor directory (names, specialties, departments).
  const handleSearch = (e) => {
    e.preventDefault();
    navigate(`/doctors${query.trim() ? `?q=${encodeURIComponent(query.trim())}` : ""}`);
  };

  return (
    <div className={`shell${navOpen ? " nav-open" : ""}`}>
      <aside className="sidebar" aria-label="Main navigation">
        <Link to={user ? (admin ? "/admin" : "/dashboard") : "/doctors"} className="brand">
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
            {admin && can("settings:manage") ? (
              <NavLink to="/admin/settings">
                <Settings size={19} aria-hidden="true" />
                Settings
              </NavLink>
            ) : (
              <NavLink to="/help">
                <LifeBuoy size={19} aria-hidden="true" />
                Help &amp; Support
              </NavLink>
            )}
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
          {user ? (
            <GlobalSearch />
          ) : (
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
          )}
          <span className="spacer" />
          {user ? (
            <>
              <NotificationBell />
              <AccountMenu onLogout={handleLogout} />
            </>
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
          {/* A page that fails to render never blanks the shell; a new route clears it. */}
          <ErrorBoundary resetKey={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      {/* One assistant for the whole signed-in app (D96); outside the page boundary so a page error never removes it. */}
      {user && <ClinicAssistant />}
    </div>
  );
}
