import api, { apiUrl, getAccessToken, refreshAccessToken } from "./api";

// Clinic AI Assistant (D96). Every call is the signed-in user's own data.
export const getAssistantStatus = () => api.get("/ai/status");
export const getAssistantUsage = () => api.get("/ai/usage/me");
export const listConversations = () => api.get("/ai/conversations");
export const getConversation = (id) => api.get(`/ai/conversations/${id}`);
export const deleteConversation = (id) => api.delete(`/ai/conversations/${id}`);
export const sendAssistantMessage = (data, signal) => api.post("/ai/messages", data, { signal });
export const decideAction = (conversationId, messageId, confirm) =>
  api.post(`/ai/conversations/${conversationId}/messages/${messageId}/decision`, { confirm });
export const deleteAssistantDocument = (id) => api.delete(`/ai/documents/${id}`);
export function uploadAssistantDocuments(files, conversationId, onProgress) {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  if (conversationId) form.append("conversation_id", conversationId);
  return api.post("/ai/documents", form, {
    onUploadProgress: onProgress ? (e) => e.total && onProgress(Math.round((e.loaded / e.total) * 100)) : undefined,
  });
}

const LIMIT_CODES = new Set(["AI_USER_RATE_LIMITED", "AI_USER_DAILY_LIMIT", "AI_SERVER_BUSY", "AI_SERVER_DAILY_LIMIT"]);

// Streams one message (Server-Sent Events over fetch, since EventSource cannot
// POST or send the Authorization header). `onDelta(text)` gets answer text as
// it arrives; resolves with the saved { conversation, user_message,
// assistant_message }. Failures reject with an axios-shaped error, so
// getErrorMessage() reads them like every other API error.
export async function streamAssistantMessage(data, { signal, onDelta } = {}) {
  const post = () =>
    fetch(apiUrl("/ai/messages/stream"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream", Authorization: `Bearer ${getAccessToken()}` },
      body: JSON.stringify(data),
      signal,
    });
  let response = await post();
  if (response.status === 401) {
    await refreshAccessToken(); // expired access token: refresh once, then retry
    response = await post();
  }
  if (!response.ok) {
    let body = null;
    try {
      body = await response.json();
    } catch {
      // not JSON
    }
    throw { response: { status: response.status, data: body } };
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const event = chunk.match(/^event: (.*)$/m)?.[1];
      const payload = chunk.match(/^data: (.*)$/m)?.[1];
      if (!event || payload == null) continue;
      const parsed = JSON.parse(payload);
      if (event === "delta") onDelta?.(parsed.text);
      else if (event === "done") return parsed;
      // Usage limits (D100) arrive as 429, like the non-streaming endpoint.
      else if (event === "error") throw { response: { status: LIMIT_CODES.has(parsed.code) ? 429 : 503, data: { error: parsed } } };
    }
  }
  throw { response: { status: 503, data: { error: { message: "The connection closed before the answer finished." } } } };
}
