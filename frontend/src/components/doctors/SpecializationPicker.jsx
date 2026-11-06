import { Check, Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useFetch } from "../../hooks/useFetch";
import { getCatalogSpecializations } from "../../services/catalogService";

const SEARCH_FROM = 8; // a search box once the list is longer than this

/**
 * Catalog specializations as tap-able chips (D118). With a department, only
 * that department's specializations are loaded and shown; without one, the
 * whole list loads only when asked for. Several may be chosen: doctors with
 * any of them match. Counts are of doctors the directory lists.
 */
export default function SpecializationPicker({ departmentId, selected, onChange, onLoaded }) {
  const labelId = useId();
  const [showAll, setShowAll] = useState(false);
  const [term, setTerm] = useState("");
  const enabled = Boolean(departmentId) || showAll;
  const { data, loading, error } = useFetch(() => getCatalogSpecializations(departmentId), [departmentId ?? ""], {
    query: "specializations/catalog",
    enabled,
  });

  // Tell the parent once per loaded list (not on every render: the callback may be a new function each time).
  const loadedRef = useRef(onLoaded);
  useEffect(() => {
    loadedRef.current = onLoaded;
  });
  useEffect(() => {
    if (data) loadedRef.current?.(data);
  }, [data]);

  const options = data ?? [];
  const needle = term.trim().toLowerCase();
  const shown = needle ? options.filter((o) => o.name.toLowerCase().includes(needle)) : options;
  const toggle = (id) => onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  return (
    <div className="spec-picker" role="group" aria-labelledby={labelId}>
      <div className="spec-picker-head">
        <span id={labelId} className="spec-picker-label">
          Specialization
        </span>
        {selected.length > 0 && (
          <button type="button" className="link-button small" onClick={() => onChange([])}>
            Clear ({selected.length})
          </button>
        )}
      </div>
      {!enabled ? (
        <div className="spec-picker-empty">
          <p className="muted small">Choose a department to see its specializations.</p>
          <button type="button" className="secondary small-button" onClick={() => setShowAll(true)}>
            Browse all specializations
          </button>
        </div>
      ) : error ? (
        <p className="field-error small">Specializations could not be loaded.</p>
      ) : loading && !data ? (
        <p className="muted small" role="status">
          Loading specializations…
        </p>
      ) : options.length === 0 ? (
        <p className="muted small">No specializations are listed for this department yet.</p>
      ) : (
        <>
          {options.length > SEARCH_FROM && (
            <div className="input-icon spec-picker-search">
              <Search size={16} aria-hidden="true" />
              <input type="search" aria-label="Search specializations" placeholder="Search specializations…" value={term} onChange={(e) => setTerm(e.target.value)} />
            </div>
          )}
          <div className="spec-chips">
            {shown.map((o) => {
              const on = selected.includes(o.id);
              return (
                <button
                  key={o.id}
                  type="button"
                  className={`spec-chip${on ? " selected" : ""}`}
                  aria-pressed={on}
                  aria-label={`${o.name}, ${o.doctor_count} ${o.doctor_count === 1 ? "doctor" : "doctors"}`}
                  onClick={() => toggle(o.id)}
                >
                  {on && <Check size={14} aria-hidden="true" />}
                  {o.name}
                  <span className="spec-chip-count">{o.doctor_count}</span>
                </button>
              );
            })}
            {shown.length === 0 && <p className="muted small">No specialization matches “{term.trim()}”.</p>}
          </div>
        </>
      )}
    </div>
  );
}
