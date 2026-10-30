import { Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getErrorMessage } from "../../services/api";
import { globalSearch } from "../../services/workspaceService";
import { STATUS_LABELS } from "../../utils/appointments";
import { formatSlotTime } from "../../utils/datetime";
import { roleLabel } from "../../routes/navigation";

const MIN_LENGTH = 2;
const DELAY_MS = 300;
const shortDate = (iso, timeZone) =>
  new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone }).format(new Date(iso));

// The API's sections as one ordered list of options, each with where it goes.
function optionsFrom(results) {
  if (!results) return [];
  const section = (name, items, describe) => (items ?? []).map((item) => ({ section: name, id: item.id, ...describe(item) }));
  return [
    ...section("Patients", results.patients, (p) => ({ to: `/patients/${p.id}`, title: p.name, detail: p.mrn })),
    ...section("Doctors", results.doctors, (d) => ({ to: `/doctors/${d.id}`, title: d.name, detail: d.specialization })),
    ...section("Appointments", results.appointments, (a) => ({
      to: `/appointments/${a.id}`,
      title: `${a.patient_name} · ${a.doctor_name}`,
      detail: `${shortDate(a.starts_at, a.timezone)} ${formatSlotTime(a.starts_at, a.timezone)} · ${STATUS_LABELS[a.status] ?? a.status}`,
    })),
    ...section("Users", results.users, (u) => ({
      to: `/admin/users?q=${encodeURIComponent(u.email)}`,
      title: u.name,
      detail: `${roleLabel(u.roles)} · ${u.email}`,
    })),
  ];
}

/**
 * Header search across what the signed-in user may see (D86): patients,
 * doctors, appointments and users, from one server-side search. Combobox
 * pattern: arrows move, Enter opens, Escape closes.
 */
export default function GlobalSearch() {
  const navigate = useNavigate();
  const listId = useId();
  const box = useRef(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState({ term: "", data: null, error: "" });
  const [active, setActive] = useState(-1);
  const term = query.trim();
  const ready = term.length >= MIN_LENGTH;

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      globalSearch(term)
        .then((res) => !cancelled && setResult({ term, data: res.data, error: "" }))
        .catch((err) => !cancelled && setResult({ term, data: null, error: getErrorMessage(err, "Search is not available right now") }));
    }, DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [term, ready]);

  useEffect(() => {
    if (!open) return;
    const outside = (e) => !box.current?.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [open]);

  const loading = ready && result.term !== term;
  const options = ready && !loading ? optionsFrom(result.data) : [];
  const go = (option) => {
    setOpen(false);
    setQuery("");
    setActive(-1);
    navigate(option.to);
  };
  const onKeyDown = (e) => {
    if (e.key === "ArrowDown" && options.length) {
      e.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % options.length);
    } else if (e.key === "ArrowUp" && options.length) {
      e.preventDefault();
      setActive((i) => (i <= 0 ? options.length - 1 : i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const option = options[active] ?? options[0];
      if (option) go(option);
    } else if (e.key === "Escape") {
      setOpen(false);
      setActive(-1);
    }
  };

  let lastSection = null;
  return (
    <div className="search global-search" ref={box} role="search">
      <Search size={18} aria-hidden="true" />
      <input
        type="search"
        role="combobox"
        aria-label="Search patients, doctors, appointments and users"
        aria-expanded={open && ready}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 && options[active] ? `${listId}-${active}` : undefined}
        placeholder="Search patients, doctors, appointments, users..."
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(-1);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {open && ready && (
        <div className="search-results card" id={listId} role="listbox" aria-label="Search results">
          {loading ? (
            <p className="muted small search-state" role="status">
              Searching…
            </p>
          ) : result.error ? (
            <p className="field-error search-state" role="alert">
              {result.error}
            </p>
          ) : options.length === 0 ? (
            <p className="muted small search-state" role="status">
              No results for “{term}”.
            </p>
          ) : (
            options.map((option, index) => {
              const heading = option.section !== lastSection ? option.section : null;
              lastSection = option.section;
              return (
                <div key={`${option.section}-${option.id}`}>
                  {heading && <p className="search-section" aria-hidden="true">{heading}</p>}
                  <div
                    id={`${listId}-${index}`}
                    role="option"
                    aria-selected={index === active}
                    aria-label={`${option.section}: ${option.title}, ${option.detail}`}
                    className={`search-option${index === active ? " active" : ""}`}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => go(option)}
                    onMouseEnter={() => setActive(index)}
                  >
                    <strong>{option.title}</strong>
                    <span className="muted small">{option.detail}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
