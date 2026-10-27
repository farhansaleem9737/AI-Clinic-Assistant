import { ClipboardCheck, FileText, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import Alert from "../components/Alert";
import ConfirmDialog from "../components/ConfirmDialog";
import CredentialPicker from "../components/doctor-application/CredentialPicker";
import ProfessionalFields from "../components/doctor-application/ProfessionalFields";
import {
  professionalPayload,
  professionalServerErrors,
  professionalValues,
  uploadCredentials,
  validateProfessional,
} from "../components/doctor-application/professional";
import { getErrorMessage } from "../services/api";
import { getPublicDepartments } from "../services/departmentService";
import {
  APPLICATION_STATUS,
  CREDENTIAL_TYPES,
  getMyApplication,
  removeApplicationDocument,
  REQUIREMENT_LABELS,
  updateMyApplication,
} from "../services/doctorApplicationService";
import { formatBytes } from "../services/files";

const NO_FILES = Object.fromEntries(CREDENTIAL_TYPES.map((t) => [t.value, null]));
const TYPE_LABEL = Object.fromEntries(CREDENTIAL_TYPES.map((t) => [t.value, t.label]));
const formatDate = (iso) => new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(iso));

function StatusCard({ application }) {
  const status = APPLICATION_STATUS[application.status];
  const pending = application.status === "pending_review";
  return (
    <section className="card application-status" aria-labelledby="application-status-title">
      <div className="section-head">
        <ShieldCheck className="icon" size={22} aria-hidden="true" />
        <h3 id="application-status-title">Verification status</h3>
        <span className={`badge ${status.tone}`}>{status.label}</span>
      </div>
      <p className="muted small">Submitted {formatDate(application.submitted_at)}</p>
      {pending && (
        <p>
          The clinic administration reviews your credentials before your profile is published. Until then you cannot
          see patients or receive appointments.
        </p>
      )}
      {application.status === "rejected" && (
        <p>Your application was not approved. Contact the clinic administration if you have questions.</p>
      )}
      {application.review_notes && (
        <p className="review-notes">
          <strong>Note from the reviewer:</strong> {application.review_notes}
        </p>
      )}
      {pending &&
        (application.missing_for_approval.length > 0 ? (
          <div className="missing-list">
            <p>Before your application can be approved, please provide:</p>
            <ul>
              {application.missing_for_approval.map((name) => (
                <li key={name}>{REQUIREMENT_LABELS[name] ?? name}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="muted">Your application has the information needed for review.</p>
        ))}
    </section>
  );
}

/**
 * The doctor applicant's own application: status, professional details and
 * credential documents. Editable while pending review; read-only afterwards.
 */
export default function DoctorApplication() {
  const [application, setApplication] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [values, setValues] = useState(null);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [notice, setNotice] = useState("");
  const [departments, setDepartments] = useState(null);
  const [departmentsError, setDepartmentsError] = useState("");
  const [files, setFiles] = useState(NO_FILES);
  const [progress, setProgress] = useState({});
  const [uploading, setUploading] = useState(false);
  const [uploadResults, setUploadResults] = useState([]);
  const [removing, setRemoving] = useState(null);
  const [removeError, setRemoveError] = useState("");

  useEffect(() => {
    let cancelled = false;
    getMyApplication()
      .then((res) => {
        if (cancelled) return;
        setApplication(res.data);
        setValues(professionalValues(res.data));
      })
      .catch((err) => !cancelled && setLoadError(getErrorMessage(err, "Could not load your application")));
    getPublicDepartments()
      .then((res) => !cancelled && setDepartments(res.data.items ?? []))
      .catch(() => {
        if (cancelled) return;
        setDepartments([]);
        setDepartmentsError("Departments could not be loaded right now.");
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const refresh = async () => {
    const res = await getMyApplication();
    setApplication(res.data);
    return res.data;
  };

  if (!application) {
    return (
      <div>
        <header className="page-head">
          <h1>My Doctor Application</h1>
        </header>
        {loadError ? (
          <div className="card" role="alert">
            <p>{loadError}</p>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setLoadError("");
                setAttempt((n) => n + 1);
              }}
            >
              Try again
            </button>
          </div>
        ) : (
          <div className="card skeleton" style={{ height: 240 }} role="status" aria-label="Loading your application" />
        )}
      </div>
    );
  }

  const editable = application.status === "pending_review";
  const chosen = Object.values(files).some(Boolean);

  const save = async (e) => {
    e.preventDefault();
    const found = validateProfessional(values);
    setErrors(found);
    setNotice("");
    setSaveError("");
    if (Object.keys(found).length > 0) return;
    setSaving(true);
    try {
      const res = await updateMyApplication(professionalPayload(values, { clearBlanks: true }));
      setApplication(res.data);
      setValues(professionalValues(res.data));
      setNotice("Your professional details were saved.");
    } catch (err) {
      setErrors(professionalServerErrors(err));
      setSaveError(getErrorMessage(err, "Could not save your details"));
    } finally {
      setSaving(false);
    }
  };

  const upload = async () => {
    setUploading(true);
    setUploadResults([]);
    const results = await uploadCredentials(files, (type, percent) =>
      setProgress((current) => ({ ...current, [type]: percent }))
    );
    // Keep the files that failed, so the user can try again.
    setFiles((current) =>
      Object.fromEntries(Object.entries(current).map(([type, file]) => [type, results.find((r) => r.type === type)?.ok ? null : file]))
    );
    setProgress({});
    setUploadResults(results);
    try {
      await refresh();
    } catch {
      // The list refreshes on the next visit; the results above are accurate.
    }
    setUploading(false);
  };

  const confirmRemove = async () => {
    setRemoveError("");
    try {
      await removeApplicationDocument(removing.id);
      await refresh();
      setRemoving(null);
    } catch (err) {
      setRemoveError(getErrorMessage(err, "Could not remove the document"));
    }
  };

  return (
    <div className="doctor-application">
      <header className="page-head">
        <div>
          <h1>My Doctor Application</h1>
          <p className="muted">Complete your professional details and submit your credentials for verification.</p>
        </div>
      </header>

      <StatusCard application={application} />

      <form className="card application-details" onSubmit={save} noValidate aria-labelledby="application-details-title">
        <div className="section-head">
          <ClipboardCheck className="icon" size={22} aria-hidden="true" />
          <h3 id="application-details-title">Professional Information</h3>
        </div>
        <Alert kind="success">{notice}</Alert>
        <Alert>{saveError}</Alert>
        <ProfessionalFields
          idPrefix="application"
          values={values}
          errors={errors}
          onChange={(field, value) => {
            setValues((current) => ({ ...current, [field]: value }));
            setErrors((current) => ({ ...current, [field]: undefined }));
          }}
          departments={departments}
          departmentsError={departmentsError}
          disabled={!editable || saving}
        />
        {editable && (
          <div className="row">
            <button type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save details"}
            </button>
          </div>
        )}
      </form>

      <section className="card application-documents" aria-labelledby="application-documents-title">
        <div className="section-head">
          <FileText className="icon" size={22} aria-hidden="true" />
          <h3 id="application-documents-title">Professional Verification Documents</h3>
        </div>
        <p className="muted small">
          Your documents are stored privately. Only the clinic administration can open them, to verify your
          credentials.
        </p>

        {application.documents.length === 0 ? (
          <p className="muted">No documents uploaded yet.</p>
        ) : (
          <ul className="uploaded-documents">
            {application.documents.map((d) => (
              <li key={d.id}>
                <span>
                  <strong>{TYPE_LABEL[d.document_type] ?? d.document_type}</strong>
                  <span className="muted small">
                    {d.filename ?? "Unnamed file"} · {formatBytes(d.size_bytes)} · uploaded {formatDate(d.uploaded_at)}
                  </span>
                </span>
                {editable && (
                  <button
                    type="button"
                    className="secondary small-button"
                    onClick={() => setRemoving(d)}
                    aria-label={`Remove ${TYPE_LABEL[d.document_type] ?? "document"}`}
                  >
                    <Trash2 size={15} aria-hidden="true" /> Remove
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        {editable && (
          <>
            <h4 className="subhead">Add documents</h4>
            <CredentialPicker
              idPrefix="application-credential"
              files={files}
              progress={progress}
              disabled={uploading}
              onChange={(type, file) => setFiles((current) => ({ ...current, [type]: file }))}
            />
            {uploadResults.length > 0 && (
              <ul className="upload-results" role="status">
                {uploadResults.map((u) => (
                  <li key={u.type} className={u.ok ? "ok" : "failed"}>
                    <strong>{u.label}:</strong> {u.ok ? "uploaded" : `not uploaded. ${u.message}`}
                  </li>
                ))}
              </ul>
            )}
            <div className="row">
              <button type="button" onClick={upload} disabled={!chosen || uploading} aria-busy={uploading}>
                {uploading ? "Uploading…" : "Upload selected documents"}
              </button>
            </div>
          </>
        )}
      </section>

      {removing && (
        <ConfirmDialog
          title="Remove document?"
          confirmLabel="Remove"
          danger
          error={removeError}
          onConfirm={confirmRemove}
          onCancel={() => {
            setRemoving(null);
            setRemoveError("");
          }}
        >
          <p>
            {TYPE_LABEL[removing.document_type]} ({removing.filename ?? "file"}) will be removed from your application.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
