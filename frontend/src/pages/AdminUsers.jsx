import { ArrowUpDown, ChevronDown, ChevronUp, CircleAlert, CircleCheck, Plus, Search, SearchX, Users } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import ActionMenu from "../components/ActionMenu";
import Alert from "../components/Alert";
import Avatar from "../components/Avatar";
import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import NumberedPager from "../components/NumberedPager";
import AdministratorAccess, { RevokeRoleDialog } from "../components/admin/AdministratorAccess";
import { AddUserDialog, EditUserDialog, RoleBadges, RolesDialog, UserDetailsDialog } from "../components/admin/UserDialogs";
import AddPatientDialog from "../components/patients/AddPatientDialog";
import DateRangeFilter from "../components/patients/DateRangeFilter";
import { useAuth } from "../context/useAuth";
import { getErrorMessage } from "../services/api";
import { activateUser, bulkSetUserStatus, deactivateUser, listRoles, listUsers } from "../services/userService";
import { avatarRole, bulkSummary, DATE_PRESETS, joinedOn, nextSort, presetRange, SORTABLE, sortState } from "../utils/adminUsers";

const PAGE_SIZE = 10;
const SEARCH_DELAY_MS = 350;
const ROLE_ORDER = ["admin", "doctor", "receptionist", "patient"];

function StatusBadge({ active }) {
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

function SelectAll({ checked, indeterminate, onChange }) {
  const box = useRef(null);
  useEffect(() => {
    if (box.current) box.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return <input ref={box} type="checkbox" checked={checked} onChange={onChange} aria-label="Select all users on this page" />;
}

function SortHeader({ sort, field, onSort }) {
  const state = sortState(sort, field);
  const Icon = state === "ascending" ? ChevronUp : state === "descending" ? ChevronDown : ArrowUpDown;
  return (
    <th scope="col" aria-sort={state}>
      <button type="button" className="sort-button" onClick={() => onSort(nextSort(sort, field))}>
        {SORTABLE[field]} <Icon size={15} aria-hidden="true" />
      </button>
    </th>
  );
}

/**
 * Admin > Users (D88): every account, with search (name, email, phone),
 * role / status / joined-date filters, server-side sorting and paging, bulk
 * activation, and the per-user actions the caller's permissions allow.
 * Administrators are added only through invitations (D87).
 */
export default function AdminUsers() {
  const { user: me, can } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // `?q=` arrives from the global search's user results.
  const [typed, setTyped] = useState(() => searchParams.get("q") ?? "");
  const [q, setQ] = useState(() => searchParams.get("q") ?? "");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [datePreset, setDatePreset] = useState("all");
  const [range, setRange] = useState({ from: "", to: "" });
  const [sort, setSort] = useState("name");
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState(null);
  const [loadedKey, setLoadedKey] = useState(null);
  const [error, setError] = useState("");
  const [roles, setRoles] = useState([]);
  const [selected, setSelected] = useState(() => new Set());
  const [notice, setNotice] = useState(null); // {text, failed?}
  const [actionError, setActionError] = useState("");
  const [dialog, setDialog] = useState(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  useEffect(() => {
    listRoles()
      .then((res) => setRoles(res.data))
      .catch(() => setRoles([]));
  }, []);

  const params = { page, page_size: PAGE_SIZE, sort };
  if (q.trim()) params.q = q.trim();
  if (role) params.role = role;
  if (status) params.is_active = status === "active";
  if (range.from) params.joined_from = range.from;
  if (range.to) params.joined_to = range.to;
  const requestKey = `${JSON.stringify(params)}#${attempt}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    const [query] = requestKey.split("#");
    listUsers(JSON.parse(query))
      .then((res) => {
        if (cancelled) return;
        setData(res.data);
        setError("");
        setSelected(new Set()); // selection is for the rows on screen only
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err, "Could not load users")))
      .finally(() => !cancelled && setLoadedKey(requestKey));
    return () => {
      cancelled = true;
    };
  }, [requestKey]);

  const refresh = () => setAttempt((n) => n + 1);
  const filter = (apply) => {
    apply();
    setPage(1);
  };
  const onSearch = (value) => {
    setTyped(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => filter(() => setQ(value)), SEARCH_DELAY_MS);
  };
  const onPreset = (value) =>
    filter(() => {
      setDatePreset(value);
      setRange(value === "custom" ? { from: "", to: "" } : presetRange(value));
    });
  const clearFilters = () => {
    clearTimeout(timer.current);
    setTyped("");
    filter(() => {
      setQ("");
      setRole("");
      setStatus("");
      setDatePreset("all");
      setRange({ from: "", to: "" });
    });
  };

  const items = data?.items ?? [];
  const filtered = Boolean(q.trim() || role || status || range.from || range.to);
  const selectable = items.filter((u) => u.id !== me.id);
  const allSelected = selectable.length > 0 && selectable.every((u) => selected.has(u.id));
  const someSelected = selectable.some((u) => selected.has(u.id));
  const toggle = (id) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const open = (kind, user) => {
    setActionError("");
    setNotice(null);
    setDialog({ kind, user });
  };
  const finish = (text, failed = []) => {
    setDialog(null);
    setBusy(false);
    setNotice({ text, failed });
    refresh();
  };

  const changeStatus = async () => {
    const { user } = dialog;
    setBusy(true);
    setActionError("");
    try {
      await (user.is_active ? deactivateUser(user.id) : activateUser(user.id));
      finish(`${user.name} is now ${user.is_active ? "inactive" : "active"}.`);
    } catch (err) {
      setActionError(getErrorMessage(err, "Could not change the account status"));
      setBusy(false);
    }
  };

  const bulk = async (active) => {
    setBusy(true);
    setActionError("");
    const ids = [...selected];
    try {
      const res = await bulkSetUserStatus(ids, active);
      const nameOf = (id) => items.find((u) => u.id === id)?.name ?? "A user";
      const summary = bulkSummary(res.data, active, nameOf);
      finish(summary.text, summary.failed);
    } catch (err) {
      setActionError(getErrorMessage(err, "Could not change the selected users"));
      setBusy(false);
    }
  };

  const actionsFor = (u) => {
    const self = u.id === me.id;
    const isAdmin = u.roles.includes("admin");
    return [
      { label: "View User", onSelect: () => open("view", u) },
      can("user:update") && { label: "Edit User", onSelect: () => open("edit", u) },
      can("user:assign_role") && { label: "Manage Roles", onSelect: () => open("roles", u) },
      u.doctor_id && { label: "Open Doctor Profile", to: `/doctors/${u.doctor_id}` },
      u.patient_id && can("patient:read_any") && { label: "Open Patient Record", to: `/patients/${u.patient_id}` },
      can("user:deactivate") && !self && {
        label: u.is_active ? "Deactivate User" : "Activate User",
        danger: u.is_active,
        onSelect: () => open("status", u),
      },
      can("user:assign_role") && isAdmin && !self && {
        label: "Remove Administrator Role",
        danger: true,
        onSelect: () => open("revoke-admin", u),
      },
    ].filter(Boolean);
  };

  const canAdd = can("user:create") || can("patient:create") || can("doctor:create") || can("admin_invitation:manage");
  const roleOptions = [...roles].sort((a, b) => (ROLE_ORDER.indexOf(a.code) + 1 || 99) - (ROLE_ORDER.indexOf(b.code) + 1 || 99));

  return (
    <div className="patients-page users-page">
      <header className="patients-head">
        <div className="schedule-head">
          <h1>Users</h1>
          <p className="muted">Manage all system users including doctors, receptionists and patients.</p>
        </div>
        {canAdd && (
          <button type="button" className="add-patient" onClick={() => open("add")}>
            <Plus size={20} aria-hidden="true" /> Add User
          </button>
        )}
      </header>

      <div className="card users-toolbar">
        <div className="appt-search patients-search">
          <Search size={20} aria-hidden="true" />
          <input
            type="search"
            aria-label="Search users by name, email or phone"
            placeholder="Search users by name, email or phone..."
            value={typed}
            maxLength={100}
            onChange={(e) => onSearch(e.target.value)}
          />
        </div>
        <label className="patients-filter">
          <span className="sr-only">Role</span>
          <select value={role} onChange={(e) => filter(() => setRole(e.target.value))}>
            <option value="">All Roles</option>
            {roleOptions.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label className="patients-filter">
          <span className="sr-only">Status</span>
          <select value={status} onChange={(e) => filter(() => setStatus(e.target.value))}>
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </label>
        <label className="patients-filter">
          <span className="sr-only">Joined date</span>
          <select value={datePreset} onChange={(e) => onPreset(e.target.value)}>
            {Object.entries(DATE_PRESETS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {datePreset === "custom" && (
          <DateRangeFilter label="Joined date" from={range.from} to={range.to} onChange={(r) => filter(() => setRange(r))} />
        )}
        {filtered && (
          <button type="button" className="link-button" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </div>

      <div aria-live="polite">
        {notice && (
          <Alert kind={notice.failed.length ? "warn" : "success"}>
            {notice.text}
            {notice.failed.length > 0 && (
              <ul className="bulk-failures">
                {notice.failed.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
          </Alert>
        )}
        {!dialog && <Alert>{actionError}</Alert>}
      </div>

      <section className="card patients-card" aria-label="User accounts" aria-busy={loading}>
        {someSelected && (
          <div className="selection-bar" role="status">
            <strong>
              {selected.size} user{selected.size === 1 ? "" : "s"} selected
            </strong>
            {can("user:deactivate") && (
              <>
                <button type="button" className="secondary small-button" onClick={() => open("bulk-activate")}>
                  Activate
                </button>
                <button type="button" className="danger small-button" onClick={() => open("bulk-deactivate")}>
                  Deactivate
                </button>
              </>
            )}
            <button type="button" className="link-button" onClick={() => setSelected(new Set())}>
              Clear selection
            </button>
          </div>
        )}

        {error ? (
          <div role="alert" className="appt-error">
            <p>{error}</p>
            <button type="button" className="secondary" onClick={refresh}>
              Try again
            </button>
          </div>
        ) : loading && !data ? (
          <div role="status" aria-label="Loading users">
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
              No users match your search or filters.
            </EmptyState>
          ) : (
            <EmptyState icon={Users}>No users yet.</EmptyState>
          )
        ) : (
          <>
            <div className="appt-table-wrap">
              <table className="patients-table users-table">
                <thead>
                  <tr>
                    <th scope="col" className="check-col">
                      <SelectAll
                        checked={allSelected}
                        indeterminate={someSelected && !allSelected}
                        onChange={() => setSelected(allSelected ? new Set() : new Set(selectable.map((u) => u.id)))}
                      />
                    </th>
                    <SortHeader sort={sort} field="name" onSort={(s) => filter(() => setSort(s))} />
                    <SortHeader sort={sort} field="email" onSort={(s) => filter(() => setSort(s))} />
                    <SortHeader sort={sort} field="role" onSort={(s) => filter(() => setSort(s))} />
                    <SortHeader sort={sort} field="status" onSort={(s) => filter(() => setSort(s))} />
                    <SortHeader sort={sort} field="created_at" onSort={(s) => filter(() => setSort(s))} />
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((u) => (
                    <tr key={u.id} className={selected.has(u.id) ? "is-selected" : ""}>
                      <td className="check-col">
                        {u.id !== me.id && (
                          <input type="checkbox" checked={selected.has(u.id)} onChange={() => toggle(u.id)} aria-label={`Select ${u.name}`} />
                        )}
                      </td>
                      <td data-label="Name">
                        <div className="appt-patient">
                          <Avatar name={u.name} role={avatarRole(u)} src={u.photo_url} size={44} alt={`Photo of ${u.name}`} />
                          <div>
                            <button type="button" className="link-button patient-name" onClick={() => open("view", u)}>
                              {u.name}
                              {u.id === me.id && <span className="muted"> (you)</span>}
                            </button>
                            <span className="muted small">{u.phone || "No phone"}</span>
                          </div>
                        </div>
                      </td>
                      <td data-label="Email" className="email-cell">
                        {u.email}
                      </td>
                      <td data-label="Role">
                        <RoleBadges codes={u.roles} roles={roles} />
                      </td>
                      <td data-label="Status">
                        <StatusBadge active={u.is_active} />
                      </td>
                      <td data-label="Joined On">
                        <time dateTime={u.created_at}>{joinedOn(u.created_at)}</time>
                      </td>
                      <td className="row-menu">
                        <ActionMenu label={`Actions for ${u.name}`} items={actionsFor(u)} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <NumberedPager page={page} pageSize={PAGE_SIZE} total={data.total} noun="users" onChange={setPage} />
          </>
        )}
      </section>

      {can("admin_invitation:manage") && (
        <AdministratorAccess
          inviting={dialog?.kind === "invite"}
          onInviteClose={() => setDialog(null)}
          onNotice={(text) => setNotice({ text, failed: [] })}
        />
      )}

      {dialog?.kind === "add" && (
        <AddUserDialog
          can={can}
          onClose={() => setDialog(null)}
          onPatient={() => setDialog({ kind: "add-patient" })}
          onDoctor={() => navigate("/admin/doctors")}
          onAdmin={() => setDialog({ kind: "invite" })}
          onCreated={async (created, active) => {
            let text = `Created ${created.name} (${created.email}).`;
            if (!active) {
              try {
                await deactivateUser(created.id);
                text += " The account is inactive.";
              } catch (err) {
                text += ` It could not be set inactive: ${getErrorMessage(err)}`;
              }
            }
            finish(text);
          }}
        />
      )}
      {dialog?.kind === "add-patient" && (
        <AddPatientDialog
          onClose={() => setDialog(null)}
          onCreated={(patient) => finish(`Patient registered with MRN ${patient.mrn}.`)}
        />
      )}
      {dialog?.kind === "view" && <UserDetailsDialog user={dialog.user} roles={roles} onClose={() => setDialog(null)} />}
      {dialog?.kind === "edit" && (
        <EditUserDialog user={dialog.user} onClose={() => setDialog(null)} onSaved={(u) => finish(`Saved ${u.name}.`)} />
      )}
      {dialog?.kind === "roles" && (
        <RolesDialog user={dialog.user} roles={roles} onClose={() => setDialog(null)} onSaved={(u) => finish(`Roles updated for ${u.name}.`)} />
      )}
      {dialog?.kind === "revoke-admin" && (
        <RevokeRoleDialog admin={dialog.user} onClose={() => setDialog(null)} onDone={(text) => finish(text)} />
      )}
      {dialog?.kind === "status" && (
        <ConfirmDialog
          title={dialog.user.is_active ? "Deactivate user?" : "Activate user?"}
          confirmLabel={dialog.user.is_active ? "Deactivate" : "Activate"}
          danger={dialog.user.is_active}
          busy={busy}
          error={actionError}
          onConfirm={changeStatus}
          onCancel={() => setDialog(null)}
        >
          <p>
            {dialog.user.is_active
              ? `${dialog.user.name} will be signed out everywhere and cannot sign in. Their appointments and records are kept.`
              : `${dialog.user.name} will be able to sign in again.`}
          </p>
        </ConfirmDialog>
      )}
      {(dialog?.kind === "bulk-activate" || dialog?.kind === "bulk-deactivate") && (
        <ConfirmDialog
          title={dialog.kind === "bulk-activate" ? "Activate selected users?" : "Deactivate selected users?"}
          confirmLabel={dialog.kind === "bulk-activate" ? "Activate" : "Deactivate"}
          danger={dialog.kind === "bulk-deactivate"}
          busy={busy}
          error={actionError}
          onConfirm={() => bulk(dialog.kind === "bulk-activate")}
          onCancel={() => setDialog(null)}
        >
          <p>
            {selected.size} user{selected.size === 1 ? "" : "s"} will be {dialog.kind === "bulk-activate" ? "activated" : "deactivated and signed out"}.
            Each account is checked on its own; the last active administrator is never deactivated.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
