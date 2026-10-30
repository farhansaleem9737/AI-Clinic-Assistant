import {
  ArrowRight,
  CalendarCheck,
  CalendarDays,
  ChartColumn,
  Check,
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
import { useEffect, useRef, useState } from "react";
import avatar from "../../assets/clinic-ai-avatar.png";
import { getErrorMessage } from "../../services/api";
import { decideAction, deleteConversation, listConversations } from "../../services/aiService";
import { ACCEPT, fileSize, suggestionsFor, unavailableReason, usageNote } from "../../utils/assistant";
import AssistantResults from "./AssistantResults";
import SafeMarkdown from "./SafeMarkdown";

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
const ACTION_TITLES = {
  book_appointment: "Book this appointment?",
  cancel_appointment: "Cancel this appointment?",
  reschedule_appointment: "Move this appointment?",
};
const ACTION_RESULTS = {
  booked: "Booked. You can see it in Appointments.",
  cancelled_appointment: "The appointment was cancelled.",
  rescheduled: "The appointment was moved.",
  cancelled: "No change was made.",
  expired: "This proposal expired before it was confirmed. Ask again to check the current times.",
};

function ActionCard({ message, conversationId, onUpdated }) {
  const action = message.action;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const decide = async (confirm) => {
    setBusy(true);
    setError("");
    try {
      const res = await decideAction(conversationId, message.id, confirm);
      onUpdated(res.data);
    } catch (err) {
      setError(getErrorMessage(err, "Could not record your decision"));
    } finally {
      setBusy(false);
    }
  };
  const rows = [
    ["Patient", action.patient_name && `${action.patient_name}${action.patient_mrn ? ` (${action.patient_mrn})` : ""}`],
    ["Doctor", action.doctor_name],
    ["Department", action.department],
    [action.type === "reschedule_appointment" ? "Now" : "When", action.local_time],
    ["New time", action.new_local_time],
    ["Fee", action.consultation_fee],
    ["Reason", action.reason],
  ].filter(([, v]) => v);
  const label = ACTION_TITLES[action.type] ?? "Confirm this action?";
  return (
    <div className={`ai-action ai-action-${action.status}`} role="group" aria-label={label}>
      <strong>
        <CalendarCheck size={16} aria-hidden="true" /> {label}
      </strong>
      <dl>
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {action.status === "pending" && action.expires_at && (
        <p className="muted small ai-action-expiry">Confirm by {time(action.expires_at)}; after that, ask again.</p>
      )}
      {action.status === "pending" ? (
        <div className="ai-action-buttons">
          <button type="button" className="small-button" disabled={busy} onClick={() => decide(true)}>
            Confirm
          </button>
          <button type="button" className="secondary small-button" disabled={busy} onClick={() => decide(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <p className="ai-action-result" role="status">
          {action.status === "failed" ? `Could not complete it: ${action.error}` : ACTION_RESULTS[action.status]}
        </p>
      )}
      {error && <p className="field-error">{error}</p>}
    </div>
  );
}

function Message({ message, conversationId, onUpdated, documents, canBook, ownRecord, onAsk }) {
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
          <span className="ai-typing" role="status" aria-label="Assistant is thinking">
            <span /> <span /> <span />
          </span>
        ) : mine ? (
          <p className="ai-user-text">{message.content}</p>
        ) : (
          <SafeMarkdown text={message.content} />
        )}
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
}

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
    stop,
    newConversation,
    openConversation,
    updateMessage,
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
  }, [messages.length, lastLength]);

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
                <Message key={m.id} message={m} conversationId={conversationId} onUpdated={updateMessage} documents={documents} canBook={canBook} ownRecord={ownRecord} onAsk={sending ? undefined : (text) => send(text)} />
              ))}
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
