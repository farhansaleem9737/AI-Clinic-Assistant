import { LayoutGrid, List, SearchX, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import heroImage from "../assets/doctor-hero.svg";
import Alert from "../components/Alert";
import DoctorCard from "../components/doctors/DoctorCard";
import DoctorFilters from "../components/doctors/DoctorFilters";
import EmptyState from "../components/EmptyState";
import Pagination from "../components/Pagination";
import { useFetch } from "../hooks/useFetch";
import { getPublicDepartments } from "../services/departmentService";
import { getCatalogSpecializations } from "../services/catalogService";
import { getPublicDoctors } from "../services/doctorService";
import {
  directoryApiParams,
  directorySearchParams,
  EMPTY_FILTERS,
  EXPERIENCE_OPTIONS,
  FEE_RANGES,
  PAGE_SIZE,
  readDirectoryState,
  SORT_OPTIONS,
} from "../utils/doctors";

// The applied filters as removable chips, so it is clear what narrows the list.
function ActiveFilters({ filters, departments, specNames, onChange, onClear }) {
  const chips = [];
  const drop = (changes) => onChange({ ...filters, ...changes });
  if (filters.q.trim()) chips.push({ key: "q", label: `“${filters.q.trim()}”`, remove: () => drop({ q: "" }) });
  if (filters.department) {
    const name = departments.find((d) => d.id === filters.department)?.name ?? "Department";
    chips.push({ key: "department", label: name, remove: () => drop({ department: "" }) });
  }
  for (const id of filters.specializations) {
    chips.push({
      key: id,
      label: specNames[id] ?? "Specialization",
      remove: () => drop({ specializations: filters.specializations.filter((x) => x !== id) }),
    });
  }
  if (filters.specialization) chips.push({ key: "spec-text", label: filters.specialization, remove: () => drop({ specialization: "" }) });
  if (filters.min_experience) {
    const label = EXPERIENCE_OPTIONS.find((o) => o.value === filters.min_experience)?.label;
    chips.push({ key: "exp", label: `${label} experience`, remove: () => drop({ min_experience: "" }) });
  }
  if (filters.fee) {
    const label = FEE_RANGES.find((o) => o.value === filters.fee)?.label;
    chips.push({ key: "fee", label: `Fee ${label}`, remove: () => drop({ fee: "" }) });
  }
  if (!chips.length) return null;
  return (
    <div className="active-filters" aria-label="Applied filters">
      {chips.map((c) => (
        <button key={c.key} type="button" className="filter-chip" onClick={c.remove} aria-label={`Remove filter ${c.label}`}>
          {c.label} <X size={14} aria-hidden="true" />
        </button>
      ))}
      <button type="button" className="link-button small" onClick={onClear}>
        Clear all
      </button>
    </div>
  );
}

/**
 * Public doctors directory. The URL is the state: search, filters, sort,
 * page and view all live in the query string, and every change of it asks
 * the API for exactly that page. Nothing is filtered or sorted in the browser.
 */
export default function Doctors() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = readDirectoryState(searchParams);
  const [attempt, setAttempt] = useState(0); // bumped by "Try again"

  // The search icon in the public navigation links to /doctors#search.
  const location = useLocation();
  useEffect(() => {
    if (location.hash === "#search") document.getElementById("search")?.focus();
  }, [location.hash, location.key]);

  const apiParams = directoryApiParams(state);
  const { data, loading, error } = useFetch(() => getPublicDoctors(apiParams), [JSON.stringify(apiParams)], {
    query: "doctors/directory",
    refresh: attempt,
  });
  const departments = useFetch(getPublicDepartments, [], { query: "departments/public" });
  // Names for specializations chosen in a shared link (the picker adds the ones it loads).
  const [specNames, setSpecNames] = useState({});
  const catalog = useFetch(() => getCatalogSpecializations(), [""], {
    query: "specializations/catalog",
    enabled: state.filters.specializations.some((id) => !specNames[id]),
  });
  const remember = useCallback((list) => setSpecNames((n) => ({ ...n, ...Object.fromEntries(list.map((x) => [x.id, x.name])) })), []);
  const names = { ...Object.fromEntries((catalog.data ?? []).map((x) => [x.id, x.name])), ...specNames };

  const update = (changes) => setSearchParams(directorySearchParams({ ...state, ...changes }));
  const doctors = data?.items ?? [];
  const total = data?.total ?? 0;
  const filtersKey = JSON.stringify(state.filters);

  return (
    <div className="doctors-page">
      <section className="doctors-hero">
        <div>
          <p className="eyebrow">Our doctors</p>
          <h1>Find a doctor</h1>
          <p className="lead">Find the right specialist for your care.</p>
        </div>
        {/* Decorative illustration, not a real person. */}
        <img src={heroImage} alt="" />
      </section>

      <DoctorFilters
        key={filtersKey}
        applied={state.filters}
        departments={departments.data?.items ?? []}
        onApply={(filters) => update({ filters, page: 1 })}
        onClear={() => update({ filters: EMPTY_FILTERS, page: 1 })}
        onSpecializationsLoaded={remember}
      />
      <ActiveFilters
        filters={state.filters}
        departments={departments.data?.items ?? []}
        specNames={names}
        onChange={(filters) => update({ filters, page: 1 })}
        onClear={() => update({ filters: EMPTY_FILTERS, page: 1 })}
      />

      <div className="doctors-toolbar">
        <h2 aria-live="polite">{loading ? "Searching…" : `${total} ${total === 1 ? "doctor" : "doctors"} found`}</h2>
        <label className="sort">
          Sort by
          <select value={state.sort} onChange={(e) => update({ sort: e.target.value, page: 1 })}>
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <div className="view-toggle" role="group" aria-label="View">
          <button
            type="button"
            className={state.view === "grid" ? "" : "secondary"}
            aria-label="Grid view"
            aria-pressed={state.view === "grid"}
            onClick={() => update({ view: "grid" })}
          >
            <LayoutGrid size={18} aria-hidden="true" />
          </button>
          <button
            type="button"
            className={state.view === "list" ? "" : "secondary"}
            aria-label="List view"
            aria-pressed={state.view === "list"}
            onClick={() => update({ view: "list" })}
          >
            <List size={18} aria-hidden="true" />
          </button>
        </div>
      </div>

      {error ? (
        <div className="card">
          <Alert>{error}</Alert>
          <button type="button" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </div>
      ) : loading && doctors.length === 0 ? (
        <div className={`doctor-results ${state.view}`} role="status" aria-label="Loading doctors">
          {Array.from({ length: PAGE_SIZE }, (_, i) => (
            <div key={i} className="card skeleton doctor-skeleton" />
          ))}
        </div>
      ) : doctors.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={SearchX}
            action={
              <button type="button" className="secondary" onClick={() => update({ filters: EMPTY_FILTERS, page: 1 })}>
                Clear filters
              </button>
            }
          >
            No doctors found. Try a different search or fewer filters.
          </EmptyState>
        </div>
      ) : (
        <div className={`doctor-results ${state.view}`} aria-busy={loading}>
          {doctors.map((doctor) => (
            <DoctorCard key={doctor.id} doctor={doctor} />
          ))}
        </div>
      )}

      <Pagination page={state.page} totalPages={data?.total_pages ?? 0} onChange={(page) => update({ page })} />
    </div>
  );
}
