import { FileText, UserCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { getErrorMessage } from "../../services/api";
import {
  APPLICATION_STATUS,
  approveApplication,
  CREDENTIAL_TYPES,
  getApplication,
  getApplicationDocumentLink,
  listApplications,
  rejectApplication,
  REQUIREMENT_LABELS,
} from "../../services/doctorApplicationService";
import { formatFee } from "../../utils/format";
import Alert from "../Alert";
import ConfirmDialog from "../ConfirmDialog";
import FormField from "../FormField";

const submitted = (iso) => new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }).format(new Date(iso));
const docLabel = (type) => CREDENTIAL_TYPES.find((t) => t.value === type)?.label ?? type;

function ReviewDialog({ applicationId, onClose, onDecided }) {
  const [app, setApp] = useState(null);
  const [error, setError] = useState("");
  const [decision, setDecision] = useState(null); // "approve" | "reject"
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [notesError, setNotesError] = useState("");

  useEffect(() => {
    let live = true;
    getApplication(applicationId)
      .then((res) => live && setApp(res.data))
      .catch((err) => live && setError(getErrorMessage(err, "Could not load the application")));
    return () => {
      live = false;
    };
  }, [applicationId]);

  const openDocument = async (doc) => {
    setError("");
    try {
      const res = await getApplicationDocumentLink(applicationId, doc.id);
      window.open(res.data.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(getErrorMessage(err, "Could not open the document"));
    }
  };

  const decide = async () => {
    if (decision === "reject" && !notes.trim()) return setNotesError("Give the applicant a reason.");
    setBusy(true);
    setError("");
    try {
      await (decision === "approve" ? approveApplication(applicationId, notes.trim()) : rejectApplication(applicationId, notes.trim()));
      onDecided(decision === "approve" ? `${app.name} was approved and is now a doctor.` : `${app.name}'s application was not approved.`);
    } catch (err) {
      setError(getErrorMessage(err, "Could not record the decision"));
      setBusy(false);
    }
  };

  const pending = app?.status === "pending_review";
  const rows = app && [
    ["Email", app.email],
    ["Phone", app.phone],
    ["Specialization", app.specialization],
    ["Department", app.department_name],
    ["License no.", app.license_number],
    ["Registration authority", app.registration_authority],
    ["Experience", app.years_of_experience == null ? null : `${app.years_of_experience} years`],
    ["Qualifications", app.qualifications],
    ["Institution", app.institution],
    ["Languages", app.languages],
    ["Consultation fee", app.consultation_fee == null ? null : formatFee(app.consultation_fee)],
    ["Submitted", submitted(app.submitted_at)],
  ];

  if (decision)
    return (
      <ConfirmDialog
        title={decision === "approve" ? `Approve ${app.name}?` : `Reject ${app.name}?`}
        confirmLabel={decision === "approve" ? "Approve" : "Reject application"}
        danger={decision === "reject"}
        busy={busy}
        error={error}
        onConfirm={decide}
        onCancel={() => setDecision(null)}
      >
        <p>
          {decision === "approve"
            ? "A doctor profile is created from this application and the account gains doctor access. They can be booked once they have a schedule."
            : "The applicant keeps their login without clinical access and can read your reason."}
        </p>
        <FormField id="review-notes" label={decision === "approve" ? "Notes (optional)" : "Reason"} error={notesError}>
          <textarea id="review-notes" rows={3} maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </FormField>
      </ConfirmDialog>
    );

  return (
    <ConfirmDialog
      title="Doctor application"
      confirmLabel={pending ? "Approve…" : "Close"}
      cancelLabel={pending ? "Close" : "Back"}
      onConfirm={() => (pending ? setDecision("approve") : onClose())}
      onCancel={onClose}
      className="wide-dialog"
    >
      <Alert>{error}</Alert>
      {!app && !error && <p role="status">Loading application…</p>}
      {app && (
        <>
          <div className="user-detail-head">
            <strong>{app.name}</strong>
            <span className={`badge ${APPLICATION_STATUS[app.status].tone}`}>{APPLICATION_STATUS[app.status].label}</span>
          </div>
          <dl className="user-detail-list">
            {rows.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value || <span className="muted">Not provided</span>}</dd>
              </div>
            ))}
          </dl>
          {app.bio && <p>{app.bio}</p>}
          <h3 className="dept-subhead">Documents</h3>
          {app.documents.length === 0 ? (
            <p className="muted">No documents uploaded.</p>
          ) : (
            <ul className="dept-doctor-list">
              {app.documents.map((doc) => (
                <li key={doc.id}>
                  <FileText size={18} aria-hidden="true" />
                  <span>{docLabel(doc.document_type)}</span>
                  <button type="button" className="secondary small-button" onClick={() => openDocument(doc)}>
                    Open
                  </button>
                </li>
              ))}
            </ul>
          )}
          {pending && app.missing_for_approval.length > 0 && (
            <Alert kind="warn">
              Missing before approval: {app.missing_for_approval.map((m) => REQUIREMENT_LABELS[m] ?? m).join(", ")}.
            </Alert>
          )}
          {app.review_notes && (
            <p>
              <strong>Review notes:</strong> {app.review_notes}
            </p>
          )}
          {pending && (
            <button type="button" className="danger small-button" onClick={() => setDecision("reject")}>
              Reject…
            </button>
          )}
        </>
      )}
    </ConfirmDialog>
  );
}

/**
 * Doctor applications (D77 / D90): self-registered doctors waiting for an
 * administrator. An applicant is not a doctor and is never listed or bookable
 * until approved here.
 */
export default function ApplicationsPanel({ onDecided }) {
  const [status, setStatus] = useState("pending_review");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [reviewing, setReviewing] = useState(null);

  useEffect(() => {
    let live = true;
    listApplications({ status: status || undefined, page_size: 50 })
      .then((res) => {
        if (!live) return;
        setData(res.data);
        setError("");
      })
      .catch((err) => live && setError(getErrorMessage(err, "Could not load applications")));
    return () => {
      live = false;
    };
  }, [status, attempt]);

  return (
    <section className="card admin-access" aria-label="Doctor applications">
      <div className="section-head">
        <UserCheck className="icon" size={20} aria-hidden="true" />
        <h3>Doctor Applications{status === "pending_review" && data ? ` (${data.total} pending)` : ""}</h3>
        <label className="patients-filter">
          <span className="sr-only">Application status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="pending_review">Pending review</option>
            <option value="approved">Approved</option>
            <option value="rejected">Not approved</option>
            <option value="">All</option>
          </select>
        </label>
      </div>
      {error ? (
        <div role="alert" className="appt-error">
          <p>{error}</p>
          <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </div>
      ) : !data ? (
        <p role="status">Loading applications…</p>
      ) : data.items.length === 0 ? (
        <p className="muted">No applications here.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Applicant</th>
                <th>Specialization</th>
                <th>Department</th>
                <th>Documents</th>
                <th>Submitted</th>
                <th>Status</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((a) => (
                <tr key={a.id}>
                  <td>
                    {a.name}
                    <div className="muted small">{a.email}</div>
                  </td>
                  <td>{a.specialization ?? "—"}</td>
                  <td>{a.department_name ?? "—"}</td>
                  <td>{a.document_count}</td>
                  <td>{submitted(a.submitted_at)}</td>
                  <td>
                    <span className={`badge ${APPLICATION_STATUS[a.status].tone}`}>{APPLICATION_STATUS[a.status].label}</span>
                  </td>
                  <td>
                    <button type="button" className="secondary small-button" aria-label={`Review application from ${a.name}`} onClick={() => setReviewing(a.id)}>
                      Review
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {reviewing && (
        <ReviewDialog
          applicationId={reviewing}
          onClose={() => setReviewing(null)}
          onDecided={(text) => {
            setReviewing(null);
            setAttempt((n) => n + 1);
            onDecided(text);
          }}
        />
      )}
    </section>
  );
}
