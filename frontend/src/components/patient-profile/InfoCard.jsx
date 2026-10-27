import { useId } from "react";

/**
 * A titled card of label/value rows. Empty values read "Not provided"
 * instead of leaving a blank line.
 */
export default function InfoCard({ title, icon: Icon, rows, action, footnote }) {
  const titleId = useId();
  return (
    <section className="card info-card" aria-labelledby={titleId}>
      <div className="section-head">
        <Icon className="icon" size={22} aria-hidden="true" />
        <h3 id={titleId}>{title}</h3>
        {action}
      </div>
      <dl className="info-list ruled">
        {rows.map(({ label, value }) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value || <span className="muted">Not provided</span>}</dd>
          </div>
        ))}
      </dl>
      {footnote && <p className="muted small info-footnote">{footnote}</p>}
    </section>
  );
}
