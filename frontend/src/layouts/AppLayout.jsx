import { LifeBuoy, LogOut, Menu, Search, Settings } from "lucide-react";
import { Suspense, useState } from "react";
import PageFallback from "../components/PageFallback";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import BrandMark from "../components/BrandMark";
import ErrorBoundary from "../components/ErrorBoundary";
import ClinicAssistant from "../components/assistant/ClinicAssistant";
import AccountMenu from "../components/layout/AccountMenu";
import GlobalSearch from "../components/layout/GlobalSearch";
import NavGroup from "../components/layout/NavGroup";
import NotificationBell from "../components/layout/NotificationBell";
import { useAuth } from "../context/useAuth";
import { isAdmin, visibleNavItems } from "../routes/navigation";
import { pageLoaderFor } from "../routes/pages";

// The application shell: sidebar navigation, top bar, page content.
export default function AppLayout() {
  const { user, can, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [navOpen, setNavOpen] = useState(false);
  const [query, setQuery] = useState("");
  // Pointing at, focusing or touching an in-app link starts downloading that
  // page's code (never its data), so the click rarely waits for it. Failures
  // are ignored here; the navigation itself retries and reports them.
  const onNavIntent = (event) => {
    const link = event.target.closest?.("a[href]");
    if (!link || link.origin !== window.location.origin) return;
    pageLoaderFor(link.pathname, can)?.().catch(() => {});
  };

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
    <div className={`shell${navOpen ? " nav-open" : ""}`} onPointerOver={onNavIntent} onFocus={onNavIntent} onTouchStart={onNavIntent}>
      <aside className="sidebar" aria-label="Main navigation">
        <Link to={user ? (admin ? "/admin" : "/dashboard") : "/doctors"} className="brand">
          <BrandMark />
          Clinic AI Assistant
        </Link>
        {/* On small screens the sidebar is a drawer: any click inside closes it. */}
        <nav onClick={() => setNavOpen(false)}>
          {items.map((item) => {
            const { to, label, icon: Icon, end, children } = item;
            if (children) return <NavGroup key={`group-${to}`} item={item} />;
            return (
              <NavLink key={to} to={to} end={end}>
                <Icon size={19} aria-hidden="true" />
                {label}
              </NavLink>
            );
          })}
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
                name="clinic-doctor-search"
                autoComplete="off"
                spellCheck={false}
                enterKeyHint="search"
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
            <Suspense fallback={<PageFallback />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
      {/* One assistant for the whole signed-in app (D96); outside the page boundary so a page error never removes it. */}
      {user && <ClinicAssistant />}
    </div>
  );
}
