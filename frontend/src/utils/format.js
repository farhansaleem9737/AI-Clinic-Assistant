// Currency label is configuration, not code (VITE_CURRENCY in frontend/.env).
export const CURRENCY = import.meta.env.VITE_CURRENCY || "";

// Fees arrive as decimal strings ("150.00"): format without float arithmetic.
export function formatFee(fee) {
  if (fee == null) return "—";
  return CURRENCY ? `${CURRENCY} ${fee}` : fee;
}

export function doctorName(doctor) {
  return doctor.title ? `${doctor.title} ${doctor.name}` : doctor.name;
}

// Drop empty values so they are not sent as query parameters.
export function cleanParams(params) {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v != null));
}
