import { RotateCcw, Search, SlidersHorizontal } from "lucide-react";
import { useCallback, useState } from "react";
import { activeFilterCount, EMPTY_FILTERS, EXPERIENCE_OPTIONS, FEE_RANGES } from "../../utils/doctors";
import { CURRENCY } from "../../utils/format";
import SpecializationPicker from "./SpecializationPicker";

/**
 * Search box and filters. Edits are a draft until "Apply filters" (or Enter)
 * hands them to the page, which puts them in the URL; the API does the
 * filtering. The parent remounts this component when the applied filters
 * change from outside (back button, a shared link, removing a chip), so the
 * draft never drifts from what is shown.
 *
 * Department and specialization come first (D118): choosing a department
 * shows only its specializations, and changing it drops chosen
 * specializations that the new department does not have. On small screens
 * the filters fold into a panel behind a "Filters (n)" button.
 */
export default function DoctorFilters({ applied, departments, onApply, onClear, onSpecializationsLoaded }) {
  const [draft, setDraft] = useState(applied);
  const [open, setOpen] = useState(false);
  const [known, setKnown] = useState({}); // specialization id -> { department_ids, ... } seen so far
  const bind = (field) => ({ value: draft[field], onChange: (e) => setDraft({ ...draft, [field]: e.target.value }) });
  const count = activeFilterCount(applied);

  const loaded = useCallback(
    (list) => {
      setKnown((k) => ({ ...k, ...Object.fromEntries(list.map((s) => [s.id, s])) }));
      onSpecializationsLoaded?.(list);
    },
    [onSpecializationsLoaded]
  );

  const changeDepartment = (e) => {
    const department = e.target.value;
    // "All departments" keeps every choice; another department keeps only its own.
    const specializations = department
      ? draft.specializations.filter((id) => known[id]?.department_ids?.includes(department))
      : draft.specializations;
    setDraft({ ...draft, department, specializations });
  };
  const submit = (e) => {
    e.preventDefault();
    setOpen(false);
    onApply(draft);
  };
  const clear = () => {
    setDraft(EMPTY_FILTERS);
    setOpen(false);
    onClear();
  };

  return (
    <form className={`card doctor-filters${open ? " open" : ""}`} role="search" aria-label="Find a doctor" onSubmit={submit}>
      <div className="doctor-search-row">
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
        <button
          type="button"
          className="secondary filter-toggle"
          aria-expanded={open}
          aria-controls="doctor-filter-panel"
          onClick={() => setOpen((v) => !v)}
        >
          <SlidersHorizontal size={17} aria-hidden="true" /> Filters{count ? ` (${count})` : ""}
        </button>
      </div>

      <div className="doctor-filter-panel" id="doctor-filter-panel">
        <div className="doctor-filter-primary">
          <label className="department-filter">
            Department
            <select value={draft.department} onChange={changeDepartment}>
              <option value="">All Departments</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
          <SpecializationPicker
            departmentId={draft.department || null}
            selected={draft.specializations}
            onChange={(specializations) => setDraft({ ...draft, specializations })}
            onLoaded={loaded}
          />
        </div>

        <div className="doctor-filter-row">
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
      </div>
    </form>
  );
}
