import { RotateCcw, Search, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { EMPTY_FILTERS, EXPERIENCE_OPTIONS, FEE_RANGES } from "../../utils/doctors";
import { CURRENCY } from "../../utils/format";

/**
 * Search box and filters. Edits are a draft until "Apply filters" (or Enter)
 * hands them to the page, which puts them in the URL; the API does the
 * filtering. The parent remounts this component when the applied filters
 * change from outside (back button, a shared link), so the draft never
 * drifts from what is shown.
 */
export default function DoctorFilters({ applied, departments, specializations, onApply, onClear }) {
  const [draft, setDraft] = useState(applied);
  const bind = (field) => ({ value: draft[field], onChange: (e) => setDraft({ ...draft, [field]: e.target.value }) });

  const submit = (e) => {
    e.preventDefault();
    onApply(draft);
  };
  const clear = () => {
    setDraft(EMPTY_FILTERS);
    onClear();
  };

  return (
    <form className="card doctor-filters" role="search" aria-label="Find a doctor" onSubmit={submit}>
      <div className="input-icon doctor-search">
        <Search size={20} aria-hidden="true" />
        <input
          id="search"
          type="search"
          aria-label="Search by doctor name or specialization"
          placeholder="Search by doctor name or specialization…"
          {...bind("q")}
        />
      </div>

      <div className="doctor-filter-row">
        <label>
          Department
          <select {...bind("department")}>
            <option value="">All Departments</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Specialization
          <select {...bind("specialization")}>
            <option value="">All Specializations</option>
            {specializations.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Min. experience
          <select {...bind("min_experience")}>
            <option value="">Any</option>
            {EXPERIENCE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Fee range{CURRENCY ? ` (${CURRENCY})` : ""}
          <select {...bind("fee")}>
            <option value="">Any</option>
            {FEE_RANGES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">
          <SlidersHorizontal size={17} aria-hidden="true" /> Apply filters
        </button>
        <button type="button" className="secondary" onClick={clear}>
          <RotateCcw size={17} aria-hidden="true" /> Clear filters
        </button>
      </div>
    </form>
  );
}
