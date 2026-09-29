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

export function statusTone(status) {
  if (status === "completed") return "ok";
  if (status === "cancelled" || status === "no_show") return "danger";
  if (status === "checked_in" || status === "in_progress") return "warn";
  return "";
}
