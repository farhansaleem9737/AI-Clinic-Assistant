import { Search } from "lucide-react";
import { Link, NavLink, Outlet } from "react-router-dom";
import BrandMark from "../components/BrandMark";

// Top-navigation layout for visitors who are not signed in (the directory
// pages). Signed-in users see the same pages inside the app shell instead.
export default function PublicLayout() {
  return (
    <div className="public">
      <header className="public-nav">
        <div className="public-nav-inner">
          <Link to="/doctors" className="public-brand">
            <BrandMark size={44} />
            Clinic AI Assistant
          </Link>
          <nav aria-label="Main">
            <NavLink to="/doctors">Doctors</NavLink>
            <NavLink to="/departments">Departments</NavLink>
          </nav>
          <span className="spacer" />
          <Link to="/doctors#search" className="icon-link" aria-label="Search doctors">
            <Search size={20} aria-hidden="true" />
          </Link>
          <Link to="/login">
            <button type="button" className="secondary">
              Sign in
            </button>
          </Link>
          <Link to="/register">
            <button type="button">Create account</button>
          </Link>
        </div>
      </header>
      <main className="public-page">
        <Outlet />
      </main>
    </div>
  );
}
