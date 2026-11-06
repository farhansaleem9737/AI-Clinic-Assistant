import { CloudUpload, Download, Eye, FileImage, FileText } from "lucide-react";
import { useEffect, useState } from "react";
import ActionMenu from "../ActionMenu";
import ConfirmDialog from "../ConfirmDialog";
import { getErrorMessage } from "../../services/api";
import { DOCUMENT_TYPES, getDocumentDownload, retractDocument, uploadDocument } from "../../services/documentService";
import { MAX_DOCUMENT_BYTES, formatBytes } from "../../services/files";
import { ACCEPTED, ACCEPT_ATTR, LIMIT_TEXT, TYPE_LABEL, docDate, isImage, shortDate } from "../../utils/medical";

// Plain words for what went wrong; the server's own message when it gives one.
function uploadError(err) {
  const status = err?.response?.status;
  if (!err?.response) return "The upload was interrupted. Check your connection and try again.";
  if (status === 401) return "Your session has expired. Sign in again, then upload the file.";
  if (status === 413) return "The file is too large. Documents can be up to 20 MB.";
  if (status === 503) return "File storage is temporarily unavailable. Please try again in a moment.";
  return getErrorMessage(err, "The document could not be uploaded. Please try again.");
}

export function FileIcon({ doc }) {
  return isImage(doc) ? (
    <span className="med-file-icon image" aria-hidden="true">
      <FileImage size={24} />
    </span>
  ) : (
    <span className="med-file-icon pdf" aria-hidden="true">
      <FileText size={22} />
      <small>PDF</small>
    </span>
  );
}

/** Choose a file, check it here (type, size), then the API checks it again and stores it. */
export function UploadDialog({ patientId, documents, onClose, onUploaded }) {
  const [file, setFile] = useState(null);
  const [form, setForm] = useState({ title: "", document_type: "lab_report", document_date: "" });
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState("");
  const [confirmDuplicate, setConfirmDuplicate] = useState(false);
  const busy = progress !== null;

  const choose = (chosen) => {
    setError("");
    setConfirmDuplicate(false);
    if (!chosen) return setFile(null);
    if (!ACCEPTED[chosen.type]) {
      setFile(null);
      return setError("This file type is not supported. Choose a PDF, JPG or PNG file.");
    }
    if (chosen.size > MAX_DOCUMENT_BYTES) {
      setFile(null);
      return setError(`This file is ${formatBytes(chosen.size)}. Documents can be up to 20 MB.`);
    }
    setFile(chosen);
    setForm((f) => ({ ...f, title: f.title || chosen.name.replace(/\.[^.]+$/, "").slice(0, 200) }));
  };
  const duplicate = file && documents.some((d) => d.filename === file.name && d.size_bytes === file.size);

  const submit = async () => {
    if (!file) return setError("Choose a file to upload.");
    if (!form.title.trim()) return setError("Give the document a title.");
    if (duplicate && !confirmDuplicate) {
      setConfirmDuplicate(true);
      return setError("");
    }
    setError("");
    setProgress(0);
    try {
      const res = await uploadDocument(patientId, file, { ...form, title: form.title.trim() }, setProgress);
      onUploaded(res.data); // only after the server confirmed it
    } catch (err) {
      setError(uploadError(err));
      setProgress(null);
    }
  };

  return (
    <ConfirmDialog
      title="Upload a medical document"
      confirmLabel={confirmDuplicate ? "Upload anyway" : "Upload"}
      busy={busy}
      onConfirm={submit}
      onCancel={onClose}
      className="med-upload-dialog"
    >
      <div className="med-upload-form">
        <label className="med-file-drop">
          <CloudUpload size={26} aria-hidden="true" />
          <span>{file ? file.name : "Choose a file"}</span>
          <small className="muted">{file ? formatBytes(file.size) : LIMIT_TEXT}</small>
          <input type="file" accept={ACCEPT_ATTR} disabled={busy} onChange={(e) => choose(e.target.files?.[0] ?? null)} aria-label="File" />
        </label>
        <label>
          Title
          <input value={form.title} maxLength={200} disabled={busy} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </label>
        <div className="med-upload-row">
          <label>
            Category
            <select value={form.document_type} disabled={busy} onChange={(e) => setForm({ ...form, document_type: e.target.value })}>
              {DOCUMENT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Date of the report <span className="muted">(optional)</span>
            <input type="date" value={form.document_date} disabled={busy} onChange={(e) => setForm({ ...form, document_date: e.target.value })} />
          </label>
        </div>
        {confirmDuplicate && (
          <p className="med-warning" role="status">
            A document with this file name and size is already in your records. Upload it again?
          </p>
        )}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        {busy && (
          <div className="med-progress" role="progressbar" aria-label="Upload progress" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${progress}%` }} />
          </div>
        )}
      </div>
    </ConfirmDialog>
  );
}

/** The file itself, from a short-lived link asked for when opened. */
export function PreviewDialog({ patientId, doc, onClose, onDownload }) {
  const [state, setState] = useState({ url: null, error: "" });
  useEffect(() => {
    let live = true;
    getDocumentDownload(patientId, doc.id, { inline: true })
      .then((res) => live && setState({ url: res.data.url, error: "" }))
      .catch((err) => live && setState({ url: null, error: getErrorMessage(err, "The document could not be opened.") }));
    return () => {
      live = false; // the link is never kept
    };
  }, [patientId, doc.id]);
  return (
    <ConfirmDialog title={doc.title} confirmLabel="Download" cancelLabel="Close" onConfirm={() => onDownload(doc)} onCancel={onClose} className="med-preview-dialog">
      <div className="med-preview">
        {state.error && (
          <p className="field-error" role="alert">
            {state.error}
          </p>
        )}
        {!state.url && !state.error && (
          <p className="muted" role="status">
            Loading the document…
          </p>
        )}
        {state.url && isImage(doc) && <img src={state.url} alt={doc.title} />}
        {state.url && !isImage(doc) && <iframe src={state.url} title={doc.title} />}
        {state.url && (
          <a href={state.url} target="_blank" rel="noopener noreferrer" className="small">
            Open in a new tab
          </a>
        )}
      </div>
    </ConfirmDialog>
  );
}

export function DetailsDialog({ doc, onClose }) {
  const rows = [
    ["Title", doc.title],
    ["Category", TYPE_LABEL[doc.document_type] ?? doc.document_type],
    ["Date of the report", doc.document_date ? shortDate(doc.document_date) : "Not given"],
    ["Uploaded", shortDate(doc.created_at)],
    ["Added by", doc.uploaded_by_me ? "You" : "The clinic"],
    ["File", `${doc.filename} · ${ACCEPTED[doc.content_type] ?? doc.content_type} · ${formatBytes(doc.size_bytes)}`],
  ];
  return (
    <ConfirmDialog title="Document details" confirmLabel="Close" cancelLabel="Back" onConfirm={onClose} onCancel={onClose}>
      <dl className="med-details">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </ConfirmDialog>
  );
}

/** Documents are never deleted (medical records): a wrong upload is removed from view, with a reason. */
export function RetractDialog({ patientId, doc, onClose, onRetracted }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const confirm = async () => {
    if (reason.trim().length < 3) return setError("Say briefly why, for example “wrong file”.");
    setBusy(true);
    setError("");
    try {
      await retractDocument(patientId, doc.id, reason.trim());
      onRetracted();
    } catch (err) {
      setError(getErrorMessage(err, "The document could not be removed."));
      setBusy(false);
    }
  };
  return (
    <ConfirmDialog title="Remove this document?" confirmLabel="Remove document" danger busy={busy} onConfirm={confirm} onCancel={onClose}>
      <p>
        “{doc.title}” will no longer appear in your records. The clinic keeps it marked as entered in error, as medical
        records require.
      </p>
      <label>
        Reason
        <textarea rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. wrong file" />
      </label>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </ConfirmDialog>
  );
}

function DocumentRow({ doc, mayRetract, onView, onDownload, onDetails, onRetract }) {
  const items = [
    { label: "View details", onSelect: () => onDetails(doc) },
    ...(mayRetract ? [{ label: "Remove document", onSelect: () => onRetract(doc), danger: true }] : []),
  ];
  return (
    <li className="med-doc-row">
      <FileIcon doc={doc} />
      <div className="med-doc-main">
        <strong>{doc.title}</strong>
        <span className="med-doc-meta muted">
          <span>{shortDate(docDate(doc))}</span>
          <span>{formatBytes(doc.size_bytes)}</span>
        </span>
      </div>
      <span className={`med-badge type-${doc.document_type}`}>{TYPE_LABEL[doc.document_type] ?? doc.document_type}</span>
      <div className="med-doc-actions">
        <button type="button" className="icon-button" aria-label={`View ${doc.title}`} onClick={() => onView(doc)}>
          <Eye size={18} aria-hidden="true" />
        </button>
        <button type="button" className="icon-button" aria-label={`Download ${doc.title}`} onClick={() => onDownload(doc)}>
          <Download size={18} aria-hidden="true" />
        </button>
        <ActionMenu label={`More actions for ${doc.title}`} items={items} />
      </div>
    </li>
  );
}

function EmptyIllustration() {
  return (
    <svg className="med-empty-art" viewBox="0 0 240 150" aria-hidden="true">
      <ellipse cx="120" cy="118" rx="100" ry="26" fill="#EAF2FF" />
      <circle cx="62" cy="78" r="34" fill="#F1F6FF" />
      <circle cx="182" cy="80" r="30" fill="#F1F6FF" />
      <rect x="84" y="22" width="72" height="96" rx="10" fill="#fff" stroke="#1677FF" strokeWidth="3" />
      <rect x="104" y="14" width="32" height="14" rx="5" fill="#fff" stroke="#1677FF" strokeWidth="3" />
      <path d="M120 40v22M109 51h22" stroke="#1677FF" strokeWidth="5" strokeLinecap="round" />
      <path d="M98 76h44M98 88h44M98 100h28" stroke="#9CC0FF" strokeWidth="3" strokeLinecap="round" />
      <path d="M70 26l6 6M78 18l2 8M188 52h7" stroke="#1677FF" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

/** Layout A (no documents) or B (the list), from the patient's actual records. */
export default function DocumentsPanel({ documents, loading, error, onRetry, canUpload, onUpload, onView, onDownload, onDetails, onRetract, mayRetract }) {
  if (error) {
    return (
      <div className="med-state" role="alert">
        <p>{error}</p>
        <button type="button" className="secondary" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }
  if (loading && !documents) {
    return (
      <div className="med-state" role="status" aria-label="Loading documents">
        <div className="skeleton" style={{ height: 64 }} />
        <div className="skeleton" style={{ height: 64 }} />
      </div>
    );
  }
  if (!documents?.length) {
    return (
      <div className="med-empty">
        <EmptyIllustration />
        <h2>No medical documents yet</h2>
        <p className="muted">Upload your lab reports, prescriptions, or other medical records to keep your health information organized and accessible.</p>
        {canUpload && (
          <button type="button" onClick={onUpload}>
            <CloudUpload size={18} aria-hidden="true" /> Upload Document
          </button>
        )}
        <small className="muted">{LIMIT_TEXT}</small>
      </div>
    );
  }
  return (
    <section className="med-docs" aria-labelledby="med-docs-title">
      <div className="med-docs-head">
        <h2 id="med-docs-title">
          <FileText size={22} aria-hidden="true" /> My Medical Documents <span className="muted">({documents.length})</span>
        </h2>
        {canUpload && (
          <button type="button" onClick={onUpload}>
            <CloudUpload size={18} aria-hidden="true" /> Upload Document
          </button>
        )}
      </div>
      <ul className="med-doc-list">
        {documents.map((doc) => (
          <DocumentRow key={doc.id} doc={doc} mayRetract={mayRetract(doc)} onView={onView} onDownload={onDownload} onDetails={onDetails} onRetract={onRetract} />
        ))}
      </ul>
    </section>
  );
}
