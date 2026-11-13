import {
  ArrowRight,
  CalendarCheck,
  CalendarDays,
  ChartColumn,
  Check,
  CircleAlert,
  CircleHelp,
  ClipboardList,
  Copy,
  FileText,
  History,
  Paperclip,
  Plus,
  RotateCw,
  Search,
  SendHorizontal,
  Sparkle,
  Square,
  Stethoscope,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";
import avatar from "../../assets/clinic-ai-avatar.png";
import { getErrorMessage } from "../../services/api";
import { decideAction, deleteConversation, getConversation, listConversations } from "../../services/aiService";
import { ACCEPT, fileSize, suggestionsFor, unavailableReason, usageNote } from "../../utils/assistant";
import AssistantResults from "./AssistantResults";
import SafeMarkdown from "./SafeMarkdown";
import ThinkingWords from "./ThinkingWords";

const time = (iso) => new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
const STATUS_LABEL = { uploading: "Uploading…", processing: "Processing…", ready: "Ready", no_text: "Ready", failed: "Failed" };
const SUGGESTION_ICONS = {
  search: Search,
  calendar: CalendarDays,
  list: ClipboardList,
  help: CircleHelp,
  stethoscope: Stethoscope,
  user: UserRound,
  chart: ChartColumn,
  file: FileText,
};
// Proposed actions (D104): the question itself is the message text above the card
// ("Confirm your appointment with ... on ...?"); the card adds only the buttons and
// anything the question does not say.
const ACTIONS = {
  book_appointment: { label: "Confirm booking", yes: "Confirm", no: "Cancel", busy: "Booking…" },
  cancel_appointment: { label: "Confirm cancellation", yes: "Confirm cancellation", no: "Keep appointment", busy: "Cancelling…" },
  reschedule_appointment: { label: "Confirm change", yes: "Confirm change", no: "Keep original", busy: "Moving…" },
  walk_in_token: { label: "Confirm token", yes: "Get token", no: "Cancel", busy: "Issuing…" },
};
const when = (a) => a.when_text ?? a.local_time;

function actionResult(a) {
  switch (a.status) {
    case "booked":
      return `Appointment booked with ${a.doctor_name} for ${when(a)}.`;
    case "cancelled_appointment":
      return `Your appointment with ${a.doctor_name} on ${when(a)} was cancelled.`;
    case "rescheduled":
      return `Moved to ${a.new_when_text ?? a.new_local_time}.`;
    case "token_issued":
      return `Token #${a.token_number} for ${a.doctor_name} on ${a.when_text}. Check in at reception when you arrive.`;
    case "cancelled":
      return { book_appointment: "Not booked.", cancel_appointment: "Kept your appointment.", reschedule_appointment: "Kept the original time.", walk_in_token: "No token issued." }[a.type];
    case "expired":
      return "This expired before it was confirmed. Ask again to check the current times.";
    case "failed":
      return `Couldn't complete it: ${a.error}`;
    default:
      return "";
  }
}

function ActionCard({ message, conversationId, onUpdated }) {
  const action = message.action;
  const kind = ACTIONS[action.type] ?? { label: "Confirm", yes: "Confirm", no: "Cancel", busy: "Working…" };
  const [busy, setBusy] = useState(null); // true = confirming, false = declining
  const [error, setError] = useState("");
  // The answer was lost (no response, server error): the booking may have gone
  // through. Never offer it again blindly; check what the server has first (D108).
  const [uncertain, setUncertain] = useState(false);
  const check = async () => {
    setBusy(true);
    try {
      const saved = (await getConversation(conversationId)).data.messages.find((m) => m.id === message.id);
      if (saved) onUpdated(saved);
      setUncertain(false);
      setError(saved?.action?.status === "pending" ? "It did not go through. You can decide again." : "");
    } catch {
      setError("We still couldn't check it. Try again in a moment, or look under My Appointments.");
    } finally {
      setBusy(null);
    }
  };
  const decide = async (confirm) => {
    if (busy !== null || uncertain) return; // one decision only
    setBusy(confirm);
    setError("");
    try {
      const res = await decideAction(conversationId, message.id, confirm);
      onUpdated(res.data);
    } catch (err) {
      const status = err?.response?.status;
      if (err?.response?.data?.error?.code === "ACTION_DECIDED") {
        await check(); // decided already (e.g. in another tab): show what happened
        return;
      }
      if (!err?.response || status >= 500) {
        setUncertain(true);
        setError("We couldn't confirm whether this went through.");
      } else {
        setError(getErrorMessage(err, "Could not record your decision"));
      }
    } finally {
      setBusy(null);
    }
  };
  // Only what the one-line question does not already say.
  const rows = [
    ["Patient", action.patient_name && `${action.patient_name}${action.patient_mrn ? ` (${action.patient_mrn})` : ""}`],
    ["Fee", action.consultation_fee],
    ["Reason", action.reason],
  ].filter(([, v]) => v);
  return (
    <div className={`ai-action ai-action-${action.status}`} role="group" aria-label={kind.label}>
      {rows.length > 0 && (
        <dl>
          {rows.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {action.status === "pending" ? (
        <div className="ai-action-buttons">
          {uncertain ? (
            <button type="button" className="small-button" disabled={busy !== null} onClick={check}>
              {busy !== null ? "Checking…" : "Check status"}
            </button>
          ) : (
            <>
              <button type="button" className="small-button" disabled={busy !== null} onClick={() => decide(true)}>
                {busy === true ? kind.busy : kind.yes}
              </button>
              <button type="button" className="secondary small-button" disabled={busy !== null} onClick={() => decide(false)}>
                {kind.no}
              </button>
            </>
          )}
        </div>
      ) : (
        <p className="ai-action-result" role="status">
          <CalendarCheck size={15} aria-hidden="true" /> {actionResult(action)}
        </p>
      )}
      {error && (
        <p className="field-error" role="status">
          {error}
        </p>
      )}
    </div>
  );
}

// The short medical note the assistant puts first on treatment questions (D104), shown subtly.
const DISCLAIMER = "AI can make mistakes. Please consult a doctor for medical advice.";

// A question that failed (D108): what happened in one line, Try again when it can help.
function FailureCard({ failure, sending, onRetry, onDismiss }) {
  return (
    <li className="ai-failure" role="alert">
      <CircleAlert size={18} aria-hidden="true" />
      <div>
        <strong>{failure.title}</strong>
        <p>{failure.message}</p>
        {failure.reference && <p className="ai-msg-note">Reference: {failure.reference}</p>}
        <div className="ai-failure-actions">
          {failure.retry && (
            <button type="button" className="small-button" disabled={sending} onClick={onRetry}>
              <RotateCw size={14} aria-hidden="true" /> Try again
            </button>
          )}
          <button type="button" className="secondary small-button" onClick={onDismiss}>
            Dismiss
          </button>
        </div>
      </div>
    </li>
  );
}

// Memoised: while an answer streams, only the streaming message re-renders (and re-parses its Markdown).
const Message = memo(function Message({ message, conversationId, onUpdated, documents, canBook, ownRecord, onAsk }) {
  const [copied, setCopied] = useState(false);
  const mine = message.role === "user";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked: nothing to do
    }
  };
  const streaming = message.streaming && !message.content;
  return (
    <li className={`ai-msg ${mine ? "ai-msg-user" : "ai-msg-assistant"}`}>
      {!mine && <img className="ai-msg-avatar" src={avatar} alt="" />}
      <div className="ai-bubble">
        {streaming ? (
          <ThinkingWords />
        ) : mine ? (
          <p className="ai-user-text">{message.content}</p>
        ) : (
          <>
            {message.content.startsWith(DISCLAIMER) && <p className="ai-medical-note">{DISCLAIMER}</p>}
            <SafeMarkdown text={message.content.startsWith(DISCLAIMER) ? message.content.slice(DISCLAIMER.length).trim() : message.content} />
          </>
        )}
        {message.incomplete && <p className="ai-msg-note">Response interrupted</p>}
        {message.document_ids?.length > 0 && (
          <ul className="ai-msg-files" aria-label="Attached files">
            {message.document_ids.map((id) => (
              <li key={id}>
                <FileText size={14} aria-hidden="true" /> {documents[id]?.filename ?? "Document"}
              </li>
            ))}
          </ul>
        )}
        {message.results?.length > 0 && <AssistantResults results={message.results} canBook={canBook} ownRecord={ownRecord} onAsk={onAsk} />}
        {message.action && <ActionCard message={message} conversationId={conversationId} onUpdated={onUpdated} />}
        {message.failed && <p className="ai-msg-note">Not sent</p>}
        {!message.streaming && (
          <div className="ai-msg-meta">
            {message.created_at && <time dateTime={message.created_at}>{time(message.created_at)}</time>}
            {!mine && !message.pending && (
              <button type="button" className="icon-button" aria-label={copied ? "Copied" : "Copy response"} onClick={copy}>
                {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
              </button>
            )}
          </div>
        )}
      </div>
    </li>
  );
});

function HistoryList({ onOpen, onClose }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    listConversations()
      .then((res) => live && setItems(res.data))
      .catch((err) => live && setError(getErrorMessage(err, "Could not load conversations")));
    return () => {
      live = false;
    };
  }, []);
  const remove = async (id) => {
    try {
      await deleteConversation(id);
      setItems((list) => list.filter((c) => c.id !== id));
    } catch (err) {
      setError(getErrorMessage(err, "Could not delete the conversation"));
    }
  };
  return (
    <div className="ai-history">
      <div className="ai-history-head">
        <h3>Recent conversations</h3>
        <button type="button" className="link-button" onClick={onClose}>
          Back
        </button>
      </div>
      {error && <p className="field-error">{error}</p>}
      {items === null && !error && <p role="status">Loading…</p>}
      {items?.length === 0 && <p className="muted ai-history-empty">No saved conversations yet. Ask something and it will appear here.</p>}
      <ul>
        {items?.map((c) => (
          <li key={c.id}>
            <button type="button" className="ai-history-item" onClick={() => onOpen(c.id)}>
              <strong>{c.title}</strong>
              <span className="muted small">{new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(c.updated_at))}</span>
            </button>
            <button type="button" className="icon-button" aria-label={`Delete conversation ${c.title}`} onClick={() => remove(c.id)}>
              <Trash2 size={15} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Welcome({ status, sending, onAction }) {
  return (
    <div className="ai-welcome">
      <div className="ai-hero" aria-hidden="true">
        <Sparkle className="ai-spark s1" size={18} />
        <Sparkle className="ai-spark s2" size={14} />
        <Sparkle className="ai-spark s3" size={14} />
        <span className="ai-hero-halo" />
        <img src={avatar} alt="" />
      </div>
      <h3>
        <span className="ai-hello">Hello!</span> How can I help you today?
      </h3>
      <p>I can help you find doctors, manage appointments, answer health questions, and guide you through clinic services.</p>
      <div className="ai-quick-actions">
        {suggestionsFor(status).map((action) => {
          const Icon = SUGGESTION_ICONS[action.icon];
          const reason = status ? unavailableReason(action, status) : null;
          return (
            <button
              key={action.key}
              type="button"
              className={`ai-quick ai-quick-${action.tone}`}
              disabled={sending || !status || Boolean(reason)}
              aria-describedby={reason ? `ai-quick-${action.key}-why` : undefined}
              onClick={() => onAction(action.prompt)}
            >
              <span className="ai-quick-icon" aria-hidden="true">
                <Icon size={24} />
              </span>
              <span className="ai-quick-text">
                <strong>{action.title}</strong>
                <span>{action.text}</span>
                {reason && (
                  <em id={`ai-quick-${action.key}-why`} className="ai-quick-why">
                    {reason}
                  </em>
                )}
              </span>
              <ArrowRight className="ai-quick-arrow" size={18} aria-hidden="true" />
            </button>
          );
        })}
      </div>
    </div>
  );
}

/**
 * The assistant drawer (D96, redesigned D97). State (conversation, messages,
 * attachments) lives in ClinicAssistant so it survives navigation; this renders it.
 */
export default function AssistantPanel({ assistant, onClose }) {
  const {
    status,
    statusError,
    conversationId,
    messages,
    documents,
    sending,
    error,
    draft,
    setDraft,
    attachments,
    addFiles,
    removeAttachment,
    retryAttachment,
    send,
    failure,
    retry,
    dismissFailure,
    stop,
    newConversation,
    openConversation,
    updateMessage,
    ask,
    usage,
  } = assistant;
  const [showHistory, setShowHistory] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const list = useRef(null);
  const textarea = useRef(null);
  const fileInput = useRef(null);

  useEffect(() => {
    textarea.current?.focus();
  }, []);
  const lastLength = messages.at(-1)?.content?.length ?? 0;
  useEffect(() => {
    list.current?.scrollTo?.({ top: list.current.scrollHeight });
  }, [messages.length, lastLength, failure]);

  const configured = status?.configured;
  const documentsEnabled = Boolean(status?.documents_enabled);
  const canBook = Boolean(status?.capabilities?.some((c) => c === "book_appointment" || c === "book_for_patient"));
  const usageText = usageNote(usage);
  // A patient's document links open their own profile; a doctor's open the patient page.
  const ownRecord = !status?.roles?.includes("doctor");
  const busyFiles = attachments.some((a) => a.status === "uploading" || a.status === "processing");
  const canSend = configured && !sending && !busyFiles && draft.trim().length > 0;

  const onKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (canSend) send();
    }
  };

  return (
    <aside
      className={`ai-panel${dragOver ? " drag-over" : ""}`}
      role="dialog"
      aria-modal="false"
      aria-label="Clinic AI Assistant"
      onKeyDown={(e) => e.key === "Escape" && onClose()}
      onDragOver={(e) => {
        if (!documentsEnabled) return;
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        if (!documentsEnabled) return;
        e.preventDefault();
        setDragOver(false);
        addFiles([...e.dataTransfer.files]);
      }}
    >
      <header className="ai-panel-head">
        <img src={avatar} alt="" className="ai-panel-avatar" />
        <div className="ai-panel-title">
          <h2>Clinic AI Assistant</h2>
          <p>Your AI Health &amp; Clinic Assistant</p>
        </div>
        <div className="ai-panel-actions">
          <button
            type="button"
            className="ai-head-button"
            aria-label="New conversation"
            disabled={sending}
            onClick={() => {
              setShowHistory(false);
              newConversation();
            }}
          >
            <Plus size={20} aria-hidden="true" />
          </button>
          <button type="button" className="ai-head-button" aria-label="Conversation history" aria-pressed={showHistory} onClick={() => setShowHistory((v) => !v)}>
            <History size={19} aria-hidden="true" />
          </button>
          <button type="button" className="ai-head-close" aria-label="Close assistant" onClick={onClose}>
            <X size={22} aria-hidden="true" />
          </button>
        </div>
      </header>

      {statusError && <p className="ai-banner error" role="alert">{statusError}</p>}
      {status && !configured && (
        <p className="ai-banner" role="status">
          The AI assistant is not set up on this server yet. An administrator needs to configure an AI provider.
        </p>
      )}

      {showHistory ? (
        <HistoryList
          onClose={() => setShowHistory(false)}
          onOpen={(id) => {
            setShowHistory(false);
            openConversation(id);
          }}
        />
      ) : (
        <div className="ai-messages" ref={list}>
          {messages.length === 0 ? (
            <Welcome status={status} sending={sending} onAction={(prompt) => send(prompt)} />
          ) : (
            <ul className="ai-message-list" aria-live="polite" aria-label="Conversation">
              {messages.map((m) => (
                <Message key={m.id} message={m} conversationId={conversationId} onUpdated={updateMessage} documents={documents} canBook={canBook} ownRecord={ownRecord} onAsk={sending ? undefined : ask} />
              ))}
              {failure && <FailureCard failure={failure} sending={sending} onRetry={retry} onDismiss={dismissFailure} />}
            </ul>
          )}
        </div>
      )}

      <form
        className="ai-composer"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSend) send();
        }}
      >
        {error && (
          <p className="ai-banner error" role="alert">
            {error}
          </p>
        )}
        {attachments.length > 0 && (
          <ul className="ai-attachments" aria-label="Files to send">
            {attachments.map((a) => (
              <li key={a.key} className={`ai-attachment ${a.status}`}>
                {a.preview ? <img className="ai-attachment-thumb" src={a.preview} alt="" /> : <FileText size={18} aria-hidden="true" />}
                <span className="ai-attachment-name" title={a.name}>
                  {a.name}
                </span>
                <span className="muted small">
                  {fileSize(a.size)} · {a.status === "uploading" && a.progress != null ? `${a.progress}%` : STATUS_LABEL[a.status]}
                </span>
                {a.status === "failed" && a.file && (
                  <button type="button" className="icon-button" aria-label={`Retry ${a.name}`} onClick={() => retryAttachment(a.key)}>
                    <RotateCw size={14} aria-hidden="true" />
                  </button>
                )}
                <button type="button" className="icon-button" aria-label={`Remove ${a.name}`} onClick={() => removeAttachment(a.key)}>
                  <X size={14} aria-hidden="true" />
                </button>
                {a.error && <span className="field-error ai-attachment-error">{a.error}</span>}
              </li>
            ))}
          </ul>
        )}
        <div className="ai-composer-row">
          <button
            type="button"
            className="ai-attach"
            aria-label="Attach files"
            title={documentsEnabled ? "Attach PDF, images, DOCX or TXT" : "Document analysis is not enabled on this server"}
            disabled={!documentsEnabled || sending}
            onClick={() => fileInput.current?.click()}
          >
            <Paperclip size={22} aria-hidden="true" />
          </button>
          <input
            ref={fileInput}
            type="file"
            multiple
            accept={ACCEPT}
            hidden
            data-testid="ai-file-input"
            onChange={(e) => {
              addFiles([...e.target.files]);
              e.target.value = "";
            }}
          />
          <label className="sr-only" htmlFor="ai-prompt">
            Message
          </label>
          <textarea
            id="ai-prompt"
            ref={textarea}
            rows={1}
            value={draft}
            maxLength={4000}
            placeholder="Ask me anything..."
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
          />
          {sending ? (
            <button type="button" className="ai-send" aria-label="Stop" onClick={stop}>
              <Square size={18} aria-hidden="true" />
            </button>
          ) : (
            <button type="submit" className="ai-send" aria-label="Send message" disabled={!canSend}>
              <SendHorizontal size={22} aria-hidden="true" />
            </button>
          )}
        </div>
        <p className="ai-disclaimer">Not a substitute for medical advice. In an emergency, contact emergency services.</p>
        {configured && usageText && <p className="ai-usage">{usageText}</p>}
      </form>
    </aside>
  );
}
