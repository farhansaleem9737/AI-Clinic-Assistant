// What the header search covers for the signed-in user (D119). Mirrors
// backend/app/services/search_service.py:categories — the server decides; this
// only words the placeholder and the hints, from the permissions /auth/me sent.

export function searchScope(can) {
  const patientsAny = can("patient:read_any");
  const patientsOwn = !patientsAny && can("patient:read_assigned");
  const users = can("user:read");
  const appointments = users && can("appointment:read_any");

  const categories = [
    ...(patientsAny || patientsOwn ? ["patients"] : []),
    "doctors",
    "departments",
    ...(appointments ? ["appointments"] : []),
    ...(users ? ["users"] : []),
  ];

  let placeholder;
  if (users) placeholder = "Search users, doctors, patients, departments...";
  else if (patientsOwn) placeholder = "Search doctors, departments or your patients...";
  else if (patientsAny) placeholder = "Search patients, doctors or departments...";
  else placeholder = "Search doctors or departments...";

  const names = { patients: patientsOwn ? "your patients" : "patients", doctors: "doctors", departments: "departments", appointments: "appointments", users: "users" };
  const listed = categories.map((c) => names[c]);
  const sentence = listed.length > 1 ? `${listed.slice(0, -1).join(", ")} or ${listed.at(-1)}` : listed[0];
  return { categories, placeholder, label: `Search ${sentence}` };
}

/**
 * The doctors list for one department. On the doctors page already, the other
 * filters (experience, fee, sort, view) are kept; only the page resets.
 */
export function departmentLink(departmentId, location) {
  const params = location?.pathname === "/doctors" ? new URLSearchParams(location.search) : new URLSearchParams();
  params.set("department", departmentId);
  params.delete("page");
  return `/doctors?${params.toString()}`;
}
