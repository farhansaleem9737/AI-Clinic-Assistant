import { LayoutGrid, List, SearchX } from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import heroImage from "../assets/doctor-hero.svg";
import Alert from "../components/Alert";
import DoctorCard from "../components/doctors/DoctorCard";
import DoctorFilters from "../components/doctors/DoctorFilters";
import EmptyState from "../components/EmptyState";
import Pagination from "../components/Pagination";
import { useFetch } from "../hooks/useFetch";
import { getPublicDepartments } from "../services/departmentService";
import { getPublicDoctors, getPublicSpecializations } from "../services/doctorService";
import {
  directoryApiParams,
  directorySearchParams,
  EMPTY_FILTERS,
  PAGE_SIZE,
  readDirectoryState,
  SORT_OPTIONS,
} from "../utils/doctors";

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
  const { data, loading, error } = useFetch(() => getPublicDoctors(apiParams), [JSON.stringify(apiParams), attempt]);
  const departments = useFetch(getPublicDepartments, []);
  const specializations = useFetch(getPublicSpecializations, []);

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
        specializations={specializations.data ?? []}
        onApply={(filters) => update({ filters, page: 1 })}
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
