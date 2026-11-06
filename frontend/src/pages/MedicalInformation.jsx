import { ClipboardPlus, CloudUpload, FileText, Info, Pill, ShieldAlert, Stethoscope, HeartPulse, Zap } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Alert from "../components/Alert";
import { HealthRecordSection } from "../components/medical/HealthRecords";
import DocumentsPanel, { DetailsDialog, PreviewDialog, RetractDialog, UploadDialog } from "../components/medical/MedicalDocuments";
import { useAuth } from "../context/useAuth";
import { useFetch } from "../hooks/useFetch";
import { getErrorMessage } from "../services/api";
import { getDocumentDownload, listDocuments } from "../services/documentService";
import { getHealthRecords } from "../services/healthRecordService";

const TABS = [
  { id: "documents", label: "Documents", icon: FileText },
  { id: "diagnoses", label: "Diagnoses", icon: Stethoscope },
  { id: "allergies", label: "Allergies", icon: ShieldAlert },
  { id: "medications", label: "Medications", icon: Pill },
];

function PageHead() {
  return (
    <header className="med-head">
      <span className="med-head-icon" aria-hidden="true">
        <ClipboardPlus size={30} />
      </span>
      <div>
        <h1>Medical Information</h1>
        <p className="muted">Your health records, reports, and medical documents in one place.</p>
      </div>
    </header>
  );
}

function Tabs({ active, onChange }) {
  const onKeyDown = (event) => {
    const index = TABS.findIndex((t) => t.id === active);
    const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: TABS.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const target = TABS[(next + TABS.length) % TABS.length];
    onChange(target.id);
    document.getElementById(`med-tab-${target.id}`)?.focus();
  };
  return (
    <div className="med-tabs" role="tablist" aria-label="Medical information" onKeyDown={onKeyDown}>
      {TABS.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          role="tab"
          id={`med-tab-${id}`}
          aria-selected={active === id}
          aria-controls="med-tab-panel"
          tabIndex={active === id ? 0 : -1}
          className={active === id ? "active" : ""}
          onClick={() => onChange(id)}
        >
          <Icon size={17} aria-hidden="true" /> {label}
        </button>
      ))}
    </div>
  );
}

function HealthOverview({ documents, records, onOpen }) {
  const count = (list) => (list ? list.length : undefined);
  const rows = [
    { key: "diagnoses", label: "Diagnoses", icon: Stethoscope, tone: "purple", value: count(records?.diagnoses) },
    { key: "allergies", label: "Allergies", icon: ShieldAlert, tone: "red", value: count(records?.allergies) },
    { key: "medications", label: "Medications", icon: Pill, tone: "green", value: count(records?.medications) },
    { key: "documents", label: "Documents", icon: FileText, tone: "blue", value: count(documents) },
  ];
  return (
    <section className="card med-overview" aria-labelledby="med-overview-title">
      <h2 id="med-overview-title">
        <HeartPulse size={22} aria-hidden="true" /> Health Overview
      </h2>
      <ul>
        {rows.map(({ key, label, icon: Icon, tone, value }) => (
          <li key={key}>
            <button type="button" className="med-overview-row" onClick={() => onOpen(key)}>
              <span className={`med-overview-icon ${tone}`} aria-hidden="true">
                <Icon size={18} />
              </span>
              <span className="med-overview-label">{label}</span>
              {value === undefined ? (
                <span className="med-count none">
                  …<span className="sr-only">loading</span>
                </span>
              ) : (
                <span className={`med-count ${tone}`}>{value}</span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The patient's medical information (D110, D112): their documents (upload,
 * view, download, details, remove), and their allergies, diagnoses and
 * medications. They report their own allergies and the medicines they take;
 * diagnoses and prescribed medicines come from their doctor. Nothing is read
 * out of documents or made up by the AI. The API checks every request.
 */
export default function MedicalInformation() {
  const { user, can } = useAuth();
  const patientId = user?.patient_id;
  const [params, setParams] = useSearchParams();
  const tab = TABS.some((t) => t.id === params.get("tab")) ? params.get("tab") : "documents";
  const setTab = (id) => setParams(id === "documents" ? {} : { tab: id }, { replace: true });
  const canRead = can("document:read_own");
  const canUpload = can("document:upload_own");
  const canRetract = can("document:retract_own");
  const [attempt, setAttempt] = useState(0);
  const docs = useFetch(() => listDocuments(patientId), [patientId], {
    query: "patients/own-documents",
    refresh: attempt,
    enabled: Boolean(patientId) && canRead,
    errorMessage: "Could not load your documents",
  });
  const [recordsAttempt, setRecordsAttempt] = useState(0);
  const records = useFetch(() => getHealthRecords(patientId), [patientId], {
    query: "patients/own-health-records",
    refresh: recordsAttempt,
    enabled: Boolean(patientId) && can("health_record:read_own"),
    errorMessage: "Could not load your health records",
  });
  const [dialog, setDialog] = useState(null); // { kind: "upload" | "preview" | "details" | "retract", doc }
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");

  if (!patientId) {
    return (
      <div className="med-page">
        <PageHead />
        <div className="card med-state">
          <p>Complete your patient profile first; your medical information belongs to it.</p>
          <Link className="button" to="/profile">
            Go to My Profile
          </Link>
        </div>
      </div>
    );
  }

  const documents = docs.data;
  const hasDocuments = Boolean(documents?.length);
  // Asked for at click time (it expires in minutes); sent as an attachment, so the page stays.
  const download = async (doc) => {
    setActionError("");
    try {
      const res = await getDocumentDownload(patientId, doc.id);
      window.location.assign(res.data.url);
    } catch (err) {
      setActionError(getErrorMessage(err, "The document could not be downloaded."));
    }
  };
  const open = (kind) => (doc) => {
    setNotice("");
    setActionError("");
    setDialog({ kind, doc });
  };
  const done = (text) => {
    setDialog(null);
    setNotice(text);
    setAttempt((n) => n + 1);
  };

  return (
    <div className="med-page">
      <PageHead />
      <div aria-live="polite">
        <Alert kind="success">{notice}</Alert>
      </div>
      <Alert>{actionError}</Alert>
      <div className="med-layout">
        <div className="card med-main">
          <Tabs active={tab} onChange={setTab} />
          <div id="med-tab-panel" role="tabpanel" aria-labelledby={`med-tab-${tab}`} className="med-panel">
            {tab === "documents" &&
              (canRead ? (
                <DocumentsPanel
                  documents={documents}
                  loading={docs.loading}
                  error={docs.error}
                  onRetry={() => setAttempt((n) => n + 1)}
                  canUpload={canUpload}
                  onUpload={() => open("upload")(null)}
                  onView={open("preview")}
                  onDownload={download}
                  onDetails={open("details")}
                  onRetract={open("retract")}
                  mayRetract={(doc) => canRetract && doc.uploaded_by_me}
                />
              ) : (
                <p className="muted med-state">Your account cannot view documents.</p>
              ))}
            {tab !== "documents" &&
              (records.data ? (
                <HealthRecordSection
                  key={tab}
                  kind={tab}
                  patientId={patientId}
                  entries={records.data[tab]}
                  canAdd={records.data[`can_add_${tab}`]}
                  viewer="patient"
                  onChanged={(text) => {
                    setNotice(text);
                    setRecordsAttempt((n) => n + 1);
                  }}
                />
              ) : records.error ? (
                <div className="med-state" role="alert">
                  <p>{records.error}</p>
                  <button type="button" className="secondary" onClick={() => setRecordsAttempt((n) => n + 1)}>
                    Try again
                  </button>
                </div>
              ) : (
                <div className="med-state" role="status" aria-label="Loading">
                  <div className="skeleton" style={{ height: 64 }} />
                  <div className="skeleton" style={{ height: 64 }} />
                </div>
              ))}
          </div>
        </div>

        <aside className="med-side" aria-label="Health overview">
          <HealthOverview documents={canRead ? documents : null} records={records.data} onOpen={setTab} />
          {hasDocuments ? (
            <section className="card med-quick" aria-labelledby="med-quick-title">
              <h2 id="med-quick-title">
                <Zap size={20} aria-hidden="true" /> Quick Actions
              </h2>
              <div className="med-quick-grid">
                {canUpload && (
                  <button type="button" className="secondary" onClick={() => open("upload")(null)}>
                    <CloudUpload size={22} aria-hidden="true" /> Upload Document
                  </button>
                )}
                <button type="button" className="secondary" onClick={() => setTab("allergies")}>
                  <ShieldAlert size={22} aria-hidden="true" /> My Allergies
                </button>
              </div>
            </section>
          ) : (
            <section className="card med-tip" aria-labelledby="med-tip-title">
              <Info size={22} aria-hidden="true" />
              <div>
                <h2 id="med-tip-title">Keep your health information up to date</h2>
                <p className="muted small">Add your reports, prescriptions, and test results to help your doctor provide better care.</p>
              </div>
            </section>
          )}
        </aside>
      </div>

      {dialog?.kind === "upload" && (
        <UploadDialog
          patientId={patientId}
          documents={documents ?? []}
          onClose={() => setDialog(null)}
          onUploaded={(doc) => done(`“${doc.title}” was uploaded.`)}
        />
      )}
      {dialog?.kind === "preview" && <PreviewDialog patientId={patientId} doc={dialog.doc} onClose={() => setDialog(null)} onDownload={download} />}
      {dialog?.kind === "details" && <DetailsDialog doc={dialog.doc} onClose={() => setDialog(null)} />}
      {dialog?.kind === "retract" && (
        <RetractDialog patientId={patientId} doc={dialog.doc} onClose={() => setDialog(null)} onRetracted={() => done(`“${dialog.doc.title}” was removed from your records.`)} />
      )}
    </div>
  );
}
