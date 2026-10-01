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
