import { Link, Outlet } from "react-router-dom";
import hero from "../assets/login-hero.jpg";
import BrandMark from "../components/BrandMark";

/**
 * Full-screen layout for the signed-out pages: brand message and photo on the
 * left, the page's card on the right. On small screens only the card is shown.
 */
export default function AuthLayout() {
  return (
    <div className="auth">
      <aside className="auth-hero">
        <p className="eyebrow">Clinic AI Assistant</p>
        <h1>
          Better Care.
          <br />
          Smarter Tomorrow.
        </h1>
        <p className="lead">A modern healthcare management platform for patients, doctors and clinics.</p>
        {/* Decorative: it adds atmosphere, not information. */}
        <img src={hero} alt="" />
      </aside>
      <main className="auth-panel">
        <div className="auth-card">
          <Link to="/doctors" className="auth-brand" aria-label="Clinic AI Assistant home">
            <BrandMark size={56} />
            <span>
              Clinic AI
              <br />
              Assistant
            </span>
          </Link>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
