// Doctor career history (experience and education): form <-> API body, and the
// checks the API repeats. Used by CareerEditor and the profile's Edit dialogs.

export const NEW_POSITION = { title: "", organization: "", location: "", start_year: "", end_year: "", description: "" };
export const NEW_QUALIFICATION = { qualification: "", institution: "", field_of_study: "", start_year: "", end_year: "" };

// API record -> form strings (inputs need "" rather than null).
export const toForm = (career) => ({
  experience: career.experience.map((e) => ({ ...NEW_POSITION, ...nullsToBlank(e) })),
  education: career.education.map((e) => ({ ...NEW_QUALIFICATION, ...nullsToBlank(e) })),
});
function nullsToBlank(record) {
  return Object.fromEntries(Object.entries(record).map(([k, v]) => [k, v == null ? "" : String(v)]));
}
// Form strings -> API body: trimmed text, blank optional fields as null, years as numbers.
export function toPayload(form) {
  const text = (v) => v.trim() || null;
  const year = (v) => (String(v).trim() === "" ? null : Number(v));
  return {
    experience: form.experience.map((e) => ({
      title: e.title.trim(),
      organization: e.organization.trim(),
      location: text(e.location),
      start_year: year(e.start_year),
      end_year: year(e.end_year),
      description: text(e.description),
    })),
    education: form.education.map((e) => ({
      qualification: e.qualification.trim(),
      institution: e.institution.trim(),
      field_of_study: text(e.field_of_study),
      start_year: year(e.start_year),
      end_year: year(e.end_year),
    })),
  };
}

const blank = (v) => String(v).trim() === "";

/** The required-field and year-order checks the API repeats; "" when fine. */
export function careerError(form) {
  for (const e of form.experience) {
    if (blank(e.title) || blank(e.organization) || blank(e.start_year)) return "Each position needs a job title, an organization and a start year.";
    if (!blank(e.end_year) && Number(e.end_year) < Number(e.start_year)) return "A position cannot end before it starts.";
  }
  for (const e of form.education) {
    if (blank(e.qualification) || blank(e.institution)) return "Each qualification needs a degree or qualification and an institution.";
    if (!blank(e.end_year) && !blank(e.start_year) && Number(e.end_year) < Number(e.start_year)) return "A qualification cannot end before it starts.";
  }
  return "";
}
