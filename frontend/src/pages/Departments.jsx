import { Building2, Search, SearchX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import EmptyState from "../components/EmptyState";
import NumberedPager from "../components/NumberedPager";
import DepartmentCard from "../components/departments/DepartmentCard";
import { getErrorMessage } from "../services/api";
import { getPublicDepartments } from "../services/departmentService";

const PAGE_SIZE = 12;
const SEARCH_DELAY_MS = 350;

/**
 * Departments for patients and visitors (D94): active departments only, as
 * cards with the doctors the public directory lists, searchable by name or
 * description. Read-only: management lives in Admin > Departments. Signed-in
 * users see it inside their own app shell (DirectoryLayout).
 */
export default function Departments() {
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loadedKey, setLoadedKey] = useState(null);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  const params = { page, page_size: PAGE_SIZE };
  if (q.trim()) params.q = q.trim();
  const requestKey = `${JSON.stringify(params)}#${attempt}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    const [query] = requestKey.split("#");
    getPublicDepartments(JSON.parse(query))
      .then((res) => {
        if (cancelled) return;
        setData(res.data);
        setError("");
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err, "Could not load departments")))
      .finally(() => !cancelled && setLoadedKey(requestKey));
    return () => {
      cancelled = true;
    };
  }, [requestKey]);

  const onSearch = (value) => {
    setTyped(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setQ(value);
      setPage(1);
    }, SEARCH_DELAY_MS);
  };
  const clearSearch = () => {
    clearTimeout(timer.current);
    setTyped("");
    setQ("");
    setPage(1);
  };

  const items = data?.items ?? [];
  return (
    <div className="patients-page departments-page">
      <header className="patients-head">
        <div className="dept-title">
          <span className="dept-title-icon" aria-hidden="true">
            <Building2 size={30} />
          </span>
          <div className="schedule-head">
            <h1>Departments</h1>
            <p className="muted">Explore our clinic departments and find the right care for your needs.</p>
          </div>
        </div>
      </header>

      <div className="card users-toolbar">
        <div className="appt-search patients-search">
          <Search size={20} aria-hidden="true" />
          <input
            type="search"
            aria-label="Search departments"
            placeholder="Search departments..."
            value={typed}
            maxLength={100}
            onChange={(e) => onSearch(e.target.value)}
          />
        </div>
      </div>

      <section className="dept-grid-wrap" aria-label="Departments list" aria-busy={loading}>
        {error ? (
          <div role="alert" className="card appt-error">
            <p>{error}</p>
            <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </button>
          </div>
        ) : loading && !data ? (
          <div className="dept-grid" role="status" aria-label="Loading departments">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton dept-card-skeleton" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="card">
            {q.trim() ? (
              <EmptyState
                icon={SearchX}
                action={
                  <button type="button" className="secondary" onClick={clearSearch}>
                    Clear search
                  </button>
                }
              >
                No departments match “{q.trim()}”.
              </EmptyState>
            ) : (
              <EmptyState icon={Building2}>No departments are listed yet.</EmptyState>
            )}
          </div>
        ) : (
          <>
            <ul className="dept-grid">
              {items.map((d) => (
                <DepartmentCard key={d.id} department={d} doctorsTo={`/doctors?department=${d.id}`} emptyDescription="No description available." />
              ))}
            </ul>
            {data.total > PAGE_SIZE && (
              <div className="card dept-pager">
                <NumberedPager page={page} pageSize={PAGE_SIZE} total={data.total} noun="departments" onChange={setPage} />
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
