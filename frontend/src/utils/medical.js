import { DOCUMENT_TYPES } from "../services/documentService";
import { MAX_DOCUMENT_BYTES } from "../services/files";

// What the API accepts (backend/app/api/deps/uploads.py); it checks the content too.
export const ACCEPTED = { "application/pdf": "PDF", "image/jpeg": "JPG", "image/png": "PNG" };
export const ACCEPT_ATTR = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";
export const LIMIT_TEXT = `Supported: PDF, JPG, PNG • Up to ${MAX_DOCUMENT_BYTES / (1024 * 1024)} MB`;
export const TYPE_LABEL = Object.fromEntries(DOCUMENT_TYPES.map((t) => [t.value, t.label]));

export const isImage = (doc) => doc.content_type?.startsWith("image/");
// "30 Oct 2026". A calendar date ("2026-10-30", a report's date) is shown as
// written, never shifted by a timezone; a timestamp (an upload) in local time.
export function shortDate(value) {
  if (!value) return "";
  const format = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  if (value.length === 10) {
    const [y, m, d] = value.split("-").map(Number);
    return format.format(new Date(y, m - 1, d));
  }
  return format.format(new Date(value));
}
export const docDate = (doc) => doc.document_date ?? doc.created_at;
