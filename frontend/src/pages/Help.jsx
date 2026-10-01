import { CalendarPlus, CalendarSync, Headset, KeyRound, UserRound } from "lucide-react";
import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";

// Optional clinic contact details, set per deployment (frontend .env).
const SUPPORT_EMAIL = import.meta.env.VITE_SUPPORT_EMAIL?.trim();
const SUPPORT_PHONE = import.meta.env.VITE_SUPPORT_PHONE?.trim();

const TOPICS = [
  {
    icon: CalendarPlus,
    title: "Booking an appointment",
    body: (
      <>
        Open <Link to="/doctors">Doctors</Link>, choose a doctor, pick a date and a free time on their profile, then
        confirm on the next step. The appointment appears under <Link to="/appointments">Appointments</Link>.
      </>
    ),
  },
  {
    icon: CalendarSync,
    title: "Changing or cancelling",
    body: (
      <>
        Open the appointment from <Link to="/appointments">Appointments</Link>. Reschedule and Cancel are offered there
        while the clinic still allows changes online; close to the appointment time, contact the clinic instead.
      </>
    ),
  },
  {
    icon: UserRound,
    title: "Your details",
    body: (
      <>
        Keep your phone number, email and address up to date in <Link to="/profile">My Profile</Link>. Your medical
        record number (MRN) is assigned by the clinic and cannot be changed.
      </>
    ),
  },
  {
    icon: KeyRound,
    title: "Signing in",
    body: <>Passwords cannot be reset online yet. If you cannot sign in, contact the clinic.</>,
  },
];

/** Help & Support: how the app's existing features work, and how to reach the clinic. */
export default function Help() {
  const { hash } = useLocation();
  useEffect(() => {
    if (hash === "#contact") document.getElementById("contact")?.scrollIntoView?.({ block: "start" });
  }, [hash]);

  return (
    <div className="help-page">
      <h1>Help &amp; Support</h1>
      <p className="muted">Quick answers about using Clinic AI Assistant.</p>

      <div className="help-topics">
        {TOPICS.map(({ icon: Icon, title, body }) => (
          <section key={title} className="card" aria-labelledby={`help-${title}`}>
            <div className="section-head">
              <Icon className="icon" size={20} aria-hidden="true" />
              <h2 id={`help-${title}`}>{title}</h2>
            </div>
            <p>{body}</p>
          </section>
        ))}
      </div>

      <section className="card" id="contact" aria-labelledby="help-contact">
        <div className="section-head">
          <Headset className="icon" size={20} aria-hidden="true" />
          <h2 id="help-contact">Contact the clinic</h2>
        </div>
        {SUPPORT_EMAIL || SUPPORT_PHONE ? (
          <ul className="help-contact">
            {SUPPORT_PHONE && (
              <li>
                Phone: <a href={`tel:${SUPPORT_PHONE.replace(/[^\d+]/g, "")}`}>{SUPPORT_PHONE}</a>
              </li>
            )}
            {SUPPORT_EMAIL && (
              <li>
                Email: <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>
              </li>
            )}
          </ul>
        ) : (
          <p>Please speak to the clinic&apos;s reception desk.</p>
        )}
        <p className="muted small">
          For a medical emergency, call your local emergency number. Messages to the clinic are not monitored around the
          clock.
        </p>
      </section>
    </div>
  );
}
