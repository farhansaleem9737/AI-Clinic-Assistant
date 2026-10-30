// Helpers for the floating Clinic AI Assistant (D96).

export const LAUNCHER_STORAGE_KEY = "clinic-ai-launcher-position";
export const EDGE_GAP = 24;
export const SNAP_DISTANCE = 40;
export const DRAG_THRESHOLD = 6;
export const launcherSize = (width) => (width <= 640 ? 60 : 72);

/** Keep the launcher fully on screen. */
export function clampPosition({ x, y }, viewport, size) {
  const maxX = Math.max(0, viewport.width - size - 8);
  const maxY = Math.max(0, viewport.height - size - 8);
  return { x: Math.min(Math.max(8, x), maxX), y: Math.min(Math.max(8, y), maxY) };
}

export const defaultPosition = (viewport, size) => ({ x: viewport.width - size - EDGE_GAP, y: viewport.height - size - EDGE_GAP });

/** Released close to the left or right edge: settle at the usual gap. Anywhere else stays put. */
export function snapToEdge(position, viewport, size) {
  if (position.x < SNAP_DISTANCE) return { ...position, x: EDGE_GAP };
  if (viewport.width - (position.x + size) < SNAP_DISTANCE) return { ...position, x: viewport.width - size - EDGE_GAP };
  return position;
}

export function loadPosition(viewport, size) {
  try {
    const saved = JSON.parse(window.localStorage.getItem(LAUNCHER_STORAGE_KEY) ?? "null");
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) return clampPosition(saved, viewport, size);
  } catch {
    // storage blocked or corrupt: fall back to the default corner
  }
  return defaultPosition(viewport, size);
}

export function savePosition(position) {
  try {
    window.localStorage.setItem(LAUNCHER_STORAGE_KEY, JSON.stringify(position));
  } catch {
    // private mode: position simply is not remembered
  }
}

export const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.docx,.txt";
const EXTENSIONS = ["pdf", "png", "jpg", "jpeg", "webp", "docx", "txt"];

/** Client-side checks; the server checks again from the bytes. */
export function checkFiles(files, { maxFiles, maxBytes, already = 0 }) {
  const accepted = [];
  const errors = [];
  for (const file of files) {
    const extension = file.name.split(".").pop()?.toLowerCase();
    if (!EXTENSIONS.includes(extension)) errors.push(`${file.name}: not a supported file type.`);
    else if (file.size === 0) errors.push(`${file.name}: the file is empty.`);
    else if (file.size > maxBytes) errors.push(`${file.name}: larger than ${Math.round(maxBytes / (1024 * 1024))} MB.`);
    else if (already + accepted.length >= maxFiles) errors.push(`${file.name}: at most ${maxFiles} files per message.`);
    else accepted.push(file);
  }
  return { accepted, errors };
}

export const fileSize = (bytes) =>
  bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;

// Welcome-screen suggestions (D97; role-aware D100). Each starts a real
// request and needs a capability the server reports for this user.
export const SUGGESTIONS = {
  find: {
    capability: "find_doctors",
    title: "Find a Doctor",
    text: "Search by specialty, department or name.",
    prompt: "Help me find a doctor by name, specialty, department, or professional experience.",
    tone: "blue",
    icon: "search",
  },
  book: {
    capability: "book_appointment",
    title: "Book Appointment",
    text: "Find available slots and schedule your visit.",
    prompt: "Help me book an appointment.",
    tone: "green",
    icon: "calendar",
  },
  mine: {
    capability: "my_appointments",
    title: "My Appointments",
    text: "See your upcoming visits.",
    prompt: "Show my upcoming appointments.",
    tone: "purple",
    icon: "list",
  },
  reschedule: {
    capability: "clinic_help",
    title: "How Can I Reschedule?",
    text: "Steps and clinic policy.",
    prompt: "How can I reschedule an appointment?",
    tone: "orange",
    icon: "help",
  },
  reports: {
    capability: "medical_documents",
    title: "My Medical Reports",
    text: "List and explain your uploaded reports.",
    prompt: "What medical documents have I uploaded?",
    tone: "purple",
    icon: "file",
  },
  services: {
    capability: "find_doctors",
    title: "Clinic Services",
    text: "Explore departments and services.",
    prompt: "What departments and services does the clinic offer?",
    tone: "orange",
    icon: "stethoscope",
  },
  today: {
    capability: "appointments_overview",
    title: "Today's Appointments",
    text: "Everything booked for today.",
    prompt: "Show today's appointments.",
    tone: "blue",
    icon: "list",
  },
  schedule: {
    capability: "appointments_overview",
    title: "Show My Schedule",
    text: "The next seven days.",
    prompt: "Show my schedule for the next 7 days.",
    tone: "green",
    icon: "calendar",
  },
  findPatient: {
    capability: "find_patient",
    title: "Find a Patient",
    text: "Search by name or MRN.",
    prompt: "Help me find a patient.",
    tone: "purple",
    icon: "user",
  },
  availability: {
    capability: "find_doctors",
    title: "Check Doctor Availability",
    text: "Free slots for a doctor.",
    prompt: "Check a doctor's availability.",
    tone: "green",
    icon: "calendar",
  },
  stats: {
    capability: "dashboard_figures",
    title: "Appointment Statistics",
    text: "Today's and upcoming counts.",
    prompt: "Show appointment statistics.",
    tone: "purple",
    icon: "chart",
  },
  departments: {
    capability: "clinic_help",
    title: "Manage Departments",
    text: "Where and how to manage them.",
    prompt: "Help me manage departments.",
    tone: "orange",
    icon: "help",
  },
};

// Preferred suggestions per role; the first role the user has wins.
const ROLE_SUGGESTIONS = [
  ["admin", ["stats", "departments", "today", "find"]],
  ["receptionist", ["findPatient", "availability", "today", "find"]],
  ["doctor", ["today", "schedule", "stats", "find"]],
  ["patient", ["find", "book", "reports", "mine"]],
];
const FILLERS = ["services", "reschedule", "find", "stats"];

/**
 * Up to four suggestions for this user (D100): their role's set, keeping only
 * what the server says they can use, topped up with general ones. When the
 * assistant is not set up, the role's set is shown (disabled, with the reason).
 */
export function suggestionsFor(status) {
  const roles = status?.roles ?? [];
  const keys = (ROLE_SUGGESTIONS.find(([role]) => roles.includes(role)) ?? ROLE_SUGGESTIONS.at(-1))[1];
  if (!status?.configured) return keys.map((key) => ({ key, ...SUGGESTIONS[key] }));
  const usable = (key) => status.capabilities?.includes(SUGGESTIONS[key].capability);
  const chosen = keys.filter(usable);
  for (const key of FILLERS) {
    if (chosen.length >= 4) break;
    if (!chosen.includes(key) && usable(key)) chosen.push(key);
  }
  return chosen.map((key) => ({ key, ...SUGGESTIONS[key] }));
}

/** Why a suggestion is off, or null when it can be used. */
export function unavailableReason(action, status) {
  if (!status?.configured) return "The assistant is not set up yet.";
  return status.capabilities?.includes(action.capability) ? null : "Not available for your account.";
}

/** "12 of 20 messages left today", or null when there is no daily limit. */
export function usageNote(usage) {
  if (!usage || !usage.daily_limit) return null;
  const left = usage.remaining_today ?? 0;
  return left === 0 ? "Daily message limit reached. It resets tomorrow." : `${left} of ${usage.daily_limit} messages left today`;
}
