import { ArrowLeft, ArrowRight, BriefcaseMedical, CircleDollarSign, RotateCcw, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useFetch } from "../../hooks/useFetch";
import { getErrorMessage } from "../../services/api";
import { getPublicDepartments } from "../../services/departmentService";
import { getPublicDoctors, getPublicSpecializations } from "../../services/doctorService";
import { bookingAvailability } from "../../utils/doctors";
import { CURRENCY, doctorName } from "../../utils/format";
import Alert from "../Alert";
import Avatar from "../Avatar";

const PAGE_SIZE = 9;
const SEARCH_DELAY_MS = 300;

function fee(doctor) {
  if (doctor.consultation_fee == null) return "Fee not available";
  return CURRENCY ? `${CURRENCY} ${doctor.consultation_fee}` : doctor.consultation_fee;
}

// One selectable doctor. A real (visually hidden) radio input gives the
// radio-group keyboard behaviour; the whole card is its label.
function DoctorOption({ doctor, checked, onChoose }) {
  const name = doctorName(doctor);
  const badge = bookingAvailability(doctor.availability);
  return (
    <label className={`card doctor-option${checked ? " selected" : ""}`}>
      <input type="radio" name="booking-doctor" className="sr-only" checked={checked} onChange={() => onChoose(doctor)} />
      <span className="doctor-option-head">
        <Avatar name={doctor.name} role="doctor" src={doctor.photo_url} size={64} />
        <span className="doctor-option-id">
          <strong>{name}</strong>
          <span className="specialization">{doctor.specialization}</span>
          <span className="muted">{doctor.department_name}</span>
        </span>
        <span className="radio-mark" aria-hidden="true" />
      </span>
      <span className="doctor-option-facts">
        <span>
          <BriefcaseMedical size={17} aria-hidden="true" /> {doctor.years_of_experience} years experience
        </span>
        <span>
          <CircleDollarSign size={17} aria-hidden="true" /> {fee(doctor)}
          {doctor.consultation_fee != null && <span className="sr-only"> consultation fee</span>}
        </span>
      </span>
      <span className={`badge status ${badge.tone}`}>
        <span className="dot" aria-hidden="true" />
        {badge.label}
      </span>
    </label>
  );
}

function LoadingCards() {
  return (
    <div className="doctor-options" role="status" aria-label="Loading doctors">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="card skeleton" style={{ height: 190 }} />
      ))}
    </div>
  );
}

/**
 * Step 1: search and filter real doctors (all filtering happens in the API)
 * and choose one. `selected` is the chosen doctor or null.
 */
export default function DoctorPicker({ selected, onSelect, onBack, onContinue }) {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [specialization, setSpecialization] = useState("");
  // Set once the user changes a filter; until then a doctor chosen elsewhere
  // (the profile page, or step 2) stays selected even if not on this page.
  const [touched, setTouched] = useState(false);

  // Search as the user types, but only once they pause.
  useEffect(() => {
    const timer = setTimeout(() => setSearch(query.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const departments = useFetch(getPublicDepartments, []);
  const specializations = useFetch(() => getPublicSpecializations(departmentId || undefined), [departmentId]);

  // A specialization that does not exist in the chosen department is ignored
  // (shown as "All Specializations") once that department's options load.
  const specializationOptions = specializations.data ?? [];
  const activeSpecialization =
    specialization && !specializations.loading && specializations.data && !specializations.data.includes(specialization)
      ? ""
      : specialization;

  const filters = {
    q: search || undefined,
    department_id: departmentId || undefined,
    specialization: activeSpecialization || undefined,
  };
  const filterKey = JSON.stringify(filters);
  const firstPage = useFetch(() => getPublicDoctors({ ...filters, page: 1, page_size: PAGE_SIZE }), [filterKey]);

  // Further pages ("Show more doctors"), kept only for the filters they were loaded with.
  const [more, setMore] = useState({ key: "", items: [], page: 1, loading: false, error: "" });
  const extra = more.key === filterKey ? more : { key: filterKey, items: [], page: 1, loading: false, error: "" };
  const latestKey = useRef(filterKey);
  useEffect(() => {
    latestKey.current = filterKey;
  }, [filterKey]);

  const loadMore = async () => {
    const key = filterKey;
    const page = extra.page + 1;
    setMore({ ...extra, loading: true, error: "" });
    try {
      const res = await getPublicDoctors({ ...filters, page, page_size: PAGE_SIZE });
      if (latestKey.current === key) setMore({ key, items: [...extra.items, ...res.data.items], page, loading: false, error: "" });
    } catch (err) {
      if (latestKey.current === key) setMore({ ...extra, loading: false, error: getErrorMessage(err, "Could not load more doctors") });
    }
  };

  const ready = !firstPage.loading && firstPage.data;
  const items = ready ? [...firstPage.data.items, ...extra.items] : [];
  const total = firstPage.data?.total ?? 0;
  const inResults = Boolean(selected && items.some((d) => d.id === selected.id));
  const hasFilters = Boolean(search || departmentId || activeSpecialization);

  // After the user changes filters, a selection that is no longer in the results is cleared.
  useEffect(() => {
    if (ready && touched && selected && !inResults) onSelect(null);
  }, [ready, touched, inResults, selected, onSelect]);

  const change = (setter) => (e) => {
    setTouched(true);
    setter(e.target.value);
  };
  const clearFilters = () => {
    setTouched(true);
    setQuery("");
    setSearch("");
    setDepartmentId("");
    setSpecialization("");
  };

  // A doctor chosen before any filtering, but not on the first page of results.
  const pinned = selected && !touched && ready && !inResults ? selected : null;

  return (
    <>
      <div className="booking-card-head">
        <Search className="icon" size={24} aria-hidden="true" />
        <div>
          <h2 id="booking-step-title">Select a doctor</h2>
          <p className="muted">Search and choose a doctor to book an appointment.</p>
        </div>
      </div>

      <div className="booking-filters" role="search" aria-label="Find a doctor">
        <div className="input-icon booking-search">
          <Search size={20} aria-hidden="true" />
          <input
            type="search"
            aria-label="Search by doctor name or specialization"
            placeholder="Search by doctor name or specialization..."
            value={query}
            onChange={change(setQuery)}
          />
        </div>
        <label>
          Department
          <select value={departmentId} onChange={change(setDepartmentId)}>
            <option value="">All Departments</option>
            {(departments.data?.items ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Specialization
          <select value={activeSpecialization} onChange={change(setSpecialization)}>
            <option value="">All Specializations</option>
            {specializationOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>

      {firstPage.error ? (
        <div className="booking-error">
          <Alert>{firstPage.error}</Alert>
        </div>
      ) : !ready && !firstPage.data ? (
        <LoadingCards />
      ) : items.length === 0 && !pinned ? (
        <div className="empty booking-no-results" role="status">
          {hasFilters ? (
            <>
              <p>No doctors match your search.</p>
              <button type="button" className="secondary" onClick={clearFilters}>
                <RotateCcw size={16} aria-hidden="true" /> Clear filters
              </button>
            </>
          ) : (
            <p>No doctors are taking online bookings at the moment.</p>
          )}
        </div>
      ) : (
        <>
          <p className="muted small" aria-live="polite">
            {total} {total === 1 ? "doctor" : "doctors"} found
          </p>
          <div className="doctor-options" role="radiogroup" aria-label="Doctors" aria-busy={firstPage.loading}>
            {pinned && <DoctorOption key={pinned.id} doctor={pinned} checked onChoose={onSelect} />}
            {items.map((doctor) => (
              <DoctorOption key={doctor.id} doctor={doctor} checked={selected?.id === doctor.id} onChoose={onSelect} />
            ))}
          </div>
          <Alert>{extra.error}</Alert>
          {items.length < total && (
            <div className="booking-more">
              <button type="button" className="secondary" onClick={loadMore} disabled={extra.loading}>
                {extra.loading ? "Loading…" : "Show more doctors"}
              </button>
            </div>
          )}
        </>
      )}

      <div className="booking-actions">
        <button type="button" className="secondary" onClick={onBack}>
          <ArrowLeft size={17} aria-hidden="true" /> Back
        </button>
        <button type="button" disabled={!selected} onClick={onContinue}>
          Continue <ArrowRight size={17} aria-hidden="true" />
        </button>
      </div>
    </>
  );
}
