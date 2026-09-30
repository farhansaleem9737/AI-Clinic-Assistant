import { ChevronLeft, ChevronRight } from "lucide-react";
import { pageWindow } from "../utils/doctors";

// Numbered pagination: Previous, page numbers (with gaps), Next.
export default function Pagination({ page, totalPages, onChange }) {
  if (totalPages <= 1) return null;
  return (
    <nav className="pagination" aria-label="Pagination">
      <button type="button" className="secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        <ChevronLeft size={16} aria-hidden="true" /> Previous
      </button>
      {pageWindow(page, totalPages).map((p, index) =>
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
      <button type="button" className="secondary" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>
        Next <ChevronRight size={16} aria-hidden="true" />
      </button>
    </nav>
  );
}
