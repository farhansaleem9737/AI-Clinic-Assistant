import { Download } from "lucide-react";
import { useState } from "react";
import Alert from "../Alert";
import { useFetch } from "../../hooks/useFetch";
import { getErrorMessage } from "../../services/api";
import {
  DOCUMENT_TYPES,
  getDocumentDownload,
  listDocuments,
  retractDocument,
  uploadDocument,
} from "../../services/documentService";
import { MAX_DOCUMENT_BYTES, formatBytes } from "../../services/files";

const ACCEPT = "application/pdf,image/jpeg,image/png";
const TYPE_LABEL = Object.fromEntries(
  DOCUMENT_TYPES.map((t) => [t.value, t.label]),
);
const EMPTY = { document_type: "lab_report", title: "", document_date: "" };

/**
 * One patient's documents: list, download, upload, retract. The props only
 * decide what is shown; the API checks access on every request.
 */
export default function PatientDocuments({
  patientId,
  canUpload = false,
  retract,
}) {
  const [version, setVersion] = useState(0);
  const { data, loading, error } = useFetch(
    () => listDocuments(patientId),
    [patientId, version],
  );
  const [form, setForm] = useState(EMPTY);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState({ error: "", notice: "" });
  const reload = () => setVersion((v) => v + 1);

  const run = async (action, notice = "") => {
    setBusy(true);
    setMessage({ error: "", notice: "" });
    try {
      await action();
      setMessage({ error: "", notice });
      return true;
    } catch (err) {
      setMessage({ error: getErrorMessage(err), notice: "" });
      return false;
    } finally {
      setBusy(false);
    }
  };

  // Asked for at click time: the link expires after a few minutes. The file
  // is sent as an attachment, so the browser downloads it and the page stays.
  const download = (doc) =>
    run(async () => {
      const res = await getDocumentDownload(patientId, doc.id);
      window.location.assign(res.data.url);
    });

  const submit = async (e) => {
    e.preventDefault();
    const formElement = e.currentTarget;
    if (!file)
      return setMessage({ error: "Choose a file to upload.", notice: "" });
    if (file.size > MAX_DOCUMENT_BYTES)
      return setMessage({
        error: "The file must be 20 MB or smaller.",
        notice: "",
      });
    if (
      await run(
        () => uploadDocument(patientId, file, form),
        "Document uploaded",
      )
    ) {
      setForm(EMPTY);
      setFile(null);
      formElement.reset();
      reload();
    }
  };

  const retractOne = async (doc) => {
    const reason = window.prompt(
      "Why is this document being retracted? (e.g. wrong patient, wrong file)",
    );
    if (!reason || reason.trim().length < 3) return;
    if (
      await run(
        () => retractDocument(patientId, doc.id, reason.trim()),
        "Document retracted",
      )
    )
      reload();
  };

  const mayRetract = (doc) =>
    retract === "any" || (retract === "own" && doc.uploaded_by_me);

  return (
    <section className="card stack" aria-label="Documents">
      <h3>Documents</h3>
      <Alert>{error || message.error}</Alert>
      <Alert kind="success">{message.notice}</Alert>

      {loading && !data ? (
        <p className="muted">Loading…</p>
      ) : !data?.length ? (
        <p className="muted">No documents yet.</p>
      ) : (
        <ul
          className="stack"
          style={{ listStyle: "none", padding: 0, margin: 0 }}
        >
          {data.map((doc) => (
            <li key={doc.id} className="spread">
              <div>
                <strong>{doc.title}</strong>
                <p className="muted small">
                  {TYPE_LABEL[doc.document_type] ?? doc.document_type} ·{" "}
                  {doc.document_date ?? doc.created_at.slice(0, 10)} ·{" "}
                  {formatBytes(doc.size_bytes)}
                </p>
              </div>
              <div className="row">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => download(doc)}
                  disabled={busy}
                >
                  <Download size={16} aria-hidden="true" /> Download
                </button>
                {mayRetract(doc) && (
                  <button
                    type="button"
                    className="danger"
                    onClick={() => retractOne(doc)}
                    disabled={busy}
                  >
                    Retract
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {canUpload && (
        <form className="stack" onSubmit={submit}>
          <h4>Add a document</h4>
          <label>
            Type
            <select
              value={form.document_type}
              onChange={(e) =>
                setForm({ ...form, document_type: e.target.value })
              }
            >
              {DOCUMENT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Title
            <input
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              maxLength={200}
              placeholder="e.g. Complete blood count"
              required
            />
          </label>
          <label>
            Date of the report (optional)
            <input
              type="date"
              value={form.document_date}
              onChange={(e) =>
                setForm({ ...form, document_date: e.target.value })
              }
            />
          </label>
          <label>
            File (PDF, JPEG or PNG, up to 20 MB)
            <input
              type="file"
              accept={ACCEPT}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              required
            />
          </label>
          <button type="submit" disabled={busy}>
            {busy ? "Uploading…" : "Upload"}
          </button>
        </form>
      )}
    </section>
  );
}
