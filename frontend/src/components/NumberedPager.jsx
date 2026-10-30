import { ChevronLeft, ChevronRight } from "lucide-react";
import { pageWindow } from "../utils/doctors";

/**
 * "Showing X to Y of Z <noun>" with previous / numbered / next buttons. The
 * total comes from the server, never from the rows on the current page.
 */
export default function NumberedPager({ page, pageSize, total, noun, onChange }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);
  return (
    <div className="appt-pager">
      <p className="muted" aria-live="polite">
        Showing {first} to {last} of {total} {total === 1 ? noun.replace(/s$/, "") : noun}
      </p>
      <nav aria-label="Pagination">
        <button type="button" className="secondary" disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label="Previous page">
          <ChevronLeft size={18} aria-hidden="true" />
        </button>
        {pageWindow(page, pages).map((p, index) =>
          p === null ? (
            <span key={`gap-${index}`} className="gap" aria-hidden="true">
              …
            </span>
          ) : (
            <button
              type="button"
              key={p}
              className={p === page ? "" : "secondary"}
              aria-label={`Page ${p}`}
              aria-current={p === page ? "page" : undefined}
              onClick={() => onChange(p)}
            >
              {p}
            </button>
          )
        )}
        <button type="button" className="secondary" disabled={page >= pages} onClick={() => onChange(page + 1)} aria-label="Next page">
          <ChevronRight size={18} aria-hidden="true" />
        </button>
      </nav>
    </div>
  );
}
