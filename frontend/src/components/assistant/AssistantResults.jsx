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

function HistoryCards({ card }) {
  return (
    <ul className="ai-results" aria-label="Your appointments">
      {card.items.map((a) => (
        <li key={a.appointment_id} className={`ai-result${a.status === "cancelled" || a.status === "no_show" ? " ai-result-muted" : ""}`}>
          <Avatar name={a.doctor} role="doctor" size={40} />
          <div className="ai-result-body">
            <strong>{a.doctor}</strong>
            <span className="muted small">{[a.specialization, a.department].filter(Boolean).join(" · ")}</span>
            <span className="small">
              <Clock size={12} aria-hidden="true" /> {a.date}, {a.start}–{a.end}
            </span>
            <span className="ai-result-links">
              <Link to={`/appointments/${a.appointment_id}`}>
                View appointment<span className="sr-only">: {a.doctor}, {a.date}</span>
              </Link>
              <Link to={`/doctors/${a.doctor_id}`}>
                Doctor profile<span className="sr-only">: {a.doctor}</span>
              </Link>
            </span>
          </div>
          <StatusBadge status={a.status} />
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
            <th scope="col">Reference</th>
            <th scope="col">Flag</th>
            <th scope="col">Page</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m, i) => (
            <tr key={i} className={m.out_of_range ? "ai-out-of-range" : undefined}>
              <td>{m.test}</td>
              <td>
                {m.value} {m.unit}
              </td>
              <td>{m.reference_range ?? <span className="muted">Not printed</span>}</td>
              <td>
                {m.out_of_range ? <span className="ai-flag">{FLAG[m.out_of_range]}</span> : m.report_flag || <span className="muted">—</span>}
                {m.out_of_range && m.report_flag && <span className="muted"> ({m.report_flag})</span>}
              </td>
              <td>{m.page}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Conditions({ items }) {
  if (items.length === 0) return <p className="small">The report does not name a condition.</p>;
  return (
    <ul className="ai-report-list">
      {items.map((c) => (
        <li key={c.name}>
          <strong>{c.name}</strong>
          <span className="muted small"> · {c.role === "primary" ? "main condition stated in the report" : "also stated in the report"}</span>
          {c.about && <p className="small">{c.about}</p>}
          <p className="muted small ai-quote">“{c.source_text}” (page {c.page})</p>
        </li>
      ))}
    </ul>
  );
}

function Symptoms({ items }) {
  if (items.length === 0) return <p className="small">The report does not describe symptoms.</p>;
  return (
    <ul className="ai-report-list">
      {items.map((s) => (
        <li key={s.name}>
          <strong>{s.name}</strong> <span className="muted small">(page {s.page})</span>
        </li>
      ))}
    </ul>
  );
}

function Abnormal({ rows }) {
  const outside = rows.filter((m) => m.out_of_range);
  if (rows.length === 0) return <p className="small">No laboratory values could be read, so abnormal results cannot be listed.</p>;
  if (outside.length === 0) return <p className="small">None of the values the report could be judged on are outside their printed reference or flag.</p>;
  return (
    <ul className="ai-report-list">
      {outside.map((m) => (
        <li key={`${m.test}-${m.page}`}>
          <strong>{m.test}</strong>: {m.value} {m.unit} — {FLAG[m.out_of_range].toLowerCase()}
          {m.reference_range && <span className="muted"> (reference: {m.reference_range})</span>}
          {m.about && <p className="small">{m.about}</p>}
        </li>
      ))}
    </ul>
  );
}

function Sections({ items, kind }) {
  const chosen = items.filter((s) => s.kind === kind);
  if (chosen.length === 0) return <p className="small">The report has no {kind === "follow_up" ? "follow-up" : "interpretation"} section.</p>;
  return chosen.map((s) => (
    <p key={s.heading} className="small">
      <strong>{s.heading}</strong> (page {s.page}): {s.text}
    </p>
  ));
}

const PARTS = {
  conditions: "Condition",
  symptoms: "Symptoms described",
  measurements: "Laboratory results",
  abnormal: "Abnormal findings",
  follow_up: "Follow-up in the report",
  interpretation: "The report's interpretation",
};

function ReportCard({ card }) {
  const d = card.document;
  const rows = card.measurements ?? [];
  const conditions = card.conditions ?? [];
  const symptoms = card.symptoms ?? [];
  const sections = card.sections ?? [];
  const about = [...new Map(rows.filter((m) => m.about).map((m) => [m.about, m.test])).entries()];
  const focus = card.focus ?? "summary";
  const render = {
    conditions: () => <Conditions items={conditions} />,
    symptoms: () => <Symptoms items={symptoms} />,
    measurements: () => (rows.length ? <Measurements rows={rows} /> : <p className="small">No laboratory table could be read from this document.</p>),
    abnormal: () => <Abnormal rows={rows} />,
    follow_up: () => <Sections items={sections} kind="follow_up" />,
    interpretation: () => <Sections items={sections} kind="interpretation" />,
  };
  // The part the user asked about comes first and open; the rest is one click away.
  const order =
    focus === "summary"
      ? ["conditions", "abnormal", "symptoms", "measurements", "interpretation", "follow_up"]
      : [focus, ...Object.keys(render).filter((k) => k !== focus)];
  const available = (k) =>
    ({
      conditions: conditions.length > 0,
      symptoms: symptoms.length > 0,
      measurements: rows.length > 0,
      abnormal: rows.length > 0,
      follow_up: sections.some((s) => s.kind === "follow_up"),
      interpretation: sections.some((s) => s.kind === "interpretation"),
    })[k];
  const open = focus === "summary" ? order.filter(available).slice(0, 2) : [focus];
  const dates = [
    (d.printed_date && `Date on report: ${d.printed_date}`) || (d.report_date && `Report date: ${day(d.report_date)}`),
    d.uploaded && `Uploaded ${day(d.uploaded)}`,
  ];
  return (
    <section className="ai-report" aria-label={`Report: ${d.title}`}>
      <h4>{d.title}</h4>
      <p className="muted small">{[d.document_kind || d.type_label, ...dates, d.laboratory].filter(Boolean).join(" · ")}</p>
      {!card.version && (
        <p className="ai-report-problem">Read with an earlier version of the document reader. Ask again for an up-to-date reading.</p>
      )}
      {card.problem && <p className="ai-report-problem">{card.problem}</p>}
      {!card.problem &&
        order
          .filter((k) => open.includes(k) || available(k))
          .map((k) =>
            open.includes(k) ? (
              <div key={k}>
                <h5>{PARTS[k]}</h5>
                {render[k]()}
              </div>
            ) : (
              <details key={k} className="ai-report-more">
                <summary>{PARTS[k]}</summary>
                {render[k]()}
              </details>
            )
          )}
      {about.length > 0 && (
        <details className="ai-report-more">
          <summary>About these tests (general information)</summary>
          <ul className="small ai-report-about">
            {about.map(([text, test]) => (
              <li key={text}>
                <strong>{test}:</strong> {text}
              </li>
            ))}
          </ul>
        </details>
      )}
      {(card.notes ?? []).map((n) => (
        <p key={n} className="muted small ai-report-note">
          {n}
        </p>
      ))}
      <p className="muted small">Read directly from the document. Not a diagnosis: please discuss these results with your doctor.</p>
      <p className="muted small ai-report-source">
        Source: {card.sources.map((s) => `${s.title}${s.pages?.length ? `, page ${s.pages.join(", ")}` : ""}`).join("; ")}
      </p>
    </section>
  );
}

function SummaryCard({ card }) {
  const comparable = card.series.filter((s) => s.comparable !== false);
  const notComparable = card.series.filter((s) => s.comparable === false);
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
              {d.conditions?.length > 0 && `; condition: ${d.conditions.join(", ")}`}
              {d.outside_printed_range.length > 0 && `; outside range: ${d.outside_printed_range.join(", ")}`}
            </li>
          ))}
        </ul>
      )}
      {comparable.length > 0 && (
        <>
          <h5>Same tests over time</h5>
          <div className="ai-table-wrap">
            <table className="ai-table">
              <thead>
                <tr>
                  <th scope="col">Test</th>
                  {comparable[0].points.map((p, i) => (
                    <th key={i} scope="col">
                      {day(p.date)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {comparable.map((s) => (
                  <tr key={`${s.key ?? s.test}-${s.unit}`}>
                    <td>
                      {s.test}
                      {s.unit ? ` (${s.unit})` : ""}
                    </td>
                    {s.points.map((p, i) => (
                      <td key={i} className={p.out_of_range ? "ai-out-of-range" : undefined}>
                        {p.value}
                        {p.out_of_range && <span className="ai-flag"> {FLAG[p.out_of_range]}</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {notComparable.length > 0 && (
        <p className="muted small">Not compared because the units differ: {notComparable.map((s) => s.test).join(", ")}.</p>
      )}
      {card.skipped.length > 0 && (
        <>
          <h5>Not fully read</h5>
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
      {card.kind === "appointment_history" && <HistoryCards card={card} />}
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
