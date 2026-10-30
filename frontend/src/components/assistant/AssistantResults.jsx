import { ChevronRight, Clock, FileText } from "lucide-react";
import { Link } from "react-router-dom";
import Avatar from "../Avatar";
import StatusBadge from "../StatusBadge";

const nextAvailable = (iso) =>
  new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(iso));

function DoctorCards({ card, canBook }) {
  return (
    <ul className="ai-results" aria-label="Doctors found">
      {card.items.map((d) => (
        <li key={d.doctor_id} className="ai-result">
          <Avatar name={d.name} role="doctor" size={40} />
          <div className="ai-result-body">
            <strong>{d.name}</strong>
            <span className="muted small">{[d.specialization, d.department].filter(Boolean).join(" · ")}</span>
            <span className="muted small">
              {d.years_of_experience != null && `${d.years_of_experience} yrs experience`}
              {d.next_available && (
                <>
                  {" · "}
                  <Clock size={12} aria-hidden="true" /> Next: {nextAvailable(d.next_available)}
                </>
              )}
            </span>
            <span className="ai-result-links">
              <Link to={`/doctors/${d.doctor_id}`}>
                View profile<span className="sr-only">: {d.name}</span>
              </Link>
              {canBook && (
                <Link to={`/appointments/book?doctor=${d.doctor_id}`}>
                  Book<span className="sr-only"> with {d.name}</span>
                </Link>
              )}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function AppointmentCards({ card }) {
  return (
    <ul className="ai-results" aria-label="Appointments">
      {card.items.map((a) => (
        <li key={a.appointment_id} className="ai-result">
          <div className="ai-result-body">
            <strong>{a.when}</strong>
            <span className="muted small">
              {[a.patient && `${a.patient}${a.mrn ? ` (${a.mrn})` : ""}`, a.doctor, a.department].filter(Boolean).join(" · ")}
            </span>
          </div>
          <StatusBadge status={a.status} />
          <Link to={`/appointments/${a.appointment_id}`} className="icon-button" aria-label={`View appointment, ${a.when}`}>
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        </li>
      ))}
    </ul>
  );
}

const day = (iso) => (iso ? new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${iso}T12:00:00Z`)) : null);
// Patients open their own record; doctors the patient's page.
const recordLink = (d, own) => (own ? "/profile" : `/patients/${d.patient_id}`);

function DocumentCards({ card, own, onAsk }) {
  if (card.items.length === 0) return <p className="muted small ai-results-empty">No documents in this medical record yet.</p>;
  return (
    <ul className="ai-results" aria-label="Medical documents">
      {card.items.map((d) => (
        <li key={d.document_id} className="ai-result">
          <FileText className="ai-result-icon" size={22} aria-hidden="true" />
          <div className="ai-result-body">
            <strong>{d.title}</strong>
            <span className="muted small">
              {[d.type_label, d.report_date && `Report date ${day(d.report_date)}`, `Uploaded ${day(d.uploaded)}`, d.file_type].filter(Boolean).join(" · ")}
            </span>
            <span className="ai-result-links">
              <Link to={recordLink(d, own)}>
                View document<span className="sr-only">: {d.title}</span>
              </Link>
              {onAsk && (
                <button type="button" className="link-button" onClick={() => onAsk(`Explain the medical document with id ${d.document_id}.`)}>
                  Summarize<span className="sr-only"> {d.title}</span>
                </button>
              )}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

const FLAG = { high: "Above range", low: "Below range" };

function Measurements({ rows }) {
  return (
    <div className="ai-table-wrap">
      <table className="ai-table">
        <thead>
          <tr>
            <th scope="col">Test</th>
            <th scope="col">Result</th>
            <th scope="col">Reference range</th>
            <th scope="col">Page</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m, i) => (
            <tr key={i} className={m.out_of_range ? "ai-out-of-range" : undefined}>
              <td>{m.test}</td>
              <td>
                {m.value} {m.unit}
                {m.out_of_range && <span className="ai-flag"> {FLAG[m.out_of_range]}</span>}
                {!m.out_of_range && m.report_flag && <span className="ai-flag"> Flag: {m.report_flag}</span>}
              </td>
              <td>{m.reference_range ?? <span className="muted">Not printed</span>}</td>
              <td>{m.page}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReportCard({ card }) {
  const d = card.document;
  const outside = card.measurements.filter((m) => m.out_of_range);
  const about = [...new Map(card.measurements.filter((m) => m.about).map((m) => [m.about, m.test])).entries()];
  const dated = (d.printed_date && `Date on report: ${d.printed_date}`) || (d.report_date && `Report date: ${day(d.report_date)}`);
  return (
    <section className="ai-report" aria-label={`Report: ${d.title}`}>
      <h4>{d.title}</h4>
      <p className="muted small">{[d.type_label, dated, d.laboratory].filter(Boolean).join(" · ")}</p>
      {card.problem && <p className="ai-report-problem">{card.problem}</p>}
      {card.measurements.length > 0 ? (
        <>
          <h5>Measurements (as printed on the report)</h5>
          <Measurements rows={card.measurements} />
          <h5>Outside the report&apos;s reference range</h5>
          <p className="small">
            {outside.length === 0
              ? "None of the values with a printed reference range are outside it."
              : outside.map((m) => `${m.test} (${FLAG[m.out_of_range].toLowerCase()})`).join(", ")}
          </p>
        </>
      ) : (
        !card.problem &&
        card.has_text && <p className="small">No laboratory values in a recognisable table were found. Open the document to read it.</p>
      )}
      {about.length > 0 && (
        <>
          <h5>About these tests (general information)</h5>
          <ul className="small ai-report-about">
            {about.map(([text, test]) => (
              <li key={text}>
                <strong>{test}:</strong> {text}
              </li>
            ))}
          </ul>
        </>
      )}
      {card.notes.map((n) => (
        <p key={n} className="muted small ai-report-note">
          {n}
        </p>
      ))}
      <p className="muted small">This is not a diagnosis. Please discuss these results with your doctor, especially any value outside its range.</p>
      <p className="muted small ai-report-source">
        Source: {card.sources.map((s) => `${s.title}${s.pages.length ? `, page ${s.pages.join(", ")}` : ""}`).join("; ")}
      </p>
    </section>
  );
}

function SummaryCard({ card }) {
  return (
    <section className="ai-report" aria-label="Summary of medical documents">
      <h4>
        Summary of {card.processed.length} document{card.processed.length === 1 ? "" : "s"}
      </h4>
      {card.processed.length > 0 && (
        <ul className="small ai-report-docs">
          {card.processed.map((d) => (
            <li key={d.document_id}>
              <strong>{d.title}</strong> ({day(d.report_date || d.uploaded)}): {d.measurements} measurement{d.measurements === 1 ? "" : "s"}
              {d.outside_printed_range.length > 0 && `; outside range: ${d.outside_printed_range.join(", ")}`}
            </li>
          ))}
        </ul>
      )}
      {card.series.length > 0 && (
        <>
          <h5>Repeated tests over time</h5>
          {card.series.map((s) => (
            <div key={`${s.test}-${s.unit}`} className="ai-series">
              <strong className="small">
                {s.test}
                {s.unit ? ` (${s.unit})` : ""}
              </strong>
              <span className="small">
                {s.points.map((p) => `${day(p.date)}: ${p.value}${p.out_of_range ? ` (${FLAG[p.out_of_range].toLowerCase()})` : ""}`).join(" → ")}
              </span>
            </div>
          ))}
        </>
      )}
      {card.skipped.length > 0 && (
        <>
          <h5>Not read</h5>
          <ul className="small">
            {card.skipped.map((d) => (
              <li key={d.document_id}>
                <strong>{d.title}</strong>: {d.reason}
              </li>
            ))}
          </ul>
        </>
      )}
      {card.not_included > 0 && <p className="muted small">{card.not_included} older document(s) were not included; ask about them specifically.</p>}
      <p className="muted small">Values are compared only for the same test in the same unit. This is not a diagnosis; discuss changes with your doctor.</p>
    </section>
  );
}

function ProfileCard({ card }) {
  const p = card.items[0];
  const rows = [
    ["Name", p.name],
    ["MRN", p.mrn],
    ["Date of birth", day(p.date_of_birth)],
    ["Phone", p.phone],
    ["Email", p.email],
    ["Address", p.address],
    ["Preferred language", p.preferred_language],
  ];
  return (
    <section className="ai-report" aria-label="Your profile">
      <dl className="ai-profile">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v || <span className="muted">Not provided</span>}</dd>
          </div>
        ))}
      </dl>
      <Link to="/profile">Edit in My Profile</Link>
    </section>
  );
}

/**
 * Result cards under an answer (D100, D101): doctors, appointments, medical
 * documents and reports exactly as the backend returned or read them for this
 * user. Nothing here is generated by the model.
 */
export default function AssistantResults({ results, canBook, ownRecord = true, onAsk }) {
  return results.map((card, i) => (
    <div key={i} className="ai-result-group">
      {card.kind === "doctors" && <DoctorCards card={card} canBook={canBook} />}
      {card.kind === "appointments" && <AppointmentCards card={card} />}
      {card.kind === "medical_documents" && <DocumentCards card={card} own={ownRecord} onAsk={onAsk} />}
      {card.kind === "medical_report" && <ReportCard card={card} />}
      {card.kind === "medical_summary" && <SummaryCard card={card} />}
      {card.kind === "profile" && <ProfileCard card={card} />}
      {card.items && card.total > card.items.length && (
        <p className="muted small ai-results-more">
          Showing {card.items.length} of {card.total}.{" "}
          <Link to={card.kind === "doctors" ? "/doctors" : "/appointments"}>View all</Link>
        </p>
      )}
    </div>
  ));
}
