import { Briefcase, GraduationCap, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { yearRange } from "../../utils/doctors";

const SECTIONS = [
  { id: "about", label: "About" },
  { id: "experience", label: "Experience" },
  { id: "education", label: "Education" },
];

const sectionId = (id) => `profile-${id}`;

// Scroll to a section (instantly when the user prefers reduced motion) and
// move focus there so keyboard and screen-reader users land on it too.
function goTo(id) {
  const el = document.getElementById(sectionId(id));
  if (!el) return;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView?.({ behavior: reduce ? "auto" : "smooth", block: "start" });
  el.focus({ preventScroll: true });
}

function Section({ id, icon: Icon, title, children }) {
  return (
    <section
      id={sectionId(id)}
      data-section={id}
      className="card profile-section"
      aria-labelledby={`${sectionId(id)}-title`}
      tabIndex={-1}
    >
      <div className="profile-section-head">
        <Icon className="icon" size={24} aria-hidden="true" />
        <h2 id={`${sectionId(id)}-title`}>{title}</h2>
      </div>
      <div className="profile-section-body">{children}</div>
    </section>
  );
}

// The biography as written, one paragraph per blank-line-separated block.
// Rendered as text (never HTML), so nothing in it can run as markup.
function About({ doctor, name }) {
  const paragraphs = (doctor.bio ?? "")
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  return (
    <Section id="about" icon={UserRound} title={`About ${name}`}>
      {paragraphs.length ? (
        paragraphs.map((p, i) => (
          <p key={i} className="prose">
            {p}
          </p>
        ))
      ) : (
        <p className="muted">Professional biography has not been added yet.</p>
      )}
    </Section>
  );
}

function Timeline({ items }) {
  return (
    <ol className="career-timeline">
      {items.map((item, index) => (
        <li key={index}>
          <div className="career-entry">
            <div className="career-what">
              <h3>{item.heading}</h3>
              {item.place && <p className="career-place">{item.place}</p>}
              {item.description && <p className="career-desc prose">{item.description}</p>}
            </div>
            {item.years && <p className="career-years">{item.years}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function Experience({ doctor }) {
  const items = doctor.experience.map((e) => ({
    heading: e.title,
    place: [e.organization, e.location].filter(Boolean).join(", "),
    description: e.description,
    years: yearRange(e.start_year, e.end_year, { ongoing: "Present" }),
  }));
  return (
    <Section id="experience" icon={Briefcase} title="Experience">
      {items.length ? <Timeline items={items} /> : <p className="muted">Professional experience has not been added yet.</p>}
    </Section>
  );
}

function Education({ doctor }) {
  const items = doctor.education.map((e) => ({
    heading: e.field_of_study ? `${e.qualification} (${e.field_of_study})` : e.qualification,
    place: e.institution,
    years: yearRange(e.start_year, e.end_year),
  }));
  return (
    <Section id="education" icon={GraduationCap} title="Education">
      {items.length ? (
        <Timeline items={items} />
      ) : doctor.qualifications ? (
        <p>{doctor.qualifications}</p>
      ) : (
        <p className="muted">Education details have not been added yet.</p>
      )}
    </Section>
  );
}

/**
 * About, Experience and Education, all shown one under another, with a bar
 * of links that scroll to each. The link of the section being read is
 * highlighted as the page scrolls (where the browser supports it).
 */
export default function ProfileTabs({ doctor, name }) {
  const [active, setActive] = useState("about");

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        const top = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setActive(top.target.dataset.section);
      },
      // The band just below the sticky header counts as "being read".
      { rootMargin: "-90px 0px -55% 0px" }
    );
    for (const { id } of SECTIONS) {
      const el = document.getElementById(sectionId(id));
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <div className="profile-sections">
      <nav className="card profile-nav" aria-label="Profile sections">
        <ul>
          {SECTIONS.map(({ id, label }) => (
            <li key={id}>
              <a
                href={`#${sectionId(id)}`}
                className={active === id ? "active" : ""}
                aria-current={active === id ? "true" : undefined}
                onClick={(event) => {
                  event.preventDefault();
                  setActive(id);
                  goTo(id);
                }}
              >
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <About doctor={doctor} name={name} />
      <Experience doctor={doctor} />
      <Education doctor={doctor} />
    </div>
  );
}
