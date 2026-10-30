import { useCallback, useEffect, useRef, useState } from "react";
import { getErrorMessage } from "../../services/api";
import {
  deleteAssistantDocument,
  getAssistantStatus,
  getAssistantUsage,
  getConversation,
  streamAssistantMessage,
  uploadAssistantDocuments,
} from "../../services/aiService";
import { checkFiles } from "../../utils/assistant";
import AssistantLauncher from "./AssistantLauncher";
import AssistantPanel from "./AssistantPanel";

let attachmentSeq = 0;
const STREAM_ID = "streaming-reply";

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
  const [usage, setUsage] = useState(null);
  const abort = useRef(null);
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

  const send = async (text = draft) => {
    const content = text.trim();
    if (!content || sending) return;
    const ready = attachments.filter((a) => a.id && a.status !== "failed");
    const now = new Date().toISOString();
    const optimistic = { id: `local-${Date.now()}`, role: "user", content, document_ids: ready.map((a) => a.id), created_at: now, pending: true };
    const streaming = { id: STREAM_ID, role: "assistant", content: "", created_at: now, streaming: true };
    setMessages((list) => [...list, optimistic, streaming]);
    setSending(true);
    setError("");
    setDraft("");
    const controller = new AbortController();
    abort.current = controller;
    try {
      const result = await streamAssistantMessage(
        { conversation_id: conversationId, text: content, document_ids: ready.map((a) => a.id) },
        {
          signal: controller.signal,
          onDelta: (chunk) => setMessages((list) => list.map((m) => (m.id === STREAM_ID ? { ...m, content: m.content + chunk } : m))),
        }
      );
      setConversationId(result.conversation.id);
      setMessages((list) => [...list.filter((m) => m.id !== optimistic.id && m.id !== STREAM_ID), result.user_message, result.assistant_message]);
      ready.forEach(dropPreview);
      setAttachments((list) => list.filter((a) => !ready.includes(a)));
    } catch (err) {
      // Nothing was saved: keep what the user wrote and attached.
      setMessages((list) => list.filter((m) => m.id !== optimistic.id && m.id !== STREAM_ID));
      setDraft(content);
      if (err?.name !== "AbortError") setError(getErrorMessage(err, "The assistant could not answer. Please try again."));
    } finally {
      abort.current = null;
      setSending(false);
      refreshUsage();
    }
  };

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
    stop: () => abort.current?.abort(),
    newConversation: () => {
      // The current conversation stays saved on the server; this starts a fresh view.
      setConversationId(null);
      setMessages([]);
      setError("");
    },
    openConversation: async (id) => {
      try {
        const res = await getConversation(id);
        setConversationId(res.data.id);
        setMessages(res.data.messages);
        setError("");
      } catch (err) {
        setError(getErrorMessage(err, "Could not open the conversation"));
      }
    },
    updateMessage: (message) => setMessages((list) => list.map((m) => (m.id === message.id ? message : m))),
    usage,
  };

  return (
    <>
      {/* Stays mounted (hidden while open) so its position and focus survive. */}
      <AssistantLauncher open={open} onOpen={() => setOpen(true)} buttonRef={launcherRef} />
      {open && <AssistantPanel assistant={assistant} onClose={close} />}
    </>
  );
}
