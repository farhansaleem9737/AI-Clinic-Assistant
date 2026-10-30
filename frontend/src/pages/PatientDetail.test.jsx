import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { changeAppointmentStatus, countAppointments, listAppointments } from "../services/appointmentService";
import { listDocuments } from "../services/documentService";
import { getPatient, updatePatient } from "../services/patientService";
import { authAs, PERMISSIONS } from "../test/fixtures";
import PatientDetail from "./PatientDetail";

vi.mock("../context/useAuth");
vi.mock("../services/patientService");
vi.mock("../services/appointmentService");
vi.mock("../services/documentService", async (importOriginal) => ({ ...(await importOriginal()), listDocuments: vi.fn() }));

const RECEPTION = [...PERMISSIONS.receptionist, "patient:update"];
const JOHN = {
  id: "p-1",
  mrn: "MRN00000001",
  first_name: "John",
  last_name: "Doe",
  date_of_birth: "1994-04-15",
  sex_at_birth: "male",
  phone: "+1 555 123 4567",
  email: "john.doe@example.com",
  address: "123 Main St,\nNew York, NY 10001",
  preferred_language: "English",
  emergency_contact_name: "Sarah Doe",
  emergency_contact_relationship: "Spouse",
  emergency_contact_phone: "+1 555 987 6543",
  preferred_contact_method: "phone",
  has_account: true,
  is_active: true,
  photo_url: null,
  created_at: "2026-04-10T09:00:00Z",
  updated_at: "2026-04-10T09:00:00Z",
};
const doctor = { id: "d-1", name: "Sarah Khan", title: "Dr.", specialization: "Cardiologist", department_name: "Cardiology", photo_url: null };
const UPCOMING = {
  id: "a-1",
  status: "confirmed",
  starts_at: "2027-04-23T05:00:00Z",
  ends_at: "2027-04-23T05:30:00Z",
  timezone: "Asia/Karachi",
  reason: "Follow-up",
  doctor,
  allowed_transitions: ["checked_in", "cancelled"],
  can_reschedule: true,
};
const PAST = { ...UPCOMING, id: "a-2", status: "completed", starts_at: "2026-03-02T06:30:00Z", reason: "Routine checkup", allowed_transitions: [], can_reschedule: false };

function renderPage(entry = "/patients/p-1", permissions = RECEPTION) {
  useAuth.mockReturnValue(authAs("Ayesha Malik", ["receptionist"], permissions));
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/patients/:id" element={<PatientDetail />} />
        <Route path="/patients" element={<p>Patient list</p>} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  getPatient.mockResolvedValue({ data: JOHN });
  countAppointments.mockResolvedValue({ data: { upcoming: 1, past: 2, all: 3 } });
  listAppointments.mockImplementation((params) =>
    Promise.resolve({ data: { items: params.scope === "upcoming" ? [UPCOMING] : [PAST], total: 1, page: 1, page_size: 5 } })
  );
});

describe("Patient details", () => {
  it("shows the identity header from the record", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "John Doe" })).toBeInTheDocument();
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(breadcrumb).getByRole("link", { name: "Patients" })).toHaveAttribute("href", "/patients");
    expect(within(breadcrumb).getByText("John Doe")).toHaveAttribute("aria-current", "page");
    const header = screen.getByRole("banner");
    expect(header).toHaveTextContent("Active");
    expect(header).toHaveTextContent("MRN: MRN00000001");
    expect(header).toHaveTextContent(/\d+ years/);
    expect(header).toHaveTextContent("Male");
    expect(header).toHaveTextContent("Registered: Apr 10, 2026");
    expect(header.querySelector("img")).toBeNull(); // initials, no stock photo
  });

  it("fills the personal and contact cards, without clinical data", async () => {
    renderPage();
    const personal = await screen.findByRole("region", { name: "Personal Information" });
    expect(personal).toHaveTextContent("Apr 15, 1994");
    expect(personal).not.toHaveTextContent(/Blood/);
    const contact = screen.getByRole("region", { name: "Contact Information" });
    expect(contact).toHaveTextContent("+1 555 123 4567");
    expect(contact).toHaveTextContent("Sarah Doe (Spouse)");
    expect(contact).toHaveTextContent("+1 555 987 6543");
    expect(contact).toHaveTextContent("Phone call");
    expect(within(contact).getByText("New York, NY 10001")).toHaveClass("pd-line"); // the address keeps its lines
  });

  it("says Not provided for empty optional details", async () => {
    getPatient.mockResolvedValue({ data: { ...JOHN, email: null, emergency_contact_name: null, emergency_contact_relationship: null, preferred_contact_method: null } });
    renderPage();
    const contact = await screen.findByRole("region", { name: "Contact Information" });
    expect(within(contact).getAllByText("Not provided")).toHaveLength(3);
  });

  it("keeps Medical Information locked for reception and loads no clinical data", async () => {
    renderPage();
    await screen.findByRole("heading", { level: 1 });
    const locked = screen.getByText("Medical Information", { selector: ".pd-locked" });
    expect(locked).toHaveAttribute("aria-disabled", "true");
    expect(locked).toHaveAccessibleDescription("Medical information is restricted to authorized clinical staff.");
    expect(listDocuments).not.toHaveBeenCalled();
  });

  it("the section tabs move to their sections", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { level: 1 });
    const tabs = screen.getByRole("navigation", { name: "Patient record sections" });
    await user.click(within(tabs).getByRole("link", { name: "Contact Information" }));
    expect(within(tabs).getByRole("link", { name: "Contact Information" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("heading", { name: "Contact Information" })).toBeInTheDocument();
  });

  it("edits the details, validating before it saves", async () => {
    const user = userEvent.setup();
    updatePatient.mockResolvedValue({ data: { ...JOHN, phone: "+92 300 1234567", emergency_contact_name: "Ali Doe" } });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const dialog = screen.getByRole("dialog", { name: "Edit patient" });
    const phone = within(dialog).getByLabelText("Phone");
    expect(phone).toHaveValue("+1 555 123 4567");
    await user.clear(phone);
    await user.type(phone, "call me");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(within(dialog).getByText(/Use digits, spaces/)).toBeInTheDocument();
    expect(updatePatient).not.toHaveBeenCalled();

    await user.clear(phone);
    await user.type(phone, "+92 300 1234567");
    const contact = within(dialog).getByLabelText("Emergency contact");
    await user.clear(contact);
    await user.type(contact, "Ali Doe");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    expect(updatePatient).toHaveBeenCalledWith("p-1", expect.objectContaining({ phone: "+92 300 1234567", emergency_contact_name: "Ali Doe" }));
    const sent = updatePatient.mock.calls[0][1];
    expect(sent).not.toHaveProperty("mrn");
    expect(sent).not.toHaveProperty("created_at");
    expect(await screen.findByText("The patient's details were saved.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Contact Information" })).toHaveTextContent("Ali Doe (Spouse)");
  });

  it("opens the editor when the list's Edit asks for it", async () => {
    renderPage("/patients/p-1?edit=1");
    expect(await screen.findByRole("dialog", { name: "Edit patient" })).toBeInTheDocument();
  });

  it("Book Appointment carries this patient", async () => {
    renderPage();
    expect(await screen.findByRole("link", { name: /Book Appointment/ })).toHaveAttribute("href", "/appointments/book?patient=p-1");
  });

  it("an inactive patient shows it and cannot be booked", async () => {
    getPatient.mockResolvedValue({ data: { ...JOHN, is_active: false } });
    renderPage();
    expect(await screen.findByText("Inactive")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Book Appointment/ })).not.toBeInTheDocument();
  });

  it("lists upcoming and recent appointments with real counts", async () => {
    const user = userEvent.setup();
    renderPage();
    const card = await screen.findByRole("region", { name: "Appointments" });
    expect(await within(card).findByRole("tab", { name: "Upcoming Appointments (1)" })).toHaveAttribute("aria-selected", "true");
    const [, row] = within(card).getAllByRole("row");
    expect(row).toHaveTextContent("Apr23");
    expect(row).toHaveTextContent("Fri, Apr 23, 2027");
    expect(row).toHaveTextContent("10:00 AM");
    expect(row).toHaveTextContent("Dr. Sarah Khan");
    expect(row).toHaveTextContent("Cardiologist");
    expect(row).toHaveTextContent("Follow-up");
    expect(row).toHaveTextContent("Confirmed");
    expect(within(row).getByRole("link", { name: /View/ })).toHaveAttribute("href", "/appointments/a-1");
    expect(within(card).getByRole("link", { name: /View All/ })).toHaveAttribute("href", "/appointments?patient=p-1");
    expect(listAppointments).toHaveBeenCalledWith({ patient_id: "p-1", scope: "upcoming", page_size: 5 });
    expect(listAppointments).toHaveBeenCalledWith({ patient_id: "p-1", scope: "past", newest_first: true, page_size: 5 });

    await user.click(within(card).getByRole("tab", { name: "Recent Appointments (2)" }));
    expect(within(card).getAllByRole("row")[1]).toHaveTextContent("Completed");
  });

  it("row menus follow the state machine, and cancelling asks first", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockResolvedValue({ data: {} });
    renderPage();
    const card = await screen.findByRole("region", { name: "Appointments" });
    const [, row] = await within(card).findAllByRole("row");
    await user.click(within(row).getByRole("button", { name: /Actions for the appointment/ }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "View Appointment",
      "Check in",
      "Cancel appointment",
      "Reschedule",
    ]);
    expect(within(menu).getByRole("menuitem", { name: "Reschedule" })).toHaveAttribute("href", "/appointments/a-1?reschedule=1");
    await user.click(within(menu).getByRole("menuitem", { name: "Cancel appointment" }));
    expect(changeAppointmentStatus).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "Cancel appointment?" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));
    expect(changeAppointmentStatus).toHaveBeenCalledWith("a-1", { status: "cancelled", cancellation_reason: "patient_request" });
    await waitFor(() => expect(countAppointments).toHaveBeenCalledTimes(2)); // counts refreshed
  });

  it("explains a record that is missing or not accessible", async () => {
    getPatient.mockRejectedValue({ response: { status: 404, data: { error: { message: "Patient not found" } } } });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(/not found, or you do not have access/);
  });

  it("treating clinicians get the medical tab instead of a lock", async () => {
    listDocuments.mockResolvedValue({ data: [] });
    renderPage("/patients/p-1", [...PERMISSIONS.doctor, "document:read_assigned"]);
    await screen.findByRole("heading", { level: 1 });
    const tabs = screen.getByRole("navigation", { name: "Patient record sections" });
    expect(within(tabs).getByRole("link", { name: "Medical Information" })).toBeInTheDocument();
    expect(screen.queryByText("Medical Information", { selector: ".pd-locked" })).not.toBeInTheDocument();
    await waitFor(() => expect(listDocuments).toHaveBeenCalledWith("p-1"));
  });
});
