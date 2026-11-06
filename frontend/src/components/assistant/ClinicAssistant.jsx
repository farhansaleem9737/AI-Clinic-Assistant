import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { getErrorMessage } from "../../services/api";
import {
  deleteAssistantDocument,
  getAssistantStatus,
  getAssistantUsage,
  getConversation,
  listConversations,
  streamAssistantMessage,
  uploadAssistantDocuments,
} from "../../services/aiService";
import { checkFiles, describeFailure } from "../../utils/assistant";
import { lazyPage } from "../../routes/lazyPage";
import ErrorBoundary from "../ErrorBoundary";
import AssistantLauncher from "./AssistantLauncher";

// The panel (chat, Markdown, result cards) is a separate download, started when the
// launcher is first pointed at, focused or pressed (no AI request), or on opening.
const loadPanel = () => import("./AssistantPanel");
const AssistantPanel = lazyPage(loadPanel);
const preloadPanel = () => loadPanel().catch(() => {}); // opening retries and reports a failure

let attachmentSeq = 0;
const STREAM_ID = "streaming-reply";
const PARTIAL_ID = "interrupted-reply"; // what arrived of an answer before it failed (never saved)
// Server and browser clocks may differ a little when matching a saved question.
const SAVED_SLACK_MS = 60_000;

/**
 * Clinic AI Assistant (D96/D97): one floating launcher and drawer for the
 * whole signed-in app, mounted once in AppLayout so the open conversation
 * survives page changes. Replies stream in from the server as they are
 * written; nothing is invented here. A failed or stopped request leaves the
 * message and its files in the composer.
 */
export default function ClinicAssistant() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState(null);
  const [statusError, setStatusError] = useState("");
  const [conversationId, setConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [documents, setDocuments] = useState({}); // id -> { filename }
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  // The last question that failed (D108): { kind, title, message, retry, uncertain, content, documentIds, files, optimistic }.
  const [failure, setFailure] = useState(null);
  const [usage, setUsage] = useState(null);
  const abort = useRef(null);
  const running = useRef(false); // one request at a time, even for fast double clicks
  const launcherRef = useRef(null);
  const previews = useRef(new Set());

  useEffect(() => {
    if (!open || status) return;
    let live = true;
    getAssistantStatus()
      .then((res) => live && setStatus(res.data))
      .catch((err) => live && setStatusError(getErrorMessage(err, "Could not reach the assistant")));
    return () => {
      live = false;
    };
  }, [open, status]);

  // Today's message count (D100). Optional: if it fails the note is simply not shown.
  const refreshUsage = useCallback(() => {
    getAssistantUsage()
      .then((res) => setUsage(res.data))
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (open && status?.configured) refreshUsage();
  }, [open, status, refreshUsage]);

  // Release image previews when the assistant goes away.
  useEffect(() => {
    const urls = previews.current;
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    // After the launcher is shown again.
    requestAnimationFrame(() => launcherRef.current?.focus?.());
  }, []);

  const patchAttachment = (key, changes) => setAttachments((list) => list.map((a) => (a.key === key ? { ...a, ...changes } : a)));

  const upload = (entry) => {
    patchAttachment(entry.key, { status: "uploading", progress: 0, error: "" });
    uploadAssistantDocuments([entry.file], conversationId, (progress) =>
      patchAttachment(entry.key, { progress, status: progress >= 100 ? "processing" : "uploading" })
    )
      .then((res) => {
        const doc = res.data[0];
        setDocuments((d) => ({ ...d, [doc.id]: doc }));
        patchAttachment(entry.key, {
          id: doc.id,
          status: doc.status === "failed" ? "failed" : doc.status,
          error: doc.status === "failed" ? "The file could not be read." : "",
          file: doc.status === "failed" ? entry.file : null,
        });
      })
      .catch((err) => patchAttachment(entry.key, { status: "failed", error: getErrorMessage(err, "Upload failed") }));
  };

  const addFiles = (files) => {
    if (!status) return;
    const { accepted, errors } = checkFiles(files, { maxFiles: status.max_files, maxBytes: status.max_file_bytes, already: attachments.length });
    setError(errors.join(" "));
    const entries = accepted.map((file) => {
      const preview = file.type.startsWith("image/") && typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : null;
      if (preview) previews.current.add(preview);
      return { key: `a${++attachmentSeq}`, name: file.name, size: file.size, status: "uploading", progress: 0, file, preview };
    });
    setAttachments((list) => [...list, ...entries]);
    entries.forEach(upload);
  };

  const dropPreview = (item) => {
    if (item?.preview) {
      URL.revokeObjectURL(item.preview);
      previews.current.delete(item.preview);
    }
  };

  const removeAttachment = (key) => {
    const item = attachments.find((a) => a.key === key);
    setAttachments((list) => list.filter((a) => a.key !== key));
    dropPreview(item);
    if (item?.id) deleteAssistantDocument(item.id).catch(() => {});
  };

  const retryAttachment = (key) => {
    const item = attachments.find((a) => a.key === key);
    if (item?.file) upload(item);
  };

  // The server saves a question and its answer together, only when the answer
  // is complete. A connection that broke mid-answer is the one case where it
  // may have been saved anyway: look for it before asking again (no duplicates).
  const findSaved = async ({ content, startedAt }) => {
    let id = conversationId;
    if (!id) {
      const recent = (await listConversations()).data.find((c) => Date.parse(c.updated_at) >= startedAt - SAVED_SLACK_MS);
      if (!recent) return null;
      id = recent.id;
    }
    const conversation = (await getConversation(id)).data;
    const { messages: saved } = conversation;
    const last = saved.findLastIndex((m) => m.role === "user");
    const mine = saved[last];
    if (!mine || mine.content !== content || Date.parse(mine.created_at) < startedAt - SAVED_SLACK_MS || saved[last + 1]?.role !== "assistant") return null;
    return conversation;
  };

  // One question to the assistant, first try or Try again; the user's message is shown once.
  const exchange = async ({ content, documentIds, optimistic, files, check = false }) => {
    const streaming = { id: STREAM_ID, role: "assistant", content: "", created_at: new Date().toISOString(), streaming: true };
    setMessages((list) => [
      ...list.filter((m) => m.id !== optimistic.id && m.id !== PARTIAL_ID),
      { ...optimistic, pending: true, failed: false },
      streaming,
    ]);
    setSending(true);
    setError("");
    const controller = new AbortController();
    abort.current = controller;
    const startedAt = Date.now();
    const done = (result) => {
      setConversationId(result.conversation.id);
      // A typed "yes" decides the earlier proposal: show its new state there too (D115).
      const decision = result.assistant_message.results?.find((card) => card.kind === "decision");
      setMessages((list) => [
        ...list
          .filter((m) => m.id !== optimistic.id && m.id !== STREAM_ID)
          .map((m) => (decision && m.id === decision.message_id ? { ...m, action: decision.action } : m)),
        result.user_message,
        result.assistant_message,
      ]);
      files.forEach(dropPreview);
    };
    try {
      const saved = check ? await findSaved({ content, startedAt: optimistic.startedAt ?? startedAt }) : null;
      if (saved) {
        // It had gone through: show the saved answer instead of asking again.
        setConversationId(saved.id);
        setMessages(saved.messages);
        files.forEach(dropPreview);
        return;
      }
      done(
        await streamAssistantMessage(
          { conversation_id: conversationId, text: content, document_ids: documentIds },
          {
            signal: controller.signal,
            onDelta: (chunk) => setMessages((list) => list.map((m) => (m.id === STREAM_ID ? { ...m, content: m.content + chunk } : m))),
          }
        )
      );
    } catch (err) {
      if (err?.name === "AbortError") {
        // Stopped: nothing was saved; the message and its files go back to the composer.
        setMessages((list) => list.filter((m) => m.id !== optimistic.id && m.id !== STREAM_ID));
        setDraft(content);
        setAttachments((list) => [...files.filter((f) => !list.includes(f)), ...list]);
        return;
      }
      // The message stays where it was, with what had arrived of the answer
      // (marked as interrupted) and a short explanation with Try again.
      setMessages((list) =>
        list.flatMap((m) => {
          if (m.id === optimistic.id) return [{ ...m, pending: false, failed: true }];
          if (m.id === STREAM_ID) return m.content ? [{ ...m, id: PARTIAL_ID, streaming: false, incomplete: true }] : [];
          return [m];
        })
      );
      setFailure({
        ...describeFailure(err),
        content,
        documentIds,
        files,
        optimistic: { ...optimistic, startedAt: optimistic.startedAt ?? startedAt },
      });
    } finally {
      abort.current = null;
      running.current = false;
      setSending(false);
      refreshUsage();
    }
  };

  const send = async (text = draft) => {
    const content = text.trim();
    if (!content || sending || running.current) return;
    running.current = true;
    // A new question replaces a failed one that was never saved.
    if (failure) {
      setMessages((list) => list.filter((m) => m.id !== failure.optimistic.id && m.id !== PARTIAL_ID));
      failure.files.forEach(dropPreview);
      setFailure(null);
    }
    const ready = attachments.filter((a) => a.id && a.status !== "failed");
    const optimistic = { id: `local-${Date.now()}`, role: "user", content, document_ids: ready.map((a) => a.id), created_at: new Date().toISOString() };
    setAttachments((list) => list.filter((a) => !ready.includes(a))); // they travel with the message now
    setDraft("");
    await exchange({ content, documentIds: optimistic.document_ids, optimistic, files: ready });
  };

  // Try again: the same message and files, once at a time. After a broken
  // connection it first checks whether the answer was saved after all.
  const retry = async () => {
    const f = failure;
    if (!f?.retry || sending || running.current) return;
    running.current = true;
    setFailure(null);
    await exchange({ ...f, check: f.uncertain });
  };

  // Dismiss: the failed message leaves the conversation and goes back to the composer.
  const dismissFailure = () => {
    const f = failure;
    if (!f) return;
    setFailure(null);
    setMessages((list) => list.filter((m) => m.id !== f.optimistic.id && m.id !== PARTIAL_ID));
    setDraft(f.content);
    setAttachments((list) => [...f.files.filter((a) => !list.includes(a)), ...list]);
  };

  // Stable callbacks, so finished messages are not re-rendered on every streamed chunk.
  const updateMessage = useCallback(
    (message) => setMessages((list) => list.map((m) => (m.id === message.id ? message : m))),
    []
  );
  const sendRef = useRef(null);
  useEffect(() => {
    sendRef.current = send;
  });
  const ask = useCallback((text) => sendRef.current?.(text), []);

  const assistant = {
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
    stop: () => abort.current?.abort(),
    newConversation: () => {
      // The current conversation stays saved on the server; this starts a fresh view.
      setConversationId(null);
      setMessages([]);
      setError("");
      setFailure(null);
    },
    openConversation: async (id) => {
      try {
        const res = await getConversation(id);
        setConversationId(res.data.id);
        setMessages(res.data.messages);
        setError("");
        setFailure(null);
      } catch (err) {
        setError(getErrorMessage(err, "Could not open the conversation"));
      }
    },
    updateMessage,
    ask,
    usage,
  };

  return (
    <>
      {/* Stays mounted (hidden while open) so its position and focus survive. */}
      <AssistantLauncher open={open} onOpen={() => setOpen(true)} onIntent={preloadPanel} buttonRef={launcherRef} />
      {open && (
        // A panel that cannot load or render never takes the page down with it.
        <ErrorBoundary title="The assistant could not be opened">
          <Suspense fallback={null}>
            <AssistantPanel assistant={assistant} onClose={close} />
          </Suspense>
        </ErrorBoundary>
      )}
    </>
  );
}
