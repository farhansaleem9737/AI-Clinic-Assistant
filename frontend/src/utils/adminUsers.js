// Helpers for Admin > Users (D88).

// Role badge colours from the design: Administrator purple, Doctor blue,
// Receptionist orange, Patient green; anything else neutral.
export const ROLE_STYLE = {
  admin: { label: "Admin", tone: "role-admin" },
  doctor: { label: "Doctor", tone: "role-doctor" },
  receptionist: { label: "Receptionist", tone: "role-receptionist" },
  patient: { label: "Patient", tone: "role-patient" },
  doctor_applicant: { label: "Doctor applicant", tone: "role-other" },
};

export const roleStyle = (code, roles = []) =>
  ROLE_STYLE[code] ?? { label: roles.find((r) => r.code === code)?.name ?? code, tone: "role-other" };

// Same order the server uses for sorting by role: most privileged first.
const RANK = ["admin", "doctor", "receptionist", "patient", "doctor_applicant"];
export const byRank = (codes) => [...codes].sort((a, b) => (RANK.indexOf(a) + 1 || 99) - (RANK.indexOf(b) + 1 || 99));

// The avatar fallback: the doctor illustration for doctors, initials otherwise.
export const avatarRole = (user) => (user.doctor_id || user.roles.includes("doctor") ? "doctor" : undefined);

export const SORTABLE = { name: "Name", email: "Email", role: "Role", status: "Status", created_at: "Joined On" };

export const nextSort = (current, key) => (current === key ? `-${key}` : key);
export const sortState = (current, key) =>
  current === key ? "ascending" : current === `-${key}` ? "descending" : "none";

export const DATE_PRESETS = { all: "All Dates", today: "Today", "7d": "Last 7 Days", "30d": "Last 30 Days", custom: "Custom Date Range" };

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** {from, to} (inclusive dates) for a preset, relative to `today`. */
export function presetRange(preset, today = new Date()) {
  const back = (days) => {
    const d = new Date(today);
    d.setDate(d.getDate() - days);
    return iso(d);
  };
  switch (preset) {
    case "today":
      return { from: iso(today), to: iso(today) };
    case "7d":
      return { from: back(6), to: iso(today) };
    case "30d":
      return { from: back(29), to: iso(today) };
    default:
      return { from: "", to: "" };
  }
}

export const joinedOn = (iso) => new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(iso));

/** One line for the outcome of a bulk status change. */
export function bulkSummary(results, active, nameOf) {
  const done = results.filter((r) => r.ok).length;
  const failed = results.filter((r) => !r.ok);
  const verb = active ? "activated" : "deactivated";
  const head = `${done} user${done === 1 ? "" : "s"} ${verb}.`;
  if (!failed.length) return { text: head, failed: [] };
  return { text: `${head} ${failed.length} could not be changed:`, failed: failed.map((r) => `${nameOf(r.user_id)}: ${r.message}`) };
}
