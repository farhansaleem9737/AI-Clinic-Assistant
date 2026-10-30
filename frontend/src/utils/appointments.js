export const STATUS_LABELS = {
  requested: "Requested",
  scheduled: "Scheduled",
  confirmed: "Confirmed",
  checked_in: "Checked in",
  in_progress: "In consultation",
  completed: "Completed",
  cancelled: "Cancelled",
  no_show: "No-show",
};

// Button labels for moving *to* a status.
export const ACTION_LABELS = {
  scheduled: "Schedule",
  confirmed: "Confirm",
  checked_in: "Check in",
  in_progress: "Start consultation",
  completed: "Complete",
  no_show: "Mark no-show",
  cancelled: "Cancel appointment",
};

export const CANCELLATION_REASONS = {
  patient_request: "Patient request",
  doctor_unavailable: "Doctor unavailable",
  clinic_decision: "Clinic decision",
  other: "Other",
};

export const ACTIVE_STATUSES = ["requested", "scheduled", "confirmed", "checked_in", "in_progress"];

// Badge colours follow the design: confirmed green, scheduled blue, requested
// amber, completed neutral, cancelled red. The label is always shown too.
export function statusTone(status) {
  if (status === "confirmed") return "ok";
  if (status === "requested") return "warn";
  if (status === "scheduled") return "info";
  if (status === "checked_in" || status === "in_progress") return "warn";
  if (status === "cancelled" || status === "no_show") return "danger";
  return "";
}

// What a menu item says for moving *to* a status. Only transitions the API
// lists in `allowed_transitions` are ever shown (row menus).
export const MENU_ACTIONS = {
  scheduled: "Accept request",
  confirmed: "Confirm appointment",
  checked_in: "Check in",
  in_progress: "Start consultation",
  completed: "Mark completed",
  no_show: "Mark as no-show",
  cancelled: "Cancel appointment",
};
// Asked to confirm first: they cannot be undone.
export const CONFIRM_ACTIONS = {
  cancelled: { title: "Cancel appointment?", label: "Cancel appointment", danger: true },
  no_show: { title: "Mark as no-show?", label: "Mark as no-show", danger: true },
  completed: { title: "Mark as completed?", label: "Mark completed" },
};
