// The doctors directory keeps its whole state in the URL (search, filters,
// sort, page, view), so a refresh, the back button or a shared link all show
// the same results. These helpers translate between the URL and the API.

export const PAGE_SIZE = 6;

export const SORT_OPTIONS = [
  { value: "name_asc", label: "Name (A–Z)" },
  { value: "name_desc", label: "Name (Z–A)" },
  { value: "experience_asc", label: "Experience: Low to High" },
  { value: "experience_desc", label: "Experience: High to Low" },
  { value: "fee_asc", label: "Fee: Low to High" },
  { value: "fee_desc", label: "Fee: High to Low" },
];
export const DEFAULT_SORT = "name_asc";

export const EXPERIENCE_OPTIONS = [
  { value: "1", label: "1+ years" },
  { value: "5", label: "5+ years" },
  { value: "10", label: "10+ years" },
  { value: "15", label: "15+ years" },
];

// Ranges are half-open (a fee of exactly 150 is in "150–200" only). Fees have
// two decimals, so an upper bound of x.99 expresses "below the next range".
export const FEE_RANGES = [
  { value: "under-100", label: "Under 100", max: "99.99" },
  { value: "100-150", label: "100 – 150", min: "100", max: "149.99" },
  { value: "150-200", label: "150 – 200", min: "150", max: "199.99" },
  { value: "200-plus", label: "200+", min: "200" },
];

export const EMPTY_FILTERS = { q: "", department: "", specialization: "", min_experience: "", fee: "" };

const known = (options, value) => (options.some((o) => o.value === value) ? value : "");

// Read the directory state from the URL, ignoring anything unrecognised.
export function readDirectoryState(searchParams) {
  const page = Number.parseInt(searchParams.get("page") ?? "1", 10);
  return {
    filters: {
      q: searchParams.get("q") ?? "",
      department: searchParams.get("department") ?? "",
      specialization: searchParams.get("specialization") ?? "",
      min_experience: known(EXPERIENCE_OPTIONS, searchParams.get("min_experience") ?? ""),
      fee: known(FEE_RANGES, searchParams.get("fee") ?? ""),
    },
    sort: known(SORT_OPTIONS, searchParams.get("sort") ?? "") || DEFAULT_SORT,
    page: Number.isInteger(page) && page > 0 ? page : 1,
    view: searchParams.get("view") === "list" ? "list" : "grid",
  };
}

// Write it back, leaving defaults out so URLs stay short.
export function directorySearchParams({ filters, sort, page, view }) {
  const params = {};
  for (const [key, value] of Object.entries(filters)) {
    const trimmed = typeof value === "string" ? value.trim() : value;
    if (trimmed) params[key] = trimmed;
  }
  if (sort !== DEFAULT_SORT) params.sort = sort;
  if (page > 1) params.page = String(page);
  if (view === "list") params.view = "list";
  return params;
}

// Query parameters for GET /public/doctors.
export function directoryApiParams({ filters, sort, page }) {
  const params = { page, page_size: PAGE_SIZE, sort };
  if (filters.q.trim()) params.q = filters.q.trim();
  if (filters.department) params.department_id = filters.department;
  if (filters.specialization) params.specialization = filters.specialization;
  if (filters.min_experience) params.min_experience = filters.min_experience;
  const range = FEE_RANGES.find((r) => r.value === filters.fee);
  if (range?.min) params.fee_min = range.min;
  if (range?.max) params.fee_max = range.max;
  return params;
}

export const AVAILABILITY = {
  available: { label: "Available", tone: "ok" },
  busy: { label: "Busy", tone: "warn" },
  unavailable: { label: "Unavailable", tone: "danger" },
};

// Badge on the booking screen. Every claim comes from the API's summary of
// real free slots over the next week (working hours − leave − bookings,
// with the booking notice applied); "this week" means that 7-day window.
export function bookingAvailability(availability) {
  if (!availability) return { label: "Availability unknown", tone: "" };
  if (availability.status === "available") {
    if (availability.available_today) return { label: "Available today", tone: "ok" };
    if (availability.limited) return { label: "Limited availability", tone: "warn" };
    return { label: "Available this week", tone: "ok" };
  }
  if (availability.status === "busy") return { label: "Fully booked this week", tone: "warn" };
  return { label: "No free slots this week", tone: "danger" };
}

// Page numbers to show: first, last, and the pages around the current one,
// with null marking a gap. e.g. (5, 12) -> [1, null, 4, 5, 6, null, 12]
export function pageWindow(current, total) {
  const wanted = new Set([1, total, current - 1, current, current + 1]);
  if (current <= 3) [2, 3, 4].forEach((p) => wanted.add(p));
  if (current >= total - 2) [total - 1, total - 2, total - 3].forEach((p) => wanted.add(p));
  const pages = [...wanted].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const result = [];
  for (const [index, page] of pages.entries()) {
    if (index > 0 && page - pages[index - 1] > 1) result.push(null);
    result.push(page);
  }
  return result;
}

// "2016 – 2020", "2020 – Present" (when `ongoing` is given), "2011", or null.
export function yearRange(start, end, { ongoing } = {}) {
  if (start && end) return start === end ? String(end) : `${start} – ${end}`;
  if (start) return ongoing ? `${start} – ${ongoing}` : `From ${start}`;
  if (end) return String(end);
  return null;
}
