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

  it("a failed request keeps the message and explains", async () => {
    streamAssistantMessage.mockRejectedValue({ response: { status: 503, data: { error: { code: "AI_RATE_LIMITED", message: "The AI service is busy (rate limit). Please try again shortly." } } } });
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "hello{Enter}");
    expect(await within(panel).findByRole("alert")).toHaveTextContent("busy (rate limit)");
    expect(within(panel).getByLabelText("Message")).toHaveValue("hello");
    expect(within(panel).getByRole("heading", { name: /How can I help/ })).toBeInTheDocument(); // nothing half-shown
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

  it("a proposed booking needs Confirm and shows the real result", async () => {
    const proposal = message("m-2", "assistant", "Please confirm.", {
      action: { type: "book_appointment", status: "pending", doctor_name: "Dr. Sarah Khan", department: "Cardiology", local_time: "Fri 23 Apr 2027, 10:00 AM" },
    });
    replyWith(proposal);
    decideAction.mockResolvedValue({ data: { ...proposal, action: { ...proposal.action, status: "booked" } } });
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "Book{Enter}");
    const card = await within(panel).findByRole("group", { name: "Book this appointment?" });
    expect(card).toHaveTextContent("Dr. Sarah Khan");
    await user.click(within(card).getByRole("button", { name: "Confirm" }));
    expect(decideAction).toHaveBeenCalledWith("c-1", "m-2", true);
    expect(await within(card).findByText(/Booked/)).toBeInTheDocument();
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
    const card = await within(panel).findByRole("group", { name: "Book this appointment?" });
    expect(card).toHaveTextContent("Test Patient (MRN00000002)");
    expect(card).toHaveTextContent(/Confirm by/);
    await user.click(within(card).getByRole("button", { name: "Confirm" }));
    expect(await within(card).findByText(/expired before it was confirmed/)).toBeInTheDocument();
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
    expect(report).toHaveTextContent("Date on report: 01/09/2026 · Test Diagnostics");
    expect(within(report).getByRole("row", { name: /Platelets/ })).toHaveTextContent("455 x10^3/uL Above range");
    expect(within(report).getByRole("row", { name: /Vitamin D/ })).toHaveTextContent("Not printed");
    expect(report).toHaveTextContent("Platelets (above range)");
    expect(report).toHaveTextContent("OCR) is not installed");
    expect(report).toHaveTextContent("This is not a diagnosis");
    expect(report).toHaveTextContent("Source: Blood count September, page 1");

    replyWith(message("m-4", "assistant", "Shown below."));
    await user.click(within(docs).getByRole("button", { name: /Summarize/ }));
    expect(streamAssistantMessage.mock.calls.at(-1)[0].text).toBe("Explain the medical document with id doc-9.");
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

  it("a proposed cancellation is labelled as one", async () => {
    replyWith(message("m-2", "assistant", "Confirm?", { action: { type: "cancel_appointment", status: "pending", doctor_name: "Dr. A", local_time: "Fri" } }));
    const user = userEvent.setup();
    render(<ClinicAssistant />);
    const panel = await openPanel();
    await waitFor(() => expect(within(panel).getByText("Find a Doctor").closest("button")).toBeEnabled());
    await user.type(within(panel).getByLabelText("Message"), "Cancel it{Enter}");
    expect(await within(panel).findByRole("group", { name: "Cancel this appointment?" })).toBeInTheDocument();
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
