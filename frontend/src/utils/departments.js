// Helpers for Admin > Departments (D89).

// Must match DepartmentIcon / DepartmentColor in backend/app/schemas/department.py.
export const ICON_KEYS = [
  "heart-pulse", "stethoscope", "brain", "bone", "baby", "ear", "eye", "scan-face",
  "activity", "pill", "microscope", "syringe", "smile", "hospital",
];
export const ICON_LABELS = {
  "heart-pulse": "Heart", stethoscope: "Stethoscope", brain: "Brain", bone: "Bone", baby: "Baby", ear: "Ear", eye: "Eye",
  "scan-face": "Skin", activity: "Pulse", pill: "Pill", microscope: "Microscope", syringe: "Syringe", smile: "Teeth", hospital: "Hospital",
};
export const COLORS = {
  red: { fg: "#e5484d", bg: "#fdecec" },
  pink: { fg: "#e93d82", bg: "#fdeaf2" },
  purple: { fg: "#8e4ec6", bg: "#f3ebfb" },
  violet: { fg: "#6e56cf", bg: "#efebfc" },
  blue: { fg: "#1677ff", bg: "#e8f1ff" },
  teal: { fg: "#12a594", bg: "#e5f7f4" },
  green: { fg: "#30a46c", bg: "#e6f6ee" },
  yellow: { fg: "#d6a100", bg: "#fff6d6" },
  orange: { fg: "#f76b15", bg: "#ffefe5" },
  slate: { fg: "#64748b", bg: "#eef1f5" },
};
export const COLOR_KEYS = Object.keys(COLORS);

// When a department has no icon chosen, pick one from its name.
const GUESSES = [
  [/cardio|heart/i, "heart-pulse", "red"],
  [/derma|skin/i, "scan-face", "orange"],
  [/neuro|brain|psych/i, "brain", "purple"],
  [/ortho|bone|spine/i, "bone", "green"],
  [/pediat|paediat|child|neonat/i, "smile", "yellow"],
  [/\bent\b|ear|otolaryn/i, "ear", "yellow"],
  [/ophthal|eye|optom/i, "eye", "violet"],
  [/dent|oral/i, "smile", "teal"],
  [/patho|lab/i, "microscope", "slate"],
  [/pharm/i, "pill", "teal"],
  [/medicine|general|family|internal/i, "stethoscope", "blue"],
];

const hash = (text) => [...text].reduce((sum, ch) => sum + ch.charCodeAt(0), 0);

/** {icon, color} to show: the saved choice, otherwise a guess from the name. */
export function departmentLook(department) {
  const guess = GUESSES.find(([pattern]) => pattern.test(department.name ?? ""));
  return {
    icon: department.icon ?? guess?.[1] ?? "hospital",
    color: department.color ?? guess?.[2] ?? COLOR_KEYS[hash(department.name ?? "") % COLOR_KEYS.length],
  };
}

/**
 * "(GMT+05:00) Karachi" for an IANA name, using the offset in force on
 * `at` (default now), so daylight saving is reflected.
 */
export function timezoneLabel(zone, at = new Date()) {
  let offset;
  try {
    const part = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "longOffset" })
      .formatToParts(at)
      .find((p) => p.type === "timeZoneName");
    offset = part?.value === "GMT" ? "GMT+00:00" : (part?.value ?? "GMT");
  } catch {
    return zone;
  }
  const city = zone.split("/").at(-1).replaceAll("_", " ");
  return `(${offset}) ${city}`;
}

/** Every IANA zone the browser knows; the server validates again. */
export function timezoneOptions() {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC", "Asia/Karachi"];
  }
}

export const doctorLabel = (d) => [d.title, d.name].filter(Boolean).join(" ");

export function validateDepartment(form) {
  const errors = {};
  const name = form.name.trim();
  if (!name) errors.name = "Enter the department name.";
  else if (name.length > 100) errors.name = "Use at most 100 characters.";
  if (form.description.length > 500) errors.description = "Use at most 500 characters.";
  if (!form.timezone) errors.timezone = "Choose a timezone.";
  else if (!timezoneOptions().includes(form.timezone) && form.timezone !== "UTC") errors.timezone = "Choose a timezone from the list.";
  return errors;
}
