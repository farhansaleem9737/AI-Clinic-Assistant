import { CalendarDays } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { formatCalendarDate } from "../../utils/datetime";

const complete = (value) => !value || /^\d{4}-\d{2}-\d{2}$/.test(value);

/**
 * "Select Date Range" button opening a small panel with From / To dates
 * (inclusive). The range is applied with Apply and removed with Clear; an
 * end before the start is refused here as well as by the API.
 */
export default function DateRangeFilter({ label, from, to, onChange }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ from, to });
  const [error, setError] = useState("");
  const panelId = useId();
  const button = useRef(null);
  const panel = useRef(null);

  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector("input")?.focus();
    const outside = (e) => {
      if (!panel.current?.contains(e.target) && !button.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [open]);

  const close = () => {
    setOpen(false);
    button.current?.focus();
  };
  const apply = () => {
    if (!complete(draft.from) || !complete(draft.to)) return setError("Enter complete dates.");
    if (draft.from && draft.to && draft.from > draft.to) return setError("The start date must not be after the end date.");
    setError("");
    onChange(draft);
    close();
  };
  const clear = () => {
    setDraft({ from: "", to: "" });
    setError("");
    onChange({ from: "", to: "" });
    close();
  };

  const summary =
    from || to
      ? `${from ? formatCalendarDate(from) : "Any date"} – ${to ? formatCalendarDate(to) : "Today"}`
      : "Select Date Range";

  return (
    <div className="date-range">
      <button
        ref={button}
        type="button"
        className={`date-range-button${from || to ? " has-value" : ""}`}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-label={`${label}: ${summary}`}
        title={label}
        onClick={() => {
          setDraft({ from, to });
          setError("");
          setOpen((v) => !v);
        }}
      >
        <CalendarDays size={20} aria-hidden="true" />
        <span>{summary}</span>
      </button>
      {open && (
        <div
          ref={panel}
          id={panelId}
          className="date-range-panel card"
          role="group"
          aria-label={label}
          onKeyDown={(e) => e.key === "Escape" && close()}
        >
          <p className="date-range-title">{label}</p>
          <label>
            From
            <input type="date" value={draft.from} max={draft.to || undefined} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
          </label>
          <label>
            To
            <input type="date" value={draft.to} min={draft.from || undefined} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
          </label>
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
          <div className="date-range-actions">
            <button type="button" className="secondary" onClick={clear}>
              Clear
            </button>
            <button type="button" onClick={apply}>
              Apply
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
