import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  decideAction,
  deleteAssistantDocument,
  getAssistantStatus,
  getAssistantUsage,
  getConversation,
  listConversations,
  streamAssistantMessage,
  uploadAssistantDocuments,
} from "../../services/aiService";
import { LAUNCHER_STORAGE_KEY } from "../../utils/assistant";
import ClinicAssistant from "./ClinicAssistant";
import SafeMarkdown from "./SafeMarkdown";

vi.mock("../../services/aiService");

// jsdom has no PointerEvent: a MouseEvent with pointer fields is enough here.
beforeAll(() => {
  if (!window.PointerEvent) {
    class PointerEvent extends MouseEvent {
      constructor(type, init = {}) {
        super(type, init);
        this.pointerId = init.pointerId ?? 1;
        this.pointerType = init.pointerType ?? "mouse";
      }
    }
    window.PointerEvent = PointerEvent;
  }
});

const CONFIGURED = {
  configured: true,
  provider: "gemini",
  documents_enabled: true,
  max_files: 5,
  max_file_bytes: 10 * 1024 * 1024,
  accepted_types: ["docx", "jpg", "pdf", "png", "txt", "webp"],
  capabilities: ["find_doctors", "clinic_help", "dashboard_figures", "book_appointment", "documents"],
  roles: ["patient"],
};
const USAGE = { requests_today: 2, daily_limit: 20, remaining_today: 18, per_minute_limit: 5, input_tokens_today: 900, output_tokens_today: 120 };
const message = (id, role, content, extra = {}) => ({ id, role, content, document_ids: [], action: null, created_at: "2027-04-23T05:00:00Z", ...extra });
const launcher = () => screen.getByTestId("ai-launcher");

function press(element, { x = 0, y = 0, type = "mouse" } = {}) {
  fireEvent.pointerDown(element, { clientX: x, clientY: y, pointerId: 1, pointerType: type, button: 0 });
}
function move(element, x, y, type = "mouse") {
  fireEvent.pointerMove(element, { clientX: x, clientY: y, pointerId: 1, pointerType: type });
}
function release(element, x, y, type = "mouse") {
  fireEvent.pointerUp(element, { clientX: x, clientY: y, pointerId: 1, pointerType: type });
}
async function openPanel() {
  press(launcher(), { x: 10, y: 10 });
  release(launcher(), 10, 10);
  return screen.findByRole("dialog", { name: "Clinic AI Assistant" });
}

beforeEach(() => {
  vi.resetAllMocks();
  window.localStorage.clear();
  window.innerWidth = 1280;
  window.innerHeight = 800;
  getAssistantStatus.mockResolvedValue({ data: CONFIGURED });
  getAssistantUsage.mockResolvedValue({ data: USAGE });
  deleteAssistantDocument.mockResolvedValue({});
});
afterEach(() => window.localStorage.clear());

describe("Floating launcher", () => {
  it("shows the official avatar at the bottom-right by default", () => {
    render(<ClinicAssistant />);
    const button = launcher();
    expect(button).toHaveAccessibleName("Open Clinic AI Assistant (drag to move)");
    expect(button.querySelector("img").getAttribute("src")).toMatch(/clinic-ai-avatar\.png/);
    expect(button.style.left).toBe(`${1280 - 72 - 24}px`);
    expect(button.style.top).toBe(`${800 - 72 - 24}px`);
  });

  it("a click opens the assistant and the close button closes it", async () => {
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    expect(within(panel).getByRole("heading", { name: "Clinic AI Assistant" })).toBeInTheDocument();
    expect(within(panel).getByText("Your AI Health & Clinic Assistant")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Close assistant" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(launcher()).toBeVisible();
  });

  it("dragging moves it, does not open the panel, and the spot is remembered", () => {
    const { unmount } = render(<ClinicAssistant />);
    press(launcher(), { x: 500, y: 500 });
    move(launcher(), 400, 300);
    release(launcher(), 400, 300);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const moved = { x: 1280 - 72 - 24 - 100, y: 800 - 72 - 24 - 200 };
    expect(launcher().style.left).toBe(`${moved.x}px`);
    expect(launcher().style.top).toBe(`${moved.y}px`);
    expect(JSON.parse(window.localStorage.getItem(LAUNCHER_STORAGE_KEY))).toEqual(moved);
    unmount();
    render(<ClinicAssistant />); // a reload
    expect(launcher().style.left).toBe(`${moved.x}px`);
  });

  it("a tiny movement still counts as a click", async () => {
    render(<ClinicAssistant />);
    press(launcher(), { x: 100, y: 100 });
    move(launcher(), 103, 102);
    release(launcher(), 103, 102);
    expect(await screen.findByRole("dialog", { name: "Clinic AI Assistant" })).toBeInTheDocument();
  });

  it("touch dragging works the same way and it never leaves the screen", () => {
    render(<ClinicAssistant />);
    press(launcher(), { x: 0, y: 0, type: "touch" });
    move(launcher(), 5000, 5000, "touch");
    release(launcher(), 5000, 5000, "touch");
    expect(parseFloat(launcher().style.left)).toBeLessThanOrEqual(1280 - 72);
    expect(parseFloat(launcher().style.top)).toBeLessThanOrEqual(800 - 72);
    // A smaller window pulls a saved far-away position back on screen.
    window.localStorage.setItem(LAUNCHER_STORAGE_KEY, JSON.stringify({ x: 3000, y: 3000 }));
    act(() => {
      window.innerWidth = 400;
      window.innerHeight = 700;
      window.dispatchEvent(new Event("resize"));
    });
    expect(parseFloat(launcher().style.left)).toBeLessThanOrEqual(400 - 60);
  });

  it("released near an edge it settles against it", () => {
    render(<ClinicAssistant />);
    const start = 1280 - 72 - 24;
    press(launcher(), { x: start, y: 400 });
    move(launcher(), 30, 400);
    release(launcher(), 30, 400);
    expect(launcher().style.left).toBe("24px");
  });
});

// streamAssistantMessage(data, { onDelta, signal }) -> result; the test streams the text in pieces.
function replyWith(assistantMessage, userMessage = message("m-1", "user", "x"), conversation = "c-1") {
  streamAssistantMessage.mockImplementation(async (data, { onDelta }) => {
    for (const piece of assistantMessage.content.match(/.{1,6}/gs) ?? []) onDelta(piece);
    return {
      conversation: { id: conversation, title: "x", created_at: "", updated_at: "" },
      user_message: { ...userMessage, content: data.text, document_ids: data.document_ids },
      assistant_message: assistantMessage,
    };
  });
}

describe("Assistant panel: screenshot design", () => {
  it("header: avatar, name, subtitle, new / history / close controls", async () => {
    render(<ClinicAssistant />);
    const panel = await openPanel();
    expect(within(panel).getByRole("heading", { name: "Clinic AI Assistant" })).toBeInTheDocument();
    expect(within(panel).getByText("Your AI Health & Clinic Assistant")).toBeInTheDocument();
    for (const name of ["New conversation", "Conversation history", "Close assistant"]) expect(within(panel).getByRole("button", { name })).toBeInTheDocument();
    expect(panel.querySelector(".ai-panel-avatar").getAttribute("src")).toMatch(/clinic-ai-avatar\.png/);
  });

  it("welcome: illustration, two-tone heading, exact text and the four cards", async () => {
    render(<ClinicAssistant />);
    const panel = await openPanel();
    expect(within(panel).getByRole("heading", { name: "Hello! How can I help you today?" })).toBeInTheDocument();
    expect(within(panel).getByText("Hello!")).toHaveClass("ai-hello");
    expect(within(panel).getByText("I can help you find doctors, manage appointments, answer health questions, and guide you through clinic services.")).toBeInTheDocument();
    expect(panel.querySelector(".ai-hero img").getAttribute("src")).toMatch(/clinic-ai-avatar\.png/);
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    const titles = () => [...panel.querySelectorAll(".ai-quick")].map((c) => c.querySelector("strong").textContent);
    // A patient without the (privacy-gated) appointment tools: only what works, topped up with Clinic Services.
    expect(titles()).toEqual(["Find a Doctor", "Book Appointment", "Clinic Services", "How Can I Reschedule?"]);
    expect(within(panel).getByText("Search by specialty, department or name.")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Message")).toHaveAttribute("placeholder", "Ask me anything...");
    expect(within(panel).getByText("Not a substitute for medical advice. In an emergency, contact emergency services.")).toBeInTheDocument();
  });

  it.each([
    ["patient", ["find_doctors", "clinic_help", "dashboard_figures", "book_appointment", "my_appointments", "medical_documents"], ["Find a Doctor", "Book Appointment", "My Medical Reports", "My Appointments"]],
    ["doctor", ["find_doctors", "clinic_help", "dashboard_figures", "appointments_overview"], ["Today's Appointments", "Show My Schedule", "Appointment Statistics", "Find a Doctor"]],
    ["receptionist", ["find_doctors", "clinic_help", "dashboard_figures", "appointments_overview", "find_patient"], ["Find a Patient", "Check Doctor Availability", "Today's Appointments", "Find a Doctor"]],
    ["receptionist", ["find_doctors", "clinic_help", "dashboard_figures", "appointments_overview"], ["Check Doctor Availability", "Today's Appointments", "Find a Doctor", "Clinic Services"]],
    ["admin", ["find_doctors", "clinic_help", "dashboard_figures", "appointments_overview"], ["Appointment Statistics", "Manage Departments", "Today's Appointments", "Find a Doctor"]],
  ])("suggestions fit the %s and only offer what works", async (role, capabilities, expected) => {
    getAssistantStatus.mockResolvedValue({ data: { ...CONFIGURED, roles: [role], capabilities } });
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(panel.querySelector(".ai-quick")).toBeEnabled());
    const cards = [...panel.querySelectorAll(".ai-quick")];
    expect(cards.map((c) => c.querySelector("strong").textContent)).toEqual(expected);
    for (const card of cards) expect(card).toBeEnabled();
  });

  it("not configured: every card and Send are off, with an explanation", async () => {
    getAssistantStatus.mockResolvedValue({ data: { ...CONFIGURED, configured: false, documents_enabled: false, capabilities: [] } });
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    expect(await within(panel).findByText(/not set up on this server yet/)).toBeInTheDocument();
    for (const card of panel.querySelectorAll(".ai-quick")) expect(card).toBeDisabled();
    await user.type(within(panel).getByLabelText("Message"), "hello");
    expect(within(panel).getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it("a card starts the real request and the reply streams in", async () => {
    replyWith(message("m-2", "assistant", "**Dr. Sarah Khan**, Cardiologist, 10 years."));
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.click(within(panel).getByText("Find a Doctor").closest("button"));
    expect(streamAssistantMessage).toHaveBeenCalledWith(
      { conversation_id: null, text: "Help me find a doctor by name, specialty, department, or professional experience.", document_ids: [] },
      expect.objectContaining({ onDelta: expect.any(Function) })
    );
    expect(await within(panel).findByText("Dr. Sarah Khan")).toHaveProperty("tagName", "STRONG");
    expect(within(panel).queryByRole("heading", { name: /How can I help/ })).not.toBeInTheDocument();
  });

  it("Clinic Services asks about departments and services", async () => {
    replyWith(message("m-2", "assistant", "Cardiology and Neurology."));
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Clinic Services").closest("button")).toBeEnabled());
    await user.click(within(panel).getByText("Clinic Services").closest("button"));
    expect(streamAssistantMessage.mock.calls[0][0].text).toBe("What departments and services does the clinic offer?");
  });

  it("Enter sends, Shift+Enter adds a line, and partial text shows while streaming", async () => {
    let finish;
    streamAssistantMessage.mockImplementation(
      (data, { onDelta }) =>
        new Promise((resolve) => {
          onDelta("Looking ");
          finish = () =>
            resolve({
              conversation: { id: "c-1", title: "x", created_at: "", updated_at: "" },
              user_message: message("m-1", "user", data.text),
              assistant_message: message("m-2", "assistant", "Looking now."),
            });
        })
    );
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    const box = within(panel).getByLabelText("Message");
    await user.type(box, "Find a{Shift>}{Enter}{/Shift}cardiologist");
    expect(box).toHaveValue("Find a\ncardiologist");
    await user.type(box, "{Enter}");
    expect(await within(panel).findByText("Looking")).toBeInTheDocument(); // partial answer
    expect(within(panel).getByRole("button", { name: "Stop" })).toBeInTheDocument();
    await act(async () => finish());
    expect(await within(panel).findByText("Looking now.")).toBeInTheDocument();
    expect(box).toHaveValue("");
  });

  it("shows an activity word instead of dots until the answer starts; Stop and errors remove it", async () => {
    let push, fail;
    streamAssistantMessage.mockImplementation(
      (data, { onDelta, signal }) =>
        new Promise((resolve, reject) => {
          push = onDelta;
          fail = reject;
          signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
        })
    );
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    const thinking = () => within(panel).queryByRole("status", { name: "Assistant is preparing a response" });

    // The answer starts: the word goes, the text shows.
    await user.type(within(panel).getByLabelText("Message"), "hello{Enter}");
    expect(await within(panel).findByRole("status", { name: "Assistant is preparing a response" })).toHaveTextContent("Thinking…");
    expect(panel.querySelector(".ai-typing")).toBeNull();
    await act(async () => push("Here is "));
    expect(thinking()).not.toBeInTheDocument();
    expect(within(panel).getByText("Here is")).toBeInTheDocument();

    // An error ends it too; what had arrived stays, marked as interrupted.
    await act(async () => fail({ response: { status: 503, data: { error: { message: "Traceback: internal detail" } } } }));
    const card = await within(panel).findByRole("alert");
    expect(card).toHaveTextContent("Couldn't complete that response");
    expect(card).toHaveTextContent("The assistant is temporarily unavailable. Please try again shortly.");
    expect(card).not.toHaveTextContent("Traceback"); // never server internals
    expect(thinking()).not.toBeInTheDocument();
    expect(within(panel).getByText("Here is")).toBeInTheDocument();
    expect(within(panel).getByText("Response interrupted")).toBeInTheDocument();

    // D132: an unexpected server error says nothing was booked, with a reference that matches the server's logs.
    await user.type(within(panel).getByLabelText("Message"), "Book me with a cardiologist{Enter}");
    await act(async () =>
      fail({ response: { status: 503, data: { error: { code: "AI_FAILED", message: "x", request_id: "77991382e359487fa400bbd4089f1ff3" } } } })
    );
    await waitFor(() => expect(within(panel).getByRole("alert")).toHaveTextContent("Nothing was booked or changed."));
    expect(within(panel).getByRole("alert")).toHaveTextContent("Reference: 77991382");
    expect(within(panel).getByText("Not sent")).toBeInTheDocument();

    // A new question replaces the failed one; Stop before any text: the word goes at once.
    await user.type(within(panel).getByLabelText("Message"), "again{Enter}");
    expect(await within(panel).findByRole("status", { name: "Assistant is preparing a response" })).toBeInTheDocument();
    expect(within(panel).queryByText("hello")).not.toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(thinking()).not.toBeInTheDocument());
    expect(within(panel).getByLabelText("Message")).toHaveValue("again"); // stopped: back in the composer
  });

  async function sendHello() {
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "hello{Enter}");
    return { user, panel };
  }
  const saved = (text) => ({
    conversation: { id: "c-1", title: "hello", created_at: "", updated_at: "" },
    user_message: message("m-1", "user", text),
    assistant_message: message("m-2", "assistant", "Here you go."),
  });

  it("a failed request keeps the message in the conversation; Try again sends it once more, without a duplicate", async () => {
    streamAssistantMessage
      .mockRejectedValueOnce({ response: { status: 429, data: { error: { code: "AI_RATE_LIMITED", message: "provider says 429" } } } })
      .mockImplementation(async (data) => saved(data.text));
    const { user, panel } = await sendHello();
    const card = await within(panel).findByRole("alert");
    expect(card).toHaveTextContent("The assistant is receiving too many requests right now. Please try again in a moment.");
    expect(within(panel).getByText("hello")).toBeInTheDocument();
    expect(within(panel).getByText("Not sent")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Message")).toHaveValue(""); // not duplicated into the composer

    await user.click(within(card).getByRole("button", { name: "Try again" }));
    expect(await within(panel).findByText("Here you go.")).toBeInTheDocument();
    expect(within(panel).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(panel).getAllByText("hello")).toHaveLength(1);
    expect(streamAssistantMessage).toHaveBeenCalledTimes(2);
    expect(streamAssistantMessage.mock.calls[1][0]).toEqual(streamAssistantMessage.mock.calls[0][0]); // same message and files
  });

  it("after a broken connection, Try again first looks for an answer the server already saved", async () => {
    streamAssistantMessage.mockRejectedValue(new TypeError("Failed to fetch"));
    const { user, panel } = await sendHello();
    const card = await within(panel).findByRole("alert");
    expect(card).toHaveTextContent("Connection interrupted. Check your internet connection and try again.");
    const now = new Date().toISOString();
    listConversations.mockResolvedValue({ data: [{ id: "c-9", title: "hello", created_at: now, updated_at: now }] });
    getConversation.mockResolvedValue({
      data: { id: "c-9", title: "hello", messages: [message("m-1", "user", "hello", { created_at: now }), message("m-2", "assistant", "Saved answer.", { created_at: now })] },
    });
    await user.click(within(card).getByRole("button", { name: "Try again" }));
    expect(await within(panel).findByText("Saved answer.")).toBeInTheDocument();
    expect(streamAssistantMessage).toHaveBeenCalledTimes(1); // not asked a second time
    expect(within(panel).getAllByText("hello")).toHaveLength(1);
  });

  it("a refusal offers no pointless Try again; Dismiss puts the message back in the composer", async () => {
    streamAssistantMessage.mockRejectedValue({ response: { status: 400, data: { error: { code: "AI_PHI_NOT_ALLOWED", message: "Document analysis is switched off." } } } });
    const { user, panel } = await sendHello();
    const card = await within(panel).findByRole("alert");
    expect(card).toHaveTextContent("Document analysis is switched off.");
    expect(within(card).queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Dismiss" }));
    expect(within(panel).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(panel).getByLabelText("Message")).toHaveValue("hello");
    expect(within(panel).getByRole("heading", { name: /How can I help/ })).toBeInTheDocument();
  });

  it("a booking whose confirmation got no answer is checked, never confirmed twice", async () => {
    const proposal = message("m-2", "assistant", "Confirm your appointment?", {
      action: { type: "book_appointment", status: "pending", doctor_name: "Dr. Sarah Khan", local_time: "Fri 23 Apr 2027, 10:00 AM", when_text: "Friday, April 23 at 10:00 AM PKT" },
    });
    replyWith(proposal);
    decideAction.mockRejectedValue(new TypeError("Failed to fetch"));
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "Book{Enter}");
    const card = await within(panel).findByRole("group", { name: "Confirm booking" });
    await user.click(within(card).getByRole("button", { name: "Confirm" }));
    expect(await within(card).findByText("We couldn't confirm whether this went through.")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    getConversation.mockResolvedValue({ data: { id: "c-1", title: "Book", messages: [{ ...proposal, action: { ...proposal.action, status: "booked" } }] } });
    await user.click(within(card).getByRole("button", { name: "Check status" }));
    expect(await within(card).findByText("Appointment booked with Dr. Sarah Khan for Friday, April 23 at 10:00 AM PKT.")).toBeInTheDocument();
    expect(decideAction).toHaveBeenCalledTimes(1);
  });

  it("files: validates, previews images, uploads each, retries a failure, and sends with the message", async () => {
    URL.createObjectURL = vi.fn(() => "blob:preview");
    URL.revokeObjectURL = vi.fn();
    uploadAssistantDocuments
      .mockResolvedValueOnce({ data: [{ id: "d-1", filename: "lab.pdf", status: "ready" }] })
      .mockRejectedValueOnce({ response: { data: { error: { message: "Storage did not answer" } } } })
      .mockResolvedValueOnce({ data: [{ id: "d-2", filename: "scan.png", status: "no_text" }] });
    replyWith(message("m-2", "assistant", "Summary (lab.pdf, page 1)."));
    const user = userEvent.setup({ applyAccept: false });
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByRole("button", { name: "Attach files" })).toBeEnabled());
    await user.upload(screen.getByTestId("ai-file-input"), [
      new File(["%PDF-1.4 x"], "lab.pdf", { type: "application/pdf" }),
      new File(["png"], "scan.png", { type: "image/png" }),
      new File(["MZ"], "virus.exe"),
    ]);
    expect(within(panel).getByRole("alert")).toHaveTextContent("virus.exe: not a supported file type.");
    const files = within(panel).getByRole("list", { name: "Files to send" });
    expect(files.querySelector(".ai-attachment-thumb").getAttribute("src")).toBe("blob:preview");
    expect(await within(files).findByText(/Storage did not answer/)).toBeInTheDocument();
    await user.click(within(files).getByRole("button", { name: "Retry scan.png" }));
    await waitFor(() => expect(within(files).queryByText(/Storage did not answer/)).not.toBeInTheDocument());
    expect(uploadAssistantDocuments).toHaveBeenCalledTimes(3);
    await user.type(within(panel).getByLabelText("Message"), "Summarize{Enter}");
    expect(streamAssistantMessage.mock.calls[0][0]).toEqual({ conversation_id: null, text: "Summarize", document_ids: ["d-1", "d-2"] });
    expect(await within(panel).findByText("lab.pdf")).toBeInTheDocument();
  });

  it("removing a file deletes its upload", async () => {
    uploadAssistantDocuments.mockResolvedValue({ data: [{ id: "d-9", filename: "a.txt", status: "ready" }] });
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByRole("button", { name: "Attach files" })).toBeEnabled());
    await user.upload(screen.getByTestId("ai-file-input"), new File(["hello"], "a.txt", { type: "text/plain" }));
    await within(panel).findByText(/Ready/);
    await user.click(within(panel).getByRole("button", { name: "Remove a.txt" }));
    expect(within(panel).queryByRole("list", { name: "Files to send" })).not.toBeInTheDocument();
    expect(deleteAssistantDocument).toHaveBeenCalledWith("d-9");
  });

  it("attachments are off when the server has not enabled documents", async () => {
    getAssistantStatus.mockResolvedValue({ data: { ...CONFIGURED, documents_enabled: false, capabilities: ["find_doctors"] } });
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    expect(within(panel).getByRole("button", { name: "Attach files" })).toBeDisabled();
  });

  it("a proposed booking is one question with Confirm / Cancel, then a one-line result", async () => {
    const proposal = message("m-2", "assistant", "Confirm your appointment with Dr. Sarah Khan on Friday, April 23 at 10:00 AM PKT?", {
      action: {
        type: "book_appointment", status: "pending", doctor_name: "Dr. Sarah Khan", department: "Cardiology",
        local_time: "Fri 23 Apr 2027, 10:00 AM", when_text: "Friday, April 23 at 10:00 AM PKT",
      },
    });
    replyWith(proposal);
    decideAction.mockResolvedValue({ data: { ...proposal, action: { ...proposal.action, status: "booked" } } });
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "Book{Enter}");
    expect(await within(panel).findByText("Confirm your appointment with Dr. Sarah Khan on Friday, April 23 at 10:00 AM PKT?")).toBeInTheDocument();
    const card = within(panel).getByRole("group", { name: "Confirm booking" });
    expect(within(card).getByRole("button", { name: "Cancel" })).toBeEnabled();
    await user.click(within(card).getByRole("button", { name: "Confirm" }));
    expect(decideAction).toHaveBeenCalledTimes(1);
    expect(decideAction).toHaveBeenCalledWith("c-1", "m-2", true);
    expect(await within(card).findByText("Appointment booked with Dr. Sarah Khan for Friday, April 23 at 10:00 AM PKT.")).toBeInTheDocument();
  });

  it("a booking made for a patient shows who; an expired one says so", async () => {
    const proposal = message("m-2", "assistant", "Please confirm.", {
      action: {
        type: "book_appointment", status: "pending", doctor_name: "Dr. Sarah Khan", local_time: "Fri 23 Apr 2027, 10:00 AM",
        patient_name: "Test Patient", patient_mrn: "MRN00000002", expires_at: "2027-04-23T05:15:00Z",
      },
    });
    replyWith(proposal);
    decideAction.mockResolvedValue({ data: { ...proposal, action: { ...proposal.action, status: "expired" } } });
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "Book{Enter}");
    const card = await within(panel).findByRole("group", { name: "Confirm booking" });
    expect(card).toHaveTextContent("Test Patient (MRN00000002)");
    await user.click(within(card).getByRole("button", { name: "Confirm" }));
    expect(await within(card).findByText(/expired before it was confirmed/)).toBeInTheDocument();
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
  });

  it("doctor results are cards with profile and booking links, from the server's data", async () => {
    replyWith(
      message("m-2", "assistant", "I found one cardiologist.", {
        results: [{
          kind: "doctors", total: 3,
          items: [{ doctor_id: "doc-1", name: "Dr. Sarah Khan", specialization: "Cardiologist", department: "Cardiology", years_of_experience: 10, next_available: "2027-04-24T05:00:00Z" }],
        }],
      })
    );
    const user = userEvent.setup();
    render(<MemoryRouter><ClinicAssistant /></MemoryRouter>);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "cardiologist{Enter}");
    const list = await within(panel).findByRole("list", { name: "Doctors found" });
    expect(list).toHaveTextContent("Dr. Sarah Khan");
    expect(list).toHaveTextContent("Cardiologist · Cardiology");
    expect(list).toHaveTextContent("10 yrs experience");
    expect(list.querySelector('[data-avatar="doctor"]')).not.toBeNull(); // illustrated avatar, never a stock photo
    expect(within(list).getByRole("link", { name: /View profile/ })).toHaveAttribute("href", "/doctors/doc-1");
    expect(within(list).getByRole("link", { name: /Book/ })).toHaveAttribute("href", "/appointments/book?doctor=doc-1");
    expect(within(panel).getByText(/Showing 1 of 3/)).toBeInTheDocument();
  });

  it("appointment results show status and open the appointment; no Book link without booking rights", async () => {
    getAssistantStatus.mockResolvedValue({ data: { ...CONFIGURED, roles: ["doctor"], capabilities: ["find_doctors", "appointments_overview"] } });
    replyWith(
      message("m-2", "assistant", "One today.", {
        results: [{ kind: "appointments", total: 1, items: [{ appointment_id: "a-1", when: "Fri 23 Apr 2027, 10:00 AM", doctor: "Dr. A", department: "Cardiology", status: "confirmed", patient: "Test Patient", mrn: "MRN00000001" }] }],
      })
    );
    const user = userEvent.setup();
    render(<MemoryRouter><ClinicAssistant /></MemoryRouter>);
    const panel = await openPanel();
    await waitFor(() => expect(panel.querySelector(".ai-quick")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "today{Enter}");
    const list = await within(panel).findByRole("list", { name: "Appointments" });
    expect(list).toHaveTextContent("Test Patient (MRN00000001) · Dr. A · Cardiology");
    expect(list).toHaveTextContent("Confirmed");
    expect(within(list).getByRole("link", { name: /View appointment/ })).toHaveAttribute("href", "/appointments/a-1");
    expect(within(panel).queryByRole("link", { name: /^Book/ })).not.toBeInTheDocument();
  });

  it("medical documents and a read report come from the record, with sources and a Summarize action", async () => {
    replyWith(
      message("m-2", "assistant", "Your documents and the latest report are shown below.", {
        results: [
          {
            kind: "medical_documents", total: 1,
            items: [{ document_id: "doc-9", patient_id: "p-1", title: "Blood count September", type_label: "Lab report", report_date: "2026-09-01", uploaded: "2026-09-02", file_type: "PDF" }],
          },
          {
            kind: "medical_report", has_text: true, problem: null, shared_with_ai: false,
            notes: ["Page(s) 2 are scanned images. Text recognition (OCR) is not installed on this server, so they were not read."],
            document: { title: "Blood count September", type_label: "Lab report", printed_date: "01/09/2026", laboratory: "Test Diagnostics" },
            measurements: [
              { test: "Platelets", value: "455", unit: "x10^3/uL", reference_range: "150-400", report_flag: "H", out_of_range: "high", page: 1, about: "Platelets help blood clot." },
              { test: "Vitamin D", value: "18", unit: "ng/mL", reference_range: null, report_flag: null, out_of_range: null, page: 1, about: null },
            ],
            sources: [{ document_id: "doc-9", title: "Blood count September", pages: [1] }],
          },
        ],
      })
    );
    const user = userEvent.setup();
    render(<MemoryRouter><ClinicAssistant /></MemoryRouter>);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "my reports{Enter}");

    const docs = await within(panel).findByRole("list", { name: "Medical documents" });
    expect(docs).toHaveTextContent("Blood count September");
    expect(docs).toHaveTextContent("Lab report · Report date Sep 1, 2026 · Uploaded Sep 2, 2026 · PDF");
    expect(within(docs).getByRole("link", { name: /View document/ })).toHaveAttribute("href", "/profile");

    const report = within(panel).getByRole("region", { name: "Report: Blood count September" });
    expect(report).toHaveTextContent("Date on report: 01/09/2026");
    expect(report).toHaveTextContent("Test Diagnostics");
    // A summary leads with the abnormal findings and the table.
    expect(within(report).getByRole("heading", { name: "Abnormal findings" })).toBeInTheDocument();
    expect(report).toHaveTextContent("Platelets: 455 x10^3/uL — above range");
    const platelets = within(report).getByRole("row", { name: /Platelets/ });
    expect(platelets).toHaveTextContent("455 x10^3/uL");
    expect(platelets).toHaveTextContent("Above range (H)");
    expect(within(report).getByRole("row", { name: /Vitamin D/ })).toHaveTextContent("Not printed");
    expect(report).toHaveTextContent("OCR) is not installed");
    expect(report).toHaveTextContent("Not a diagnosis");
    expect(report).toHaveTextContent("Source: Blood count September, page 1");

    replyWith(message("m-4", "assistant", "Shown below."));
    await user.click(within(docs).getByRole("button", { name: /Summarize/ }));
    expect(streamAssistantMessage.mock.calls.at(-1)[0].text).toBe("Explain the medical document with id doc-9.");
  });

  it("a report card leads with what was asked: the condition, with the rest one click away", async () => {
    replyWith(
      message("m-2", "assistant", "The report states type 2 diabetes mellitus.", {
        results: [{
          kind: "medical_report", version: 2, focus: "conditions", has_text: true, problem: null, notes: [],
          document: { document_id: "d-1", title: "Diabetes clinical case", document_kind: "Laboratory report", printed_date: "30 Oct 2026", uploaded: "2026-10-30" },
          conditions: [{ name: "Type 2 diabetes mellitus", role: "primary", page: 1, source_text: "Findings are consistent with type 2 diabetes mellitus.", about: "A long-term condition." }],
          symptoms: [{ name: "Increased thirst", page: 1, source_text: "Increased thirst" }],
          measurements: [{ test: "HbA1c", value: "8.2", unit: "%", reference_range: "Normal <5.7%", report_flag: "HIGH", out_of_range: "high", page: 1, about: null }],
          sections: [],
          sources: [{ document_id: "d-1", title: "Diabetes clinical case", pages: [1] }],
        }],
      })
    );
    const user = userEvent.setup();
    render(<MemoryRouter><ClinicAssistant /></MemoryRouter>);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "which disease?{Enter}");
    const report = await within(panel).findByRole("region", { name: "Report: Diabetes clinical case" });
    expect(within(report).getAllByRole("heading", { level: 5 }).map((h) => h.textContent)).toEqual(["Condition"]);
    expect(report).toHaveTextContent("Type 2 diabetes mellitus · main condition stated in the report");
    expect(report).toHaveTextContent("“Findings are consistent with type 2 diabetes mellitus.” (page 1)");
    // The table and symptoms are there, collapsed.
    const more = [...report.querySelectorAll("details > summary")].map((s) => s.textContent);
    expect(more).toEqual(expect.arrayContaining(["Symptoms described", "Laboratory results", "Abnormal findings"]));
  });

  it("appointment history shows the patient's own visits with appointment and profile links, never a Book button", async () => {
    replyWith(
      message("m-2", "assistant", "You have 2 past appointments, with Dr. A, Dr. B:", {
        results: [{
          kind: "appointment_history", scope: "past", pick: "all", total: 2,
          items: [
            { appointment_id: "a-2", doctor_id: "doc-2", doctor: "Dr. B", specialization: "Neurologist", department: "Neurology", date: "Sun 25 Oct 2026", start: "10:00 AM", end: "10:30 AM", status: "cancelled" },
            { appointment_id: "a-1", doctor_id: "doc-1", doctor: "Dr. A", specialization: "Cardiologist", department: "Cardiology", date: "Sat 10 Oct 2026", start: "9:00 AM", end: "9:30 AM", status: "completed" },
          ],
        }],
      })
    );
    const user = userEvent.setup();
    render(<MemoryRouter><ClinicAssistant /></MemoryRouter>);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "doctors I saw before{Enter}");
    const list = await within(panel).findByRole("list", { name: "Your appointments" });
    const [first, second] = within(list).getAllByRole("listitem");
    expect(first).toHaveTextContent("Dr. B");
    expect(first).toHaveTextContent("Neurologist · Neurology");
    expect(first).toHaveTextContent("Sun 25 Oct 2026, 10:00 AM–10:30 AM");
    expect(first).toHaveTextContent("Cancelled");
    expect(second).toHaveTextContent("Completed");
    expect(within(first).getByRole("link", { name: /View appointment/ })).toHaveAttribute("href", "/appointments/a-2");
    expect(within(first).getByRole("link", { name: /Doctor profile/ })).toHaveAttribute("href", "/doctors/doc-2");
    expect(within(list).queryByRole("link", { name: /Book/ })).not.toBeInTheDocument();
  });

  it("shows how many messages are left today and refreshes it after sending", async () => {
    replyWith(message("m-2", "assistant", "Hi."));
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    expect(await within(panel).findByText("18 of 20 messages left today")).toBeInTheDocument();
    getAssistantUsage.mockResolvedValue({ data: { ...USAGE, requests_today: 20, remaining_today: 0 } });
    await user.type(within(panel).getByLabelText("Message"), "hi{Enter}");
    expect(await within(panel).findByText("Daily message limit reached. It resets tomorrow.")).toBeInTheDocument();
  });

  it("a proposed cancellation offers Confirm cancellation / Keep appointment; keeping it says so", async () => {
    const proposal = message("m-2", "assistant", "Cancel your appointment with Dr. A on Friday, November 6 at 3:00 PM PKT?", {
      action: { type: "cancel_appointment", status: "pending", doctor_name: "Dr. A", local_time: "Fri", when_text: "Friday, November 6 at 3:00 PM PKT" },
    });
    replyWith(proposal);
    decideAction.mockResolvedValue({ data: { ...proposal, action: { ...proposal.action, status: "cancelled" } } });
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "Cancel it{Enter}");
    const card = await within(panel).findByRole("group", { name: "Confirm cancellation" });
    expect(within(card).getByRole("button", { name: "Confirm cancellation" })).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Keep appointment" }));
    expect(decideAction).toHaveBeenCalledWith("c-1", "m-2", false);
    expect(await within(card).findByText("Kept your appointment.")).toBeInTheDocument();
  });

  it("a treatment answer shows the short medical note once, above the answer", async () => {
    replyWith(message("m-2", "assistant", "AI can make mistakes. Please consult a doctor for medical advice.\n\nIt is usually treated with iron."));
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "how is anemia treated{Enter}");
    const note = await within(panel).findByText("AI can make mistakes. Please consult a doctor for medical advice.");
    expect(note).toHaveClass("ai-medical-note");
    expect(within(panel).getByText("It is usually treated with iron.")).toBeInTheDocument();
    expect(within(panel).getAllByText(/AI can make mistakes/)).toHaveLength(1);
  });

  it("New conversation clears the view; History reopens a saved one", async () => {
    replyWith(message("m-2", "assistant", "Hi there."));
    listConversations.mockResolvedValue({ data: [{ id: "c-7", title: "Blood test", created_at: "2027-04-20T05:00:00Z", updated_at: "2027-04-20T05:00:00Z" }] });
    getConversation.mockResolvedValue({ data: { id: "c-7", title: "Blood test", messages: [message("m-1", "user", "What did it say?"), message("m-2", "assistant", "Normal range.")] } });
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "Hello{Enter}");
    await within(panel).findByText("Hi there.");
    await user.click(within(panel).getByRole("button", { name: "New conversation" }));
    expect(within(panel).getByRole("heading", { name: /How can I help/ })).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Conversation history" }));
    await user.click(await within(panel).findByRole("button", { name: /^Blood test/ }));
    expect(await within(panel).findByText("Normal range.")).toBeInTheDocument();
  });

  it("history says when there is nothing saved", async () => {
    listConversations.mockResolvedValue({ data: [] });
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await user.click(within(panel).getByRole("button", { name: "Conversation history" }));
    expect(await within(panel).findByText(/No saved conversations yet/)).toBeInTheDocument();
  });

  it("closing keeps the conversation; Escape closes too", async () => {
    replyWith(message("m-2", "assistant", "Still here."));
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    let panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "Hi{Enter}");
    await within(panel).findByText("Still here.");
    fireEvent.keyDown(panel, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    panel = await openPanel();
    expect(within(panel).getByText("Still here.")).toBeInTheDocument();
  });
});

describe("SafeMarkdown", () => {
  it("never renders HTML from the model", () => {
    const { container } = render(<SafeMarkdown text={'<img src=x onerror="alert(1)"> **bold**'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container).toHaveTextContent('<img src=x onerror="alert(1)">');
    expect(container.querySelector("strong")).toHaveTextContent("bold");
  });
});

describe("Conversational follow-ups (D115)", () => {
  const DOCTOR = {
    doctor_id: "d-3",
    name: "Dr. Layla Hassan",
    specialization: "Cardiology",
    department: "Heart Centre",
    years_of_experience: 18,
    consultation_fee: "2000",
    next_available: "2027-04-24T12:00:00Z",
    selected: true,
  };

  async function ask(text) {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ClinicAssistant />
      </MemoryRouter>
    );
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), `${text}{Enter}`);
    return { user, panel };
  }

  it("doctor cards: separate lines, named actions and relative links only", async () => {
    replyWith(message("m-2", "assistant", "Dr. Layla Hassan is the most experienced.", { results: [{ kind: "doctors", total: 1, items: [DOCTOR] }] }));
    const { panel } = await ask("book the most experienced one");
    const card = await within(panel).findByRole("list", { name: "Doctors found" });
    const item = within(card).getByRole("listitem");
    expect(within(item).getByText("Selected")).toBeInTheDocument();
    // Each fact is its own block, so the text never runs together.
    expect([...item.querySelectorAll(".ai-result-body > p")].map((p) => p.textContent.trim())).toEqual([
      "Dr. Layla HassanSelected",
      "Cardiology · Heart Centre",
      "18 yrs experience · Fee 2000",
      expect.stringMatching(/^Next available: /),
      "View profile Book appointment",
    ]);
    const profile = within(item).getByRole("link", { name: "View profile of Dr. Layla Hassan" });
    const book = within(item).getByRole("link", { name: "Book an appointment with Dr. Layla Hassan" });
    expect(profile).toHaveAttribute("href", "/doctors/d-3");
    expect(book).toHaveAttribute("href", "/appointments/book?doctor=d-3");
    for (const link of within(panel).getAllByRole("link")) expect(link.getAttribute("href")).not.toMatch(/localhost|^https?:/);
  });

  it("free times are chips that ask for that time", async () => {
    replyWith(
      message("m-2", "assistant", "Tomorrow evening is free.", {
        results: [{ kind: "slots", doctor_id: "d-3", doctor_name: "Dr. Layla Hassan", timezone: "Asia/Karachi", total: 2, items: [
          { starts_at: "2027-04-24T12:00:00Z", local_time: "Sat 24 Apr 2027, 05:00 PM" },
          { starts_at: "2027-04-24T12:30:00Z", local_time: "Sat 24 Apr 2027, 05:30 PM" },
        ] }],
      })
    );
    const { user, panel } = await ask("tomorrow evening");
    const slots = await within(panel).findByRole("region", { name: "Free times with Dr. Layla Hassan" });
    replyWith(message("m-4", "assistant", "Confirm your appointment?"));
    await user.click(within(slots).getByRole("button", { name: "Sat 24 Apr 2027, 05:30 PM" }));
    await waitFor(() => expect(streamAssistantMessage).toHaveBeenCalledTimes(2));
    expect(streamAssistantMessage.mock.calls[1][0].text).toBe("Book the Sat 24 Apr 2027, 05:30 PM slot");
  });

  it("a typed yes updates the earlier proposal instead of leaving its buttons", async () => {
    const pending = { type: "book_appointment", status: "pending", doctor_name: "Dr. Layla Hassan", local_time: "Sat 24 Apr 2027, 05:00 PM", when_text: "Saturday, April 24 at 5:00 PM PKT" };
    replyWith(message("m-2", "assistant", "Confirm your appointment with Dr. Layla Hassan?", { action: pending }));
    const { user, panel } = await ask("take the earliest one");
    expect(await within(panel).findByRole("group", { name: "Confirm booking" })).toBeInTheDocument();
    replyWith(
      message("m-4", "assistant", "Done: your appointment with Dr. Layla Hassan on Saturday, April 24 at 5:00 PM PKT is booked.", {
        results: [{ kind: "decision", message_id: "m-2", action: { ...pending, status: "booked", appointment_id: "a-1" } }],
      }),
      message("m-3", "user", "yes")
    );
    await user.type(within(panel).getByLabelText("Message"), "yes, confirm{Enter}");
    expect(await within(panel).findByText(/is booked\./)).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  });

  it("answers show no app URLs, even in older saved messages", () => {
    render(<SafeMarkdown text="Open [Dr Khan](http://localhost:5173/doctors/1) or http://localhost:5173/doctors now." />);
    expect(screen.getByText(/Open Dr Khan or now\./)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/localhost|http/);
  });

  it("a failed follow-up never shows the previous doctor cards again", async () => {
    replyWith(message("m-2", "assistant", "Three cardiologists.", { results: [{ kind: "doctors", total: 1, items: [{ ...DOCTOR, selected: false }] }] }));
    const { user, panel } = await ask("heart doctors");
    await within(panel).findByRole("list", { name: "Doctors found" });
    replyWith(message("m-4", "assistant", "I'm not sure what you'd like to do with those doctors.", { results: null }), message("m-3", "user", "hmm"));
    await user.type(within(panel).getByLabelText("Message"), "hmm{Enter}");
    await within(panel).findByText(/not sure what you'd like/);
    expect(within(panel).getAllByRole("list", { name: "Doctors found" })).toHaveLength(1); // only under the first answer
  });
});
