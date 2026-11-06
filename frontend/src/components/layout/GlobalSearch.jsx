import { CalendarDays, Search, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/useAuth";
import { getErrorMessage } from "../../services/api";
import { globalSearch } from "../../services/workspaceService";
import { STATUS_LABELS } from "../../utils/appointments";
import { formatSlotTime } from "../../utils/datetime";
import { departmentLink, searchScope } from "../../utils/search";
import { roleLabel } from "../../routes/navigation";
import Avatar from "../Avatar";
import DepartmentIcon from "../departments/DepartmentIcon";

const MIN_LENGTH = 2;
const DELAY_MS = 300;
const shortDate = (iso, timeZone) =>
  new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone }).format(new Date(iso));
const SECTION_TITLES = { patients: "Patients", doctors: "Doctors", departments: "Departments", appointments: "Appointments", users: "Users" };

// The API's sections as one ordered list of options, each with where it goes.
// Only sections the server returned (it leaves the caller's other ones null).
function optionsFrom(results, location) {
  if (!results) return [];
  const section = (key, describe) =>
    (results[key] ?? []).map((item) => ({ section: SECTION_TITLES[key], id: item.id, ...describe(item) }));
  return [
    ...section("patients", (p) => ({
      to: `/patients/${p.id}`,
      title: p.name,
      detail: p.mrn,
      icon: <Avatar name={p.name} size={32} />,
    })),
    ...section("doctors", (d) => ({
      to: `/doctors/${d.id}`,
      title: d.name,
      detail: [d.specialization, d.department_name].filter(Boolean).join(" · "),
      icon: <Avatar name={d.name} role="doctor" src={d.photo_url} size={32} />,
    })),
    ...section("departments", (d) => ({
      to: departmentLink(d.id, location),
      title: d.name,
      detail: d.description || "See this department's doctors",
      icon: <DepartmentIcon department={d} size={32} />,
    })),
    ...section("appointments", (a) => ({
      to: `/appointments/${a.id}`,
      title: `${a.patient_name} · ${a.doctor_name}`,
      detail: `${shortDate(a.starts_at, a.timezone)} ${formatSlotTime(a.starts_at, a.timezone)} · ${STATUS_LABELS[a.status] ?? a.status}`,
      icon: (
        <span className="search-option-glyph" aria-hidden="true">
          <CalendarDays size={16} />
        </span>
      ),
    })),
    ...section("users", (u) => ({
      to: `/admin/users?q=${encodeURIComponent(u.email)}`,
      title: u.name,
      detail: `${roleLabel(u.roles)} · ${u.email}`,
      icon: <Avatar name={u.name} size={32} />,
    })),
  ];
}

/**
 * Header search (D86, D119) over what the signed-in user may open: a patient
 * finds doctors and departments; front desk, doctors and administrators more,
 * as their permissions allow (the server decides; see utils/search.js).
 *
 * A clinic search box, not a credential field: it is a named type="search"
 * input with autocomplete off and no form around it, so browsers have no
 * reason to offer saved logins. Combobox pattern: arrows move, Enter opens,
 * Escape closes (then clears).
 */
export default function GlobalSearch() {
  const navigate = useNavigate();
  const location = useLocation();
  const { can } = useAuth();
  const scope = searchScope(can);
  const listId = useId();
  const hintId = useId();
  const box = useRef(null);
  const input = useRef(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState({ term: "", data: null, error: "" });
  const [active, setActive] = useState(-1);
  const term = query.trim().replace(/\s+/g, " ");
  const ready = term.length >= MIN_LENGTH;

  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      globalSearch(term, { signal: controller.signal })
        .then((res) => !controller.signal.aborted && setResult({ term, data: res.data, error: "" }))
        .catch((err) => {
          if (!controller.signal.aborted) setResult({ term, data: null, error: getErrorMessage(err, "Search is not available right now") });
        });
    }, DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort(); // a newer query replaces this one: drop the request and its answer
    };
  }, [term, ready]);

  useEffect(() => {
    if (!open) return;
    const outside = (e) => !box.current?.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [open]);

  const loading = ready && result.term !== term;
  const options = ready && !loading ? optionsFrom(result.data, location) : [];
  const expanded = open && (ready || query.length > 0);
  const clear = () => {
    setQuery("");
    setActive(-1);
    input.current?.focus();
  };
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
      e.preventDefault();
      if (open) setOpen(false);
      else setQuery("");
      setActive(-1);
    }
  };

  let lastSection = null;
  return (
    <div className="search global-search" ref={box} role="search">
      <Search size={18} aria-hidden="true" />
      <input
        ref={input}
        id="clinic-global-search"
        name="clinic-global-search"
        type="search"
        role="combobox"
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={false}
        enterKeyHint="search"
        aria-label={scope.label}
        aria-describedby={hintId}
        aria-expanded={expanded}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 && options[active] ? `${listId}-${active}` : undefined}
        placeholder={scope.placeholder}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(-1);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      <span id={hintId} className="sr-only">
        Type at least {MIN_LENGTH} characters. Use the arrow keys to choose a result and Enter to open it.
      </span>
      {query && (
        <button type="button" className="search-clear" aria-label="Clear search" onClick={clear}>
          <X size={16} aria-hidden="true" />
        </button>
      )}
      {expanded && (
        <div className="search-results card" id={listId} role="listbox" aria-label="Search results">
          {!ready ? (
            <p className="muted small search-state" role="status">
              Keep typing to search {scope.label.replace(/^Search /, "")}.
            </p>
          ) : loading ? (
            <p className="muted small search-state" role="status">
              Searching…
            </p>
          ) : result.error ? (
            <p className="field-error search-state" role="alert">
              {result.error}
            </p>
          ) : options.length === 0 ? (
            <p className="muted small search-state" role="status">
              No results for “{term}”. Try a name, specialty or department.
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
                    {option.icon}
                    <span className="search-option-text">
                      <strong>{option.title}</strong>
                      <span className="muted small">{option.detail}</span>
                    </span>
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
