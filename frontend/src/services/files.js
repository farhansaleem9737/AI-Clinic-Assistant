// Upload body: the file plus optional form fields. Empty fields are left out
// (the API reads a missing date as "none", but "" as an invalid date).
// Never set Content-Type yourself: axios adds the multipart boundary.
export function fileForm(file, fields = {}) {
  const form = new FormData();
  form.append("file", file);
  for (const [name, value] of Object.entries(fields)) {
    if (value !== undefined && value !== null && value !== "")
      form.append(name, value);
  }
  return form;
}

// Same limits as the backend settings. Here only for a quick message; the API decides.
export const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
export const MAX_DOCUMENT_BYTES = 20 * 1024 * 1024;

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
