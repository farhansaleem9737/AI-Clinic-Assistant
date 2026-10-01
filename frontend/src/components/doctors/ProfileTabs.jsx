import { useRef, useState } from "react";
import { yearRange } from "../../utils/doctors";

const TABS = [
  { id: "about", label: "About" },
  { id: "experience", label: "Experience" },
  { id: "education", label: "Education" },
];

function About({ doctor, name }) {
  return (
    <>
      <h2>About {name}</h2>
      {doctor.bio ? <p className="prose">{doctor.bio}</p> : <p className="muted">{name} has not added a biography yet.</p>}
    </>
  );
}

function Experience({ doctor }) {
  return (
    <>
      <h2>Experience</h2>
      {doctor.experience.length === 0 ? (
        <p className="muted">No work history has been added yet.</p>
      ) : (
        <ol className="timeline">
          {doctor.experience.map((e, index) => (
            <li key={index}>
              <h3>{e.title}</h3>
              <p>{[e.organization, e.location].filter(Boolean).join(", ")}</p>
              <p className="muted small">{yearRange(e.start_year, e.end_year, { ongoing: "Present" })}</p>
              {e.description && <p className="prose">{e.description}</p>}
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

function Education({ doctor }) {
  return (
    <>
      <h2>Education</h2>
      {doctor.education.length > 0 ? (
        <ol className="timeline">
          {doctor.education.map((e, index) => {
            const years = yearRange(e.start_year, e.end_year);
            return (
              <li key={index}>
                <h3>
                  {e.qualification}
                  {e.field_of_study && ` (${e.field_of_study})`}
                </h3>
                <p>{e.institution}</p>
                {years && <p className="muted small">{years}</p>}
              </li>
            );
          })}
        </ol>
      ) : doctor.qualifications ? (
        <p>{doctor.qualifications}</p>
      ) : (
        <p className="muted">No education has been added yet.</p>
      )}
    </>
  );
}

const PANELS = { about: About, experience: Experience, education: Education };

/** About / Experience / Education, as keyboard-operable tabs (arrow keys, Home, End). */
export default function ProfileTabs({ doctor, name }) {
  const [active, setActive] = useState("about");
  const tabs = useRef({});

  const onKeyDown = (event) => {
    const index = TABS.findIndex((t) => t.id === active);
    const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: TABS.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const tab = TABS[(next + TABS.length) % TABS.length];
    setActive(tab.id);
    tabs.current[tab.id]?.focus();
  };

  const Panel = PANELS[active];
  return (
    <section className="card profile-tabs" aria-label="Doctor profile">
      <div className="tabs" role="tablist" aria-label="Profile sections" onKeyDown={onKeyDown}>
        {TABS.map((tab) => (
          <button
            type="button"
            role="tab"
            key={tab.id}
            id={`tab-${tab.id}`}
            ref={(el) => {
              tabs.current[tab.id] = el;
            }}
            aria-selected={active === tab.id}
            aria-controls={`panel-${tab.id}`}
            tabIndex={active === tab.id ? 0 : -1}
            className={active === tab.id ? "active" : ""}
            onClick={() => setActive(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="tab-panel" role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`} tabIndex={0}>
        <Panel doctor={doctor} name={name} />
      </div>
    </section>
  );
}
