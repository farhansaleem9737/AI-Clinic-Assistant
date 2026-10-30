import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { listDoctors } from "../services/doctorService";
import { bulkSetPatientStatus, deactivatePatient, listPatients, registerPatient } from "../services/patientService";
import { authAs, PERMISSIONS } from "../test/fixtures";
import Patients from "./Patients";

vi.mock("../context/useAuth");
vi.mock("../services/patientService");
vi.mock("../services/doctorService");

// The receptionist role as seeded: read any, create and update patients, book.
const RECEPTION = [...PERMISSIONS.receptionist, "patient:update"];
const patient = (id, overrides = {}) => ({
  id,
  mrn: `MRN0000000${id}`,
  first_name: "John",
  last_name: "Doe",
  date_of_birth: "1990-01-01",
  sex_at_birth: "male",
  phone: "+1 555 123 4567",
  email: "john.doe@example.com",
  is_active: true,
  photo_url: null,
  created_at: "2026-04-10T09:00:00Z",
  ...overrides,
});
const JOHN = patient("1");
const JANE = patient("2", {
  first_name: "Jane",
  last_name: "Smith",
  sex_at_birth: "unknown",
  phone: null,
  email: "jane@example.com",
  is_active: false,
  created_at: "2026-04-12T09:00:00Z",
});
const page = (items, total = items.length) => ({ data: { items, total, page: 1, page_size: 10, total_pages: Math.ceil(total / 10) } });
const lastParams = () => listPatients.mock.calls.at(-1)[0];

function renderPage(permissions = RECEPTION) {
  useAuth.mockReturnValue(authAs("Ayesha Malik", ["receptionist"], permissions));
  return render(
    <MemoryRouter initialEntries={["/patients"]}>
      <Routes>
        <Route path="/patients" element={<Patients />} />
      </Routes>
    </MemoryRouter>
  );
}
const rows = async () => (await screen.findAllByRole("row")).slice(1);

beforeEach(() => {
  vi.resetAllMocks();
  listPatients.mockResolvedValue(page([JOHN, JANE]));
  listDoctors.mockResolvedValue({ data: { items: [{ id: "doc-1", name: "Sarah Khan", title: "Dr." }] } });
});

describe("Patients", () => {
  it("lists real records with counts, demographics and status", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Patients" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add Patient/ })).toBeInTheDocument();
    const [john, jane] = await rows();
    expect(screen.getAllByText("Showing 1 to 2 of 2 patients").length).toBeGreaterThan(0);
    expect(john).toHaveTextContent("John Doe");
    expect(john).toHaveTextContent(/\d+ years · Male/);
    expect(john).toHaveTextContent("MRN00000001");
    expect(john).toHaveTextContent("+1 555 123 4567");
    expect(john).toHaveTextContent("john.doe@example.com");
    expect(john).toHaveTextContent("Active");
    expect(john).toHaveTextContent("Apr 10, 2026");
    expect(john.querySelector("img")).toBeNull(); // no photo on file: initials, never a stock picture
    expect(jane).toHaveTextContent("Inactive");
    expect(jane).toHaveTextContent("Not provided"); // no phone
    expect(jane).not.toHaveTextContent("Not recorded"); // unknown sex is simply left out
    expect(lastParams()).toEqual({ page: 1, page_size: 10 });
  });

  it("searches after a pause and keeps the text out of the URL", async () => {
    const user = userEvent.setup();
    renderPage();
    await rows();
    await user.type(screen.getByLabelText(/Search patients/), "0300");
    await waitFor(() => expect(lastParams()).toEqual({ page: 1, page_size: 10, q: "0300" }));
    expect(listPatients.mock.calls.map(([p]) => p.q).filter(Boolean)).toEqual(["0300"]);
  });

  it("filters by status and by doctor, together", async () => {
    const user = userEvent.setup();
    renderPage();
    await rows();
    await user.selectOptions(screen.getByLabelText("Status"), "inactive");
    await waitFor(() => expect(lastParams()).toMatchObject({ is_active: "false", page: 1 }));
    await user.selectOptions(screen.getByLabelText("Doctor"), "doc-1");
    await waitFor(() => expect(lastParams()).toMatchObject({ is_active: "false", doctor_id: "doc-1" }));
    expect(screen.getByText(/who have an appointment with the selected doctor/)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Dr. Sarah Khan" })).toBeInTheDocument();
  });

  it("filters by registration date range and refuses a reversed one", async () => {
    const user = userEvent.setup();
    renderPage();
    await rows();
    await user.click(screen.getByRole("button", { name: /Registration date: Select Date Range/ }));
    const panel = screen.getByRole("group", { name: "Registration date" });
    fireEvent.change(within(panel).getByLabelText("From"), { target: { value: "2026-04-20" } });
    fireEvent.change(within(panel).getByLabelText("To"), { target: { value: "2026-04-01" } });
    await user.click(within(panel).getByRole("button", { name: "Apply" }));
    expect(within(panel).getByRole("alert")).toHaveTextContent("The start date must not be after the end date.");

    fireEvent.change(within(panel).getByLabelText("To"), { target: { value: "2026-04-30" } });
    await user.click(within(panel).getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(lastParams()).toMatchObject({ registered_from: "2026-04-20", registered_to: "2026-04-30" }));
    expect(screen.getByRole("button", { name: /Registration date: Apr 20, 2026 – Apr 30, 2026/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Registration date:/ }));
    await user.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(lastParams()).not.toHaveProperty("registered_from"));
  });

  it("selects rows on this page, with a select-all that knows a partial selection", async () => {
    const user = userEvent.setup();
    renderPage();
    const [john] = await rows();
    const all = screen.getByRole("checkbox", { name: "Select all patients on this page" });
    await user.click(within(john).getByRole("checkbox", { name: "Select John Doe" }));
    expect(all.indeterminate).toBe(true);
    expect(screen.getByText("1 patient selected on this page.")).toBeInTheDocument();
    // Reception may not change status, so no bulk buttons (D91).
    expect(screen.getByText(/Open a patient to act on their record/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deactivate" })).not.toBeInTheDocument();

    await user.click(all);
    expect(all).toBeChecked();
    expect(screen.getByText("2 patients selected on this page.")).toBeInTheDocument();
    await user.click(all);
    expect(screen.queryByText(/selected on this page/)).not.toBeInTheDocument();
  });

  it("clears the selection when the page changes", async () => {
    const user = userEvent.setup();
    listPatients.mockResolvedValue(page([JOHN, JANE], 25));
    renderPage();
    const [john] = await rows();
    await user.click(within(john).getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(lastParams()).toMatchObject({ page: 2 }));
    await waitFor(() => expect(screen.queryByText(/selected on this page/)).not.toBeInTheDocument());
  });

  it("row menus offer what reception may do, and no status change", async () => {
    const user = userEvent.setup();
    renderPage();
    const [john] = await rows();
    await user.click(within(john).getByRole("button", { name: "Actions for John Doe" }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "View Patient Details",
      "Edit Patient Information",
      "Book Appointment",
      "View Appointments",
    ]);
    expect(within(menu).getByRole("menuitem", { name: "View Appointments" })).toHaveAttribute("href", "/appointments?patient=1");
    expect(within(menu).getByRole("menuitem", { name: "View Patient Details" })).toHaveAttribute("href", "/patients/1");
    expect(within(menu).getByRole("menuitem", { name: "Book Appointment" })).toHaveAttribute("href", "/appointments/book?patient=1");
  });

  it("an inactive patient cannot be booked from the menu", async () => {
    const user = userEvent.setup();
    renderPage();
    const [, jane] = await rows();
    await user.click(within(jane).getByRole("button", { name: "Actions for Jane Smith" }));
    expect(screen.queryByRole("menuitem", { name: "Book Appointment" })).not.toBeInTheDocument();
  });

  it("administrators can deactivate after confirming", async () => {
    const user = userEvent.setup();
    deactivatePatient.mockResolvedValue({ data: {} });
    renderPage([...RECEPTION, "patient:deactivate"]);
    const [john] = await rows();
    await user.click(within(john).getByRole("button", { name: "Actions for John Doe" }));
    await user.click(screen.getByRole("menuitem", { name: "Deactivate Patient" }));
    expect(deactivatePatient).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "Deactivate patient?" });
    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    expect(deactivatePatient).toHaveBeenCalledWith("1");
    expect(await screen.findByText("John Doe is now inactive.")).toBeInTheDocument();
  });

  it("registers a walk-in patient and links to the new record", async () => {
    const user = userEvent.setup();
    registerPatient.mockResolvedValue({ data: patient("9", { first_name: "Ali", last_name: "Raza", mrn: "MRN00000099" }) });
    renderPage();
    await rows();
    await user.click(screen.getByRole("button", { name: /Add Patient/ }));
    const dialog = screen.getByRole("dialog", { name: "Add Patient" });
    await user.click(within(dialog).getByRole("button", { name: "Register patient" }));
    expect(within(dialog).getByText("Enter the first name.")).toBeInTheDocument();
    expect(registerPatient).not.toHaveBeenCalled();

    await user.type(within(dialog).getByLabelText("First name"), " Ali ");
    await user.type(within(dialog).getByLabelText("Last name"), "Raza");
    fireEvent.change(within(dialog).getByLabelText("Date of birth"), { target: { value: "1985-02-03" } });
    await user.type(within(dialog).getByLabelText("Phone (optional)"), "0300 1234567");
    const loads = listPatients.mock.calls.length;
    await user.click(within(dialog).getByRole("button", { name: "Register patient" }));

    expect(registerPatient).toHaveBeenCalledWith({
      first_name: "Ali",
      last_name: "Raza",
      date_of_birth: "1985-02-03",
      sex_at_birth: "unknown",
      phone: "0300 1234567",
      email: null,
      address: null,
      preferred_language: null,
    });
    expect(await screen.findByText(/Ali Raza was registered with MRN MRN00000099/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View patient record" })).toHaveAttribute("href", "/patients/9");
    await waitFor(() => expect(listPatients.mock.calls.length).toBeGreaterThan(loads)); // list and count refreshed
  });

  it("hides Add Patient from those who cannot register patients", async () => {
    renderPage(["patient:read_any"]);
    await rows();
    expect(screen.queryByRole("button", { name: /Add Patient/ })).not.toBeInTheDocument();
  });

  it("tells an empty database from no matches", async () => {
    const user = userEvent.setup();
    listPatients.mockResolvedValue(page([]));
    renderPage();
    expect(await screen.findByText("No patients have been registered yet.")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Status"), "active");
    expect(await screen.findByText("No patients match your search or filters.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear search and filters" }));
    await waitFor(() => expect(lastParams()).toEqual({ page: 1, page_size: 10 }));
  });

  it("explains a loading failure and can retry", async () => {
    const user = userEvent.setup();
    listPatients.mockRejectedValueOnce({ response: { data: { error: { message: "Service unavailable" } } } });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect((await rows()).length).toBe(2);
  });
});


describe("Admin > Patients (D91)", () => {
  const ADMIN = [...PERMISSIONS.admin, "patient:create", "patient:update", "patient:deactivate", "appointment:create"];
  const renderAdmin = () => renderPage(ADMIN);

  it("uses the admin heading and filters by gender, unrecorded included", async () => {
    const user = userEvent.setup();
    renderAdmin();
    expect(screen.getByText("Manage all clinic patients.")).toBeInTheDocument();
    await rows();
    const gender = screen.getByLabelText("Gender");
    expect(within(gender).getAllByRole("option").map((o) => o.textContent)).toEqual(["All Genders", "Female", "Male", "Intersex", "Not recorded"]);
    await user.selectOptions(gender, "unknown");
    await waitFor(() => expect(lastParams()).toEqual(expect.objectContaining({ sex_at_birth: "unknown", page: 1 })));
  });

  it("sorts every column on the server, toggling direction", async () => {
    const user = userEvent.setup();
    renderAdmin();
    await rows();
    await user.click(screen.getByRole("button", { name: /^MRN/ }));
    await waitFor(() => expect(lastParams().sort).toBe("mrn"));
    await user.click(screen.getByRole("button", { name: /^MRN/ }));
    await waitFor(() => expect(lastParams().sort).toBe("-mrn"));
    expect(screen.getByRole("columnheader", { name: /MRN/ })).toHaveAttribute("aria-sort", "descending");
    await user.click(screen.getByRole("button", { name: /^Phone/ }));
    await waitFor(() => expect(lastParams().sort).toBe("phone"));
  });

  it("bulk-deactivates the selected patients after confirming and lists refusals", async () => {
    const user = userEvent.setup();
    bulkSetPatientStatus.mockResolvedValue({
      data: [
        { patient_id: "1", ok: false, code: "HAS_UPCOMING_APPOINTMENTS", message: "This patient has upcoming appointments; cancel them first" },
        { patient_id: "2", ok: true },
      ],
    });
    renderAdmin();
    await rows();
    await user.click(screen.getByRole("checkbox", { name: "Select all patients on this page" }));
    await user.click(screen.getByRole("button", { name: "Deactivate" }));
    const dialog = screen.getByRole("dialog", { name: "Deactivate selected patients?" });
    expect(dialog).toHaveTextContent("nothing is cancelled or deleted");
    expect(bulkSetPatientStatus).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    expect(bulkSetPatientStatus).toHaveBeenCalledWith(["1", "2"], false);
    expect(await screen.findByText(/1 patient deactivated\. 1 could not be changed/)).toBeInTheDocument();
    expect(screen.getByText("John Doe: This patient has upcoming appointments; cancel them first")).toBeInTheDocument();
    await waitFor(() => expect(listPatients).toHaveBeenCalledTimes(2)); // refreshed
  });

  it("a failed bulk request is shown in the dialog", async () => {
    const user = userEvent.setup();
    bulkSetPatientStatus.mockRejectedValue({ response: { data: { error: { message: "Network down" } } } });
    renderAdmin();
    const [john] = await rows();
    await user.click(within(john).getByRole("checkbox", { name: "Select John Doe" }));
    await user.click(screen.getByRole("button", { name: "Activate" }));
    const dialog = screen.getByRole("dialog", { name: "Activate selected patients?" });
    await user.click(within(dialog).getByRole("button", { name: "Activate" }));
    expect(await within(dialog).findByText("Network down")).toBeInTheDocument();
  });

  it("admin row menu includes the status change", async () => {
    const user = userEvent.setup();
    renderAdmin();
    const [john] = await rows();
    await user.click(within(john).getByRole("button", { name: "Actions for John Doe" }));
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "View Patient Details",
      "Edit Patient Information",
      "Book Appointment",
      "View Appointments",
      "Deactivate Patient",
    ]);
  });
});
