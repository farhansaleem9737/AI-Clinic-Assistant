import { CalendarDays, ShieldPlus, Users } from "lucide-react";
import { Link, Outlet } from "react-router-dom";
import loginHero from "../assets/login-hero.jpg";
import registerHero from "../assets/register-hero.jpg";
import BrandMark from "../components/BrandMark";

// What the brand panel says on each signed-out page.
const HEROES = {
  login: {
    title: ["Better Care.", "Smarter Tomorrow."],
    lead: "A modern healthcare management platform for patients, doctors and clinics.",
    image: loginHero,
  },
  register: {
    title: ["Your Health.", "Our Priority."],
    lead: "Connecting patients, doctors and clinics for a healthier tomorrow.",
    image: registerHero,
    benefits: [
      { icon: Users, title: "Trusted Doctors", text: "Find the right specialist" },
      { icon: CalendarDays, title: "Easy Appointments", text: "Book in minutes" },
      { icon: ShieldPlus, title: "Better Care", text: "For you and your family" },
    ],
  },
};

/**
 * Full-screen layout for the signed-out pages: brand message and photo on the
 * left, the page's card on the right. On small screens only the card is shown.
 */
export default function AuthLayout({ variant = "login" }) {
  const hero = HEROES[variant];
  return (
    <div className={`auth auth-${variant}`}>
      <aside className={`auth-hero auth-hero-${variant}`}>
        {/* Decorative: it adds atmosphere, not information. */}
        <img src={hero.image} alt="" />
        <div className="auth-hero-text">
          <p className="eyebrow">Clinic AI Assistant</p>
          <h1>
            {hero.title[0]}
            <br />
            {hero.title[1]}
          </h1>
          <p className="lead">{hero.lead}</p>
          {hero.benefits && (
            <ul className="auth-benefits">
              {hero.benefits.map(({ icon: Icon, title, text }) => (
                <li key={title}>
                  <span className="tile">
                    <Icon size={20} aria-hidden="true" />
                  </span>
                  <span>
                    <strong>{title}</strong>
                    <small>{text}</small>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
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
