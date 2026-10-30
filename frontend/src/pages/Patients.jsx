import { ArrowUpDown, ChevronDown, ChevronUp, CircleAlert, CircleCheck, Plus, Search, SearchX, Users } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import ActionMenu from "../components/ActionMenu";
import Alert from "../components/Alert";
import Avatar from "../components/Avatar";
import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import NumberedPager from "../components/NumberedPager";
import AddPatientDialog from "../components/patients/AddPatientDialog";
import DateRangeFilter from "../components/patients/DateRangeFilter";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { listDoctors } from "../services/doctorService";
import { activatePatient, bulkSetPatientStatus, deactivatePatient, listPatients } from "../services/patientService";
import { doctorName } from "../utils/format";
import { ageFromDateOfBirth, patientFullName, SEX_LABELS, SEX_OPTIONS } from "../utils/patient";

const PAGE_SIZE = 10;
const SEARCH_DELAY_MS = 350;
const STATUSES = { active: "true", inactive: "false" };
const dateOnly = (value) => (/^\d{4}-\d{2}-\d{2}$/.test(value ?? "") ? value : "");
const registered = (iso) => new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(iso));

function PatientStatus({ active }) {
  return active ? (
    <span className="badge ok with-icon">
      <CircleCheck size={14} aria-hidden="true" /> Active
    </span>
  ) : (
    <span className="badge danger with-icon">
      <CircleAlert size={14} aria-hidden="true" /> Inactive
    </span>
  );
}

const SORT_COLUMNS = { name: "Patient", mrn: "MRN", email: "Email", phone: "Phone", status: "Status" };
const SORTS = new Set(Object.keys(SORT_COLUMNS).flatMap((k) => [k, `-${k}`]));

function SortHeader({ sort, field, onSort }) {
  const state = sort === field ? "ascending" : sort === `-${field}` ? "descending" : "none";
  const Icon = state === "ascending" ? ChevronUp : state === "descending" ? ChevronDown : ArrowUpDown;
  return (
    <th scope="col" aria-sort={state}>
      <button type="button" className="sort-button" onClick={() => onSort(sort === field ? `-${field}` : field)}>
        {SORT_COLUMNS[field]} <Icon size={15} aria-hidden="true" />
      </button>
    </th>
  );
}

function SelectAll({ checked, indeterminate, onChange, disabled }) {
  const box = useRef(null);
  useEffect(() => {
    if (box.current) box.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <input
      ref={box}
      type="checkbox"
      checked={checked}
      onChange={onChange}
      disabled={disabled}
      aria-label="Select all patients on this page"
    />
  );
}

/**
 * Front-desk patient records (D80): search, status / doctor / registration
 * date filters, paging and the actions the caller's permissions allow. The
 * URL keeps the filters and page; the search text (names, phone numbers)
 * stays out of it.
 */
export default function Patients() {
  const { can } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const status = STATUSES[searchParams.get("status")] ? searchParams.get("status") : "";
  const doctorId = searchParams.get("doctor") ?? "";
  const from = dateOnly(searchParams.get("from"));
  const to = dateOnly(searchParams.get("to"));
  const gender = SEX_OPTIONS.includes(searchParams.get("gender")) ? searchParams.get("gender") : "";
  const sort = SORTS.has(searchParams.get("sort")) ? searchParams.get("sort") : "name";
  const page = Math.max(1, Number(searchParams.get("page")) || 1);

  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  // The request whose answer is on screen; loading while it differs from the current one.
  const [loadedKey, setLoadedKey] = useState(null);
  const [doctors, setDoctors] = useState([]);
  const [selected, setSelected] = useState(() => new Set());
  const [adding, setAdding] = useState(false);
  const [created, setCreated] = useState(null);
  const [notice, setNotice] = useState("");
  const [statusChange, setStatusChange] = useState(null);
  const [statusError, setStatusError] = useState("");
  const [statusBusy, setStatusBusy] = useState(false);
  const [bulk, setBulk] = useState(null); // true = activate, false = deactivate
  const [bulkFailures, setBulkFailures] = useState([]);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  useEffect(() => {
    listDoctors({ page_size: 100, sort: "name_asc" })
      .then((res) => setDoctors(res.data.items))
      .catch(() => setDoctors([]));
  }, []);

  const params = { page, page_size: PAGE_SIZE };
  if (q.trim()) params.q = q.trim();
  if (status) params.is_active = STATUSES[status];
  if (doctorId) params.doctor_id = doctorId;
  if (from) params.registered_from = from;
  if (to) params.registered_to = to;
  if (gender) params.sex_at_birth = gender;
  if (sort !== "name") params.sort = sort;
  const requestKey = `${JSON.stringify(params)}#${attempt}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    const [query] = requestKey.split("#");
    listPatients(JSON.parse(query))
      .then((res) => {
        if (cancelled) return;
        setData(res.data);
        setError("");
        setSelected(new Set()); // selection is for the rows on screen only
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err, "Could not load patients")))
      .finally(() => !cancelled && setLoadedKey(requestKey));
    return () => {
      cancelled = true;
    };
  }, [requestKey]);

  const update = (changes) => {
    const next = { status, doctor: doctorId, from, to, gender, sort: sort === "name" ? "" : sort, page, ...changes };
    const params = new URLSearchParams();
    for (const key of ["status", "doctor", "from", "to", "gender", "sort"]) if (next[key]) params.set(key, next[key]);
    if (next.page > 1) params.set("page", String(next.page));
    setSearchParams(params);
  };
  const onSearch = (value) => {
    setTyped(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setQ(value);
      update({ page: 1 });
    }, SEARCH_DELAY_MS);
  };
  const clearFilters = () => {
    clearTimeout(timer.current);
    setTyped("");
    setQ("");
    setSearchParams(new URLSearchParams());
  };

  const items = data?.items ?? [];
  const filtered = Boolean(q.trim() || status || doctorId || from || to || gender);
  const allSelected = items.length > 0 && items.every((p) => selected.has(p.id));
  const someSelected = items.some((p) => selected.has(p.id));
  const toggle = (id) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const changeStatus = async () => {
    setStatusBusy(true);
    setStatusError("");
    const { patient } = statusChange;
    try {
      await (patient.is_active ? deactivatePatient(patient.id) : activatePatient(patient.id));
      setStatusChange(null);
      setNotice(`${patientFullName(patient)} is now ${patient.is_active ? "inactive" : "active"}.`);
      setAttempt((n) => n + 1);
    } catch (err) {
      setStatusError(getErrorMessage(err, "Could not change the patient's status"));
    } finally {
      setStatusBusy(false);
    }
  };

  const openBulk = (active) => {
    setStatusError("");
    setNotice("");
    setBulkFailures([]);
    setBulk(active);
  };
  const runBulk = async () => {
    setStatusBusy(true);
    setStatusError("");
    try {
      const res = await bulkSetPatientStatus([...selected], bulk);
      const nameOf = (id) => {
        const p = items.find((x) => x.id === id);
        return p ? patientFullName(p) : "A patient";
      };
      const done = res.data.filter((r) => r.ok).length;
      const failed = res.data.filter((r) => !r.ok);
      setNotice(
        `${done} patient${done === 1 ? "" : "s"} ${bulk ? "activated" : "deactivated"}.` +
          (failed.length ? ` ${failed.length} could not be changed:` : "")
      );
      setBulkFailures(failed.map((r) => `${nameOf(r.patient_id)}: ${r.message}`));
      setBulk(null);
      setAttempt((n) => n + 1);
    } catch (err) {
      setStatusError(getErrorMessage(err, "Could not change the selected patients"));
    } finally {
      setStatusBusy(false);
    }
  };

  const actionsFor = (p) => {
    const name = patientFullName(p);
    return [
      { label: "View Patient Details", to: `/patients/${p.id}` },
      can("patient:update") && { label: "Edit Patient Information", to: `/patients/${p.id}?edit=1` },
      can("appointment:create") && p.is_active && { label: "Book Appointment", to: `/appointments/book?patient=${p.id}` },
      can("appointment:read_any") && { label: "View Appointments", to: `/appointments?patient=${p.id}` },
      can("patient:deactivate") && {
        label: p.is_active ? "Deactivate Patient" : "Reactivate Patient",
        danger: p.is_active,
        onSelect: () => {
          setStatusError("");
          setNotice("");
          setStatusChange({ patient: p, name });
        },
      },
    ].filter(Boolean);
  };

  const countLine = data && data.total > 0 && (
    <p className="muted patients-count" aria-live="polite">
      Showing {(page - 1) * PAGE_SIZE + 1} to {Math.min(page * PAGE_SIZE, data.total)} of {data.total} patient
      {data.total === 1 ? "" : "s"}
    </p>
  );

  return (
    <div className="patients-page">
      <header className="patients-head">
        <div className="schedule-head">
          <h1>Patients</h1>
          <p className="muted">Manage all clinic patients.</p>
        </div>
        {can("patient:create") && (
          <button
            type="button"
            className="add-patient"
            onClick={() => {
              setNotice("");
              setCreated(null);
              setAdding(true);
            }}
          >
            <Plus size={20} aria-hidden="true" /> Add Patient
          </button>
        )}
      </header>

      <div className="patients-toolbar">
        <div className="appt-search patients-search">
          <Search size={20} aria-hidden="true" />
          <input
            type="search"
            aria-label="Search patients by name, MRN, phone or email"
            placeholder="Search by name, MRN, phone or email..."
            value={typed}
            maxLength={100}
            onChange={(e) => onSearch(e.target.value)}
          />
        </div>
        <label className="patients-filter">
          <span className="sr-only">Status</span>
          <select value={status} onChange={(e) => update({ status: e.target.value, page: 1 })}>
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
        <label className="patients-filter">
          <span className="sr-only">Doctor</span>
          <select value={doctorId} onChange={(e) => update({ doctor: e.target.value, page: 1 })}>
            <option value="">All Doctors</option>
            {doctors.map((d) => (
              <option key={d.id} value={d.id}>
                {doctorName(d)}
              </option>
            ))}
          </select>
        </label>
        <label className="patients-filter">
          <span className="sr-only">Gender</span>
          <select value={gender} onChange={(e) => update({ gender: e.target.value, page: 1 })}>
            <option value="">All Genders</option>
            {SEX_OPTIONS.filter((s) => s !== "unknown").map((s) => (
              <option key={s} value={s}>
                {SEX_LABELS[s]}
              </option>
            ))}
            <option value="unknown">Not recorded</option>
          </select>
        </label>
        <DateRangeFilter label="Registration date" from={from} to={to} onChange={(range) => update({ ...range, page: 1 })} />
      </div>
      {doctorId && <p className="muted small patients-hint">Showing patients who have an appointment with the selected doctor.</p>}

      <div aria-live="polite">
        <Alert kind={bulkFailures.length ? "warn" : "success"}>
          {notice}
          {bulkFailures.length > 0 && (
            <ul className="bulk-failures">
              {bulkFailures.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
          {created && (
            <>
              {patientFullName(created)} was registered with MRN {created.mrn}.{" "}
              <Link to={`/patients/${created.id}`}>View patient record</Link>
            </>
          )}
        </Alert>
      </div>

      <section className="card patients-card" aria-label="Patient records" aria-busy={loading}>
        {countLine}
        {someSelected && (
          <div className="selection-bar" role="status">
            <strong>
              {selected.size} patient{selected.size === 1 ? "" : "s"} selected on this page.
            </strong>{" "}
            {can("patient:deactivate") ? (
              <>
                <button type="button" className="secondary small-button" onClick={() => openBulk(true)}>
                  Activate
                </button>
                <button type="button" className="danger small-button" onClick={() => openBulk(false)}>
                  Deactivate
                </button>
              </>
            ) : (
              <span className="muted">Open a patient to act on their record.</span>
            )}
            <button type="button" className="link-button" onClick={() => setSelected(new Set())}>
              Clear selection
            </button>
          </div>
        )}

        {error ? (
          <div role="alert" className="appt-error">
            <p>{error}</p>
            <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </button>
          </div>
        ) : loading && !data ? (
          <div role="status" aria-label="Loading patients">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton appt-skeleton" />
            ))}
          </div>
        ) : items.length === 0 ? (
          filtered ? (
            <EmptyState
              icon={SearchX}
              action={
                <button type="button" className="secondary" onClick={clearFilters}>
                  Clear search and filters
                </button>
              }
            >
              No patients match your search or filters.
            </EmptyState>
          ) : (
            <EmptyState icon={Users}>No patients have been registered yet.</EmptyState>
          )
        ) : (
          <>
            <div className="appt-table-wrap">
              <table className="patients-table">
                <thead>
                  <tr>
                    <th scope="col" className="check-col">
                      <SelectAll
                        checked={allSelected}
                        indeterminate={someSelected && !allSelected}
                        onChange={() => setSelected(allSelected ? new Set() : new Set(items.map((p) => p.id)))}
                      />
                    </th>
                    <SortHeader sort={sort} field="name" onSort={(s) => update({ sort: s, page: 1 })} />
                    <SortHeader sort={sort} field="mrn" onSort={(s) => update({ sort: s, page: 1 })} />
                    <SortHeader sort={sort} field="email" onSort={(s) => update({ sort: s, page: 1 })} />
                    <SortHeader sort={sort} field="phone" onSort={(s) => update({ sort: s, page: 1 })} />
                    <SortHeader sort={sort} field="status" onSort={(s) => update({ sort: s, page: 1 })} />
                    <th scope="col">Registered On</th>
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                      <span aria-hidden="true">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((p) => {
                    const name = patientFullName(p);
                    const age = ageFromDateOfBirth(p.date_of_birth);
                    const sex = p.sex_at_birth !== "unknown" ? SEX_LABELS[p.sex_at_birth] : null;
                    return (
                      <tr key={p.id} className={selected.has(p.id) ? "is-selected" : ""}>
                        <td className="check-col">
                          <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggle(p.id)} aria-label={`Select ${name}`} />
                        </td>
                        <td data-label="Name">
                          <div className="appt-patient">
                            <Avatar name={name} role="patient" src={p.photo_url} size={44} alt={`Photo of ${name}`} />
                            <div>
                              <Link to={`/patients/${p.id}`} className="patient-name">
                                {name}
                              </Link>
                              <span className="muted small">{[age != null && `${age} years`, sex].filter(Boolean).join(" · ")}</span>
                            </div>
                          </div>
                        </td>
                        <td data-label="MRN">{p.mrn}</td>
                        <td data-label="Email" className="email-cell">
                          {p.email || <span className="muted">Not provided</span>}
                        </td>
                        <td data-label="Phone">{p.phone || <span className="muted">Not provided</span>}</td>
                        <td data-label="Status">
                          <PatientStatus active={p.is_active} />
                        </td>
                        <td data-label="Registered On">
                          <time dateTime={p.created_at}>{registered(p.created_at)}</time>
                        </td>
                        <td className="row-menu">
                          <ActionMenu label={`Actions for ${name}`} items={actionsFor(p)} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <NumberedPager page={page} pageSize={PAGE_SIZE} total={data.total} noun="patients" onChange={(p) => update({ page: p })} />
          </>
        )}
      </section>

      {adding && (
        <AddPatientDialog
          onClose={() => setAdding(false)}
          onCreated={(patient) => {
            setAdding(false);
            setCreated(patient);
            setAttempt((n) => n + 1);
          }}
        />
      )}

      {bulk !== null && (
        <ConfirmDialog
          title={bulk ? "Activate selected patients?" : "Deactivate selected patients?"}
          confirmLabel={bulk ? "Activate" : "Deactivate"}
          danger={!bulk}
          busy={statusBusy}
          error={statusError}
          onConfirm={runBulk}
          onCancel={() => setBulk(null)}
        >
          <p>
            {selected.size} patient{selected.size === 1 ? "" : "s"} selected on this page will be {bulk ? "activated" : "deactivated"}.
            {!bulk && " A patient with upcoming appointments is skipped; nothing is cancelled or deleted, and MRNs never change."}
          </p>
        </ConfirmDialog>
      )}

      {statusChange && (
        <ConfirmDialog
          title={statusChange.patient.is_active ? "Deactivate patient?" : "Reactivate patient?"}
          confirmLabel={statusChange.patient.is_active ? "Deactivate" : "Reactivate"}
          danger={statusChange.patient.is_active}
          busy={statusBusy}
          error={statusError}
          onConfirm={changeStatus}
          onCancel={() => setStatusChange(null)}
        >
          <p>
            {statusChange.patient.is_active
              ? `${statusChange.name} will no longer be offered for new bookings. The record is kept and can be reactivated.`
              : `${statusChange.name} can be booked again.`}
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
