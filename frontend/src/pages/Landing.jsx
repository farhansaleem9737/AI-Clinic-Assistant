import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Check, CircleHelp, Mail, Menu, ShieldCheck, Sparkles, X } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import BrandMark from "../components/BrandMark";
import { useAuth } from "../context/useAuth";
import { HOME_PATH } from "../routes/navigation";
import { SUPPORT_EMAIL } from "../utils/support";
import Accordion from "./landing/Accordion";
import Architecture from "./landing/Architecture";
import HeroPreview from "./landing/HeroPreview";
import Showcase from "./landing/Showcase";
import { ACCESS_PLANS, FAQ, FEATURES, NAV_SECTIONS, ROLES, SECURITY, STEPS } from "./landing/content";
import "./landing/landing.css";

const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

// Smooth-scrolls to a section (the sticky header is allowed for by scroll-margin-top in CSS).
function scrollToSection(id) {
  const target = document.getElementById(id);
  if (!target) return;
  target.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
  window.history.replaceState(null, "", id === "home" ? window.location.pathname : `#${id}`);
}

// Which section is on screen, for the header's active link.
function useActiveSection() {
  const [active, setActive] = useState("home");
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return undefined;
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((entry) => entry.isIntersecting && setActive(entry.target.id)),
      { rootMargin: "-45% 0px -50% 0px" },
    );
    NAV_SECTIONS.forEach(({ id }) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, []);
  return active;
}

// Fades sections in as they scroll into view. Without IntersectionObserver
// (or with reduced motion) everything is simply shown.
function useReveal(root) {
  useEffect(() => {
    const items = root.current?.querySelectorAll(".lp-reveal") ?? [];
    if (typeof IntersectionObserver === "undefined" || reducedMotion()) {
      items.forEach((el) => el.classList.add("is-visible"));
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) =>
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }),
      { rootMargin: "0px 0px -8% 0px" },
    );
    items.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [root]);
}

function SectionLink({ id, children, className, onNavigate }) {
  return (
    <a
      href={`#${id}`}
      className={className}
      onClick={(event) => {
        event.preventDefault();
        onNavigate?.();
        scrollToSection(id);
      }}
    >
      {children}
    </a>
  );
}

function Header() {
  const { user } = useAuth();
  const active = useActiveSection();
  const [open, setOpen] = useState(false);
  const menuButton = useRef(null);
  const drawer = useRef(null);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") {
        setOpen(false);
        menuButton.current?.focus();
      }
    };
    const onPointer = (event) => {
      if (!drawer.current?.contains(event.target) && !menuButton.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  const actions = user ? (
    <Link to={HOME_PATH} className="lp-btn primary">
      Open dashboard <ArrowRight size={16} aria-hidden="true" />
    </Link>
  ) : (
    <>
      <Link to="/login" className="lp-btn outline">
        Sign In
      </Link>
      <Link to="/register" className="lp-btn primary">
        Get Started <ArrowRight size={16} aria-hidden="true" />
      </Link>
    </>
  );

  return (
    <header className="lp-header">
      <div className="lp-header-inner">
        <SectionLink id="home" className="lp-brand" onNavigate={close}>
          <BrandMark size={36} />
          <span>Clinic AI Assistant</span>
        </SectionLink>
        <nav aria-label="Main" className="lp-nav">
          {NAV_SECTIONS.map(({ id, label }) => (
            <SectionLink key={id} id={id} className={active === id ? "active" : undefined}>
              {label}
              {active === id && <span className="sr-only"> (current section)</span>}
            </SectionLink>
          ))}
        </nav>
        <div className="lp-header-actions">{actions}</div>
        <button
          ref={menuButton}
          type="button"
          className="lp-menu-button"
          aria-expanded={open}
          aria-controls="lp-drawer"
          aria-label={open ? "Close menu" : "Open menu"}
          onClick={() => setOpen(!open)}
        >
          {open ? <X size={22} aria-hidden="true" /> : <Menu size={22} aria-hidden="true" />}
        </button>
      </div>
      <div id="lp-drawer" ref={drawer} className={open ? "lp-drawer open" : "lp-drawer"} hidden={!open}>
        <nav aria-label="Mobile">
          {NAV_SECTIONS.map(({ id, label }) => (
            <SectionLink key={id} id={id} className={active === id ? "active" : undefined} onNavigate={close}>
              {label}
            </SectionLink>
          ))}
        </nav>
        <div className="lp-drawer-actions">{actions}</div>
      </div>
    </header>
  );
}

function SectionHead({ eyebrow, title, text, id }) {
  return (
    <div className="lp-section-head lp-reveal">
      <span className="lp-eyebrow">{eyebrow}</span>
      <h2 id={id}>{title}</h2>
      {text && <p>{text}</p>}
    </div>
  );
}

function FeatureLink({ link }) {
  const content = (
    <>
      {link.label} <ArrowRight size={15} aria-hidden="true" />
    </>
  );
  return link.href ? (
    <SectionLink id={link.href.slice(1)} className="lp-more">
      {content}
    </SectionLink>
  ) : (
    <Link to={link.to} className="lp-more">
      {content}
    </Link>
  );
}

function Footer() {
  return (
    <footer className="lp-footer">
      <div className="lp-container lp-footer-grid">
        <div className="lp-footer-brand">
          <span className="lp-brand">
            <BrandMark size={32} />
            <span>Clinic AI Assistant</span>
          </span>
          <p>Appointments, patients, schedules and documents in one role-based clinic platform, with an AI assistant that works on your behalf.</p>
          {SUPPORT_EMAIL && (
            <a href={`mailto:${SUPPORT_EMAIL}`} className="lp-footer-mail">
              <Mail size={15} aria-hidden="true" /> {SUPPORT_EMAIL}
            </a>
          )}
        </div>
        <nav aria-labelledby="lp-foot-product">
          <h3 id="lp-foot-product">Product</h3>
          {NAV_SECTIONS.slice(1).map(({ id, label }) => (
            <SectionLink key={id} id={id}>
              {label}
            </SectionLink>
          ))}
        </nav>
        <nav aria-labelledby="lp-foot-platform">
          <h3 id="lp-foot-platform">Platform</h3>
          <Link to="/doctors">Doctor Directory</Link>
          <Link to="/departments">Departments</Link>
          <Link to="/login">Sign In</Link>
          <Link to="/register">Create Account</Link>
        </nav>
        <nav aria-labelledby="lp-foot-legal">
          <h3 id="lp-foot-legal">Legal</h3>
          <Link to="/privacy">Privacy Policy</Link>
          <Link to="/terms">Terms of Service</Link>
          <Link to="/ai-disclaimer">AI Disclaimer</Link>
        </nav>
      </div>
      <div className="lp-container lp-footer-base">
        <span>© {new Date().getFullYear()} Clinic AI Assistant</span>
        <span>General information only — not a substitute for professional medical advice.</span>
      </div>
    </footer>
  );
}

/**
 * The public home page. Everything shown is either a real link into the app
 * or clearly marked demo content; visitors never call protected endpoints.
 */
export default function Landing() {
  const root = useRef(null);
  const { hash } = useLocation();
  useReveal(root);

  useEffect(() => {
    document.title = "Clinic AI Assistant — Smarter clinic management, powered by AI";
    return () => {
      document.title = "Clinic AI Assistant";
    };
  }, []);

  // Arriving at "/#security" (e.g. from another page) lands on that section.
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView();
  }, [hash]);

  return (
    <div className="lp" ref={root}>
      <a href="#main" className="lp-skip">
        Skip to content
      </a>
      <Header />
      <main id="main">
        <section id="home" className="lp-hero" aria-labelledby="lp-hero-title">
          <div className="lp-container lp-hero-grid">
            <div className="lp-hero-copy">
              <span className="lp-badge">
                <Sparkles size={15} aria-hidden="true" /> AI-powered clinic platform
              </span>
              <h1 id="lp-hero-title">
                Smarter Clinic Management, <span className="lp-accent">Powered by AI</span>
              </h1>
              <p className="lp-lead">
                Manage appointments, patients, medical documents, and clinic operations in one secure, role-based
                platform—with an AI assistant designed to simplify everyday workflows.
              </p>
              <div className="lp-hero-ctas">
                <Link to="/register" className="lp-btn primary lg">
                  Get Started <ArrowRight size={18} aria-hidden="true" />
                </Link>
                <SectionLink id="features" className="lp-btn outline lg">
                  Explore Features
                </SectionLink>
              </div>
              <ul className="lp-checks">
                {["AI-assisted appointment management", "Role-based clinic workflows", "Medical document intelligence"].map((item) => (
                  <li key={item}>
                    <Check size={14} aria-hidden="true" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            <HeroPreview />
          </div>
        </section>

        <section id="features" className="lp-section" aria-labelledby="lp-features-title">
          <div className="lp-container">
            <SectionHead
              id="lp-features-title"
              eyebrow="Features"
              title="Everything a clinic runs on, in one place"
              text="Built around real clinic workflows — and only what the platform does today."
            />
            <div className="lp-feature-grid">
              {FEATURES.map(({ icon: Icon, tone, title, text, points, link }) => (
                <article key={title} className="lp-card lp-feature lp-reveal">
                  <span className={`lp-tile tone-${tone}`}>
                    <Icon size={22} aria-hidden="true" />
                  </span>
                  <h3>{title}</h3>
                  <p>{text}</p>
                  <ul className="lp-points">
                    {points.map((point) => (
                      <li key={point}>
                        <Check size={14} aria-hidden="true" /> {point}
                      </li>
                    ))}
                  </ul>
                  <FeatureLink link={link} />
                </article>
              ))}
            </div>

            <div className="lp-roles lp-reveal">
              <h3>Four roles, one platform</h3>
              <div className="lp-role-grid">
                {ROLES.map(({ role, icon: Icon, items }) => (
                  <div key={role} className="lp-role">
                    <h4>
                      <Icon size={17} aria-hidden="true" /> {role}
                    </h4>
                    <ul>
                      {items.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="lp-section lp-alt" aria-labelledby="lp-steps-title">
          <div className="lp-container">
            <SectionHead id="lp-steps-title" eyebrow="How it works" title="From sign-up to a smoother clinic day" />
            <ol className="lp-steps">
              {STEPS.map(({ title, text }, i) => (
                <li key={title} className="lp-step lp-reveal">
                  <span className="lp-step-num" aria-hidden="true">
                    {i + 1}
                  </span>
                  <h3>{title}</h3>
                  <p>{text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="architecture" className="lp-section" aria-labelledby="lp-arch-title">
          <div className="lp-container">
            <SectionHead
              id="lp-arch-title"
              eyebrow="Architecture"
              title="Built on a Modern, Scalable Architecture"
              text="Explore how the frontend, backend, database, storage, and AI services work together to power clinic operations."
            />
            <div className="lp-reveal">
              <Architecture />
            </div>
          </div>
        </section>

        <section id="showcase" className="lp-section lp-alt" aria-labelledby="lp-show-title">
          <div className="lp-container">
            <SectionHead id="lp-show-title" eyebrow="Product tour" title="A workspace for every role" text="Previews use made-up demo data." />
            <div className="lp-reveal">
              <Showcase />
            </div>
          </div>
        </section>

        <section id="security" className="lp-section lp-security" aria-labelledby="lp-security-title">
          <div className="lp-container">
            <SectionHead
              id="lp-security-title"
              eyebrow="Security"
              title="Security and Privacy by Design"
              text="How access, sessions, files and the AI assistant are protected — in plain language, with the technical detail one click away."
            />
            <div className="lp-security-grid">
              {SECURITY.map(({ icon: Icon, title, text, details }) => (
                <article key={title} className="lp-card lp-sec-card lp-reveal">
                  <span className="lp-tile tone-navy">
                    <Icon size={20} aria-hidden="true" />
                  </span>
                  <p className="lp-sec-text">{text}</p>
                  <Accordion title={title}>
                    <p>{details}</p>
                  </Accordion>
                </article>
              ))}
            </div>
            <p className="lp-note lp-reveal">
              <ShieldCheck size={16} aria-hidden="true" /> We do not claim HIPAA, GDPR, ISO 27001, SOC 2 or any other
              certification. Read the <Link to="/privacy">Privacy Policy</Link> and the{" "}
              <Link to="/ai-disclaimer">AI Disclaimer</Link>.
            </p>
          </div>
        </section>

        <section id="pricing" className="lp-section lp-alt" aria-labelledby="lp-pricing-title">
          <div className="lp-container">
            <SectionHead
              id="lp-pricing-title"
              eyebrow="Pricing"
              title="How to get access"
              text="Commercial plans have not been published yet, and no payment is taken in the app. Here is how each kind of account is created today."
            />
            <div className="lp-plan-grid">
              {ACCESS_PLANS.map(({ name, price, text, items, action, featured }) => (
                <article key={name} className={featured ? "lp-card lp-plan featured lp-reveal" : "lp-card lp-plan lp-reveal"}>
                  <h3>{name}</h3>
                  <p className="lp-plan-price">{price}</p>
                  <p>{text}</p>
                  <ul className="lp-points">
                    {items.map((item) => (
                      <li key={item}>
                        <Check size={14} aria-hidden="true" /> {item}
                      </li>
                    ))}
                  </ul>
                  <Link to={action.to} className={featured ? "lp-btn primary block" : "lp-btn outline block"}>
                    {action.label}
                  </Link>
                </article>
              ))}
            </div>
            {SUPPORT_EMAIL && (
              <p className="lp-note lp-reveal">
                <Mail size={16} aria-hidden="true" /> Running a clinic and interested in the platform?{" "}
                <a href={`mailto:${SUPPORT_EMAIL}?subject=Clinic%20AI%20Assistant%20enquiry`}>Contact us</a>.
              </p>
            )}
          </div>
        </section>

        <section className="lp-section" aria-labelledby="lp-faq-title">
          <div className="lp-container lp-faq">
            <SectionHead id="lp-faq-title" eyebrow="FAQ" title="Frequently asked questions" />
            <div className="lp-faq-list lp-reveal">
              {FAQ.map(([question, answer]) => (
                <Accordion key={question} title={question} icon={CircleHelp}>
                  <p>{answer}</p>
                </Accordion>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-cta" aria-labelledby="lp-cta-title">
          <div className="lp-container lp-cta-inner lp-reveal">
            <div>
              <h2 id="lp-cta-title">Ready to see it for yourself?</h2>
              <p>Create an account in a minute, or browse the doctor directory first.</p>
            </div>
            <div className="lp-hero-ctas">
              <Link to="/register" className="lp-btn white lg">
                Get Started <ArrowRight size={18} aria-hidden="true" />
              </Link>
              <Link to="/doctors" className="lp-btn ghost lg">
                Browse doctors
              </Link>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
