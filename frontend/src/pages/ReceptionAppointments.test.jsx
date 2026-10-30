import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { changeAppointmentStatus, countAppointments, listAppointments } from "../services/appointmentService";
import { getPublicDepartments, listDepartments } from "../services/departmentService";
import { listDoctors } from "../services/doctorService";
import { authAs, PERMISSIONS } from "../test/fixtures";
import Appointments from "./Appointments";

vi.mock("../context/useAuth");
vi.mock("../services/appointmentService");
vi.mock("../services/departmentService");
vi.mock("../services/doctorService");

const doctor = { id: "d-1", name: "Sarah Khan", title: "Dr.", specialization: "Cardiologist", department_name: "Cardiology", photo_url: null };
const row = (id, overrides = {}) => ({
  id,
  status: "scheduled",
  starts_at: "2027-04-23T04:00:00Z", // 09:00 in Karachi
  ends_at: "2027-04-23T04:30:00Z",
  timezone: "Asia/Karachi",
  reason: "Follow-up",
  doctor,
  patient: { id: `p-${id}`, name: "John Doe", mrn: "MRN00000001", date_of_birth: "1994-04-15", sex_at_birth: "male", photo_url: null },
  allowed_transitions: ["confirmed", "checked_in", "cancelled"],
  can_reschedule: true,
  ...overrides,
});
const A1 = row("a-1");
const A2 = row("a-2", {
  status: "checked_in",
  starts_at: "2027-04-23T05:30:00Z",
  allowed_transitions: [],
  can_reschedule: false,
  patient: { id: "p-2", name: "Emily Carter", mrn: "MRN00000002", date_of_birth: "1998-01-01", sex_at_birth: "female", photo_url: null },
});
const page = (items, total = items.length) => ({ data: { items, total, page: 1, page_size: 10, total_pages: Math.ceil(total / 10) } });
const COUNTS = { all: 24, upcoming: 12, past: 6, today: 6, today_date: "2027-04-23" };
const lastList = () => listAppointments.mock.calls.at(-1)[0];
const lastCounts = () => countAppointments.mock.calls.at(-1)[0];

function renderPage(entry = "/appointments", permissions = [...PERMISSIONS.receptionist, "appointment:manage"]) {
  useAuth.mockReturnValue(authAs("Ayesha Malik", ["receptionist"], permissions));
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/appointments" element={<Appointments />} />
      </Routes>
    </MemoryRouter>
  );
}
const rows = async () => (await screen.findAllByRole("row")).slice(1);

beforeEach(() => {
  vi.resetAllMocks();
  listAppointments.mockResolvedValue(page([A1, A2], 24));
  countAppointments.mockResolvedValue({ data: COUNTS });
  listDoctors.mockResolvedValue({ data: { items: [{ ...doctor, is_active: true }, { id: "d-2", name: "Old Doc", title: null, is_active: false }] } });
  getPublicDepartments.mockResolvedValue({ data: { items: [{ id: "dep-1", name: "Cardiology" }] } });
});

describe("staff Appointments", () => {
  it("shows the tabs with real counts and the first page", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Appointments" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Book Appointment/ })).toHaveAttribute("href", "/appointments/book");
    expect(await screen.findByRole("tab", { name: "All (24)" })).toHaveAttribute("aria-selected", "true");
    for (const name of ["Today (6)", "Upcoming (12)", "Past (6)"]) expect(screen.getByRole("tab", { name })).toBeInTheDocument();
    expect(lastList()).toEqual({ page: 1, page_size: 10 });
    expect(lastCounts()).toEqual({ include_today: true });
    expect(screen.getByText("Showing 1 to 10 of 24 appointments")).toBeInTheDocument();
  });

  it("rows show date and time, patient, doctor, department and status", async () => {
    renderPage();
    const [first, second] = await rows();
    expect(first).toHaveTextContent("09:00 AM");
    expect(first).toHaveTextContent("Apr 23, 2027"); // date first, then time (D92)
    expect(first).toHaveTextContent("John Doe");
    expect(first).toHaveTextContent(/MRN00000001 · \d+ years · Male/);
    expect(first).toHaveTextContent("Dr. Sarah Khan");
    expect(first).toHaveTextContent("Cardiologist");
    expect(first).toHaveTextContent("Cardiology");
    expect(first).toHaveTextContent("Scheduled");
    expect(second).toHaveTextContent("Checked in");
    expect(first.querySelector("img")).toBeNull(); // illustration and initials, no stock photos
  });

  it("tabs map to today's date and the lifecycle scopes", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("tab", { name: "Today (6)" }));
    await waitFor(() => expect(lastList()).toMatchObject({ date_from: "2027-04-23", date_to: "2027-04-23" }));
    await user.click(screen.getByRole("tab", { name: "Upcoming (12)" }));
    await waitFor(() => expect(lastList()).toMatchObject({ scope: "upcoming" }));
    await user.click(screen.getByRole("tab", { name: "Past (6)" }));
    await waitFor(() => expect(lastList()).toMatchObject({ scope: "past", newest_first: true }));
  });

  it("searches after a pause, on the list and the counts", async () => {
    const user = userEvent.setup();
    renderPage();
    await rows();
    await user.type(screen.getByLabelText(/Search by patient name/), "chest");
    await waitFor(() => expect(lastList()).toMatchObject({ q: "chest", page: 1 }));
    expect(lastCounts()).toMatchObject({ q: "chest", include_today: true });
    expect(listAppointments.mock.calls.map(([p]) => p.q).filter(Boolean)).toEqual(["chest"]);
  });

  it("filters combine: date range, doctor, department and status", async () => {
    const user = userEvent.setup();
    renderPage();
    await rows();
    await user.click(screen.getByRole("button", { name: /Appointment dates:/ }));
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2027-04-25" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2027-04-29" } });
    await user.click(screen.getByRole("button", { name: "Apply" }));
    await user.selectOptions(screen.getByLabelText("Doctor"), "d-1");
    await user.selectOptions(screen.getByLabelText("Department"), "dep-1");
    await user.selectOptions(screen.getByLabelText("Status"), "confirmed");
    await waitFor(() =>
      expect(lastList()).toMatchObject({
        date_from: "2027-04-25",
        date_to: "2027-04-29",
        doctor_id: "d-1",
        department_id: "dep-1",
        status: ["confirmed"],
      })
    );
    expect(lastCounts()).toMatchObject({ date_from: "2027-04-25", doctor_id: "d-1", status: ["confirmed"] });
    expect(screen.getByRole("option", { name: "Old Doc (inactive)" })).toBeInTheDocument(); // history keeps its doctors

    // Clear Filters resets every filter (and the sort) in one go.
    await user.click(screen.getByRole("button", { name: "Clear Filters" }));
    await waitFor(() => expect(lastList()).toEqual({ page: 1, page_size: 10 }));
    expect(screen.getByRole("button", { name: "Clear Filters" })).toBeDisabled();
  });

  it("a one-day link from the dashboards still filters that day", async () => {
    renderPage("/appointments?date=2027-04-25");
    await rows();
    expect(lastList()).toMatchObject({ date_from: "2027-04-25", date_to: "2027-04-25" });
  });

  it("sorts on the server, toggling the direction", async () => {
    const user = userEvent.setup();
    renderPage();
    await rows();
    const patientHeader = screen.getByRole("columnheader", { name: /Patient/ });
    await user.click(within(patientHeader).getByRole("button"));
    await waitFor(() => expect(lastList()).toMatchObject({ sort: "patient_asc" }));
    expect(screen.getByRole("columnheader", { name: /Patient/ })).toHaveAttribute("aria-sort", "ascending");
    await user.click(within(screen.getByRole("columnheader", { name: /Patient/ })).getByRole("button"));
    await waitFor(() => expect(lastList()).toMatchObject({ sort: "patient_desc" }));
    expect(within(screen.getByRole("columnheader", { name: "Actions" })).queryByRole("button")).not.toBeInTheDocument();
  });

  it("row menus follow the state machine and link to the records", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockResolvedValue({ data: {} });
    renderPage();
    const [first] = await rows();
    await user.click(within(first).getByRole("button", { name: /Actions for John Doe/ }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "View Appointment",
      "View Patient",
      "View Doctor",
      "Confirm appointment",
      "Check in",
      "Cancel appointment",
      "Reschedule Appointment",
    ]);
    expect(within(menu).getByRole("menuitem", { name: "View Patient" })).toHaveAttribute("href", "/patients/p-a-1");
    expect(within(menu).getByRole("menuitem", { name: "View Doctor" })).toHaveAttribute("href", "/doctors/d-1");
    const before = countAppointments.mock.calls.length;
    await user.click(within(menu).getByRole("menuitem", { name: "Check in" }));
    expect(changeAppointmentStatus).toHaveBeenCalledWith("a-1", { status: "checked_in" });
    expect(await screen.findByText("John Doe: checked in.")).toBeInTheDocument();
    await waitFor(() => expect(countAppointments.mock.calls.length).toBeGreaterThan(before));
  });

  it("cancelling asks first and sends a reason", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockResolvedValue({ data: {} });
    renderPage();
    const [first] = await rows();
    await user.click(within(first).getByRole("button", { name: /Actions for John Doe/ }));
    await user.click(screen.getByRole("menuitem", { name: "Cancel appointment" }));
    expect(changeAppointmentStatus).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "Cancel appointment?" });
    await user.selectOptions(within(dialog).getByLabelText("Reason"), "clinic_decision");
    await user.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));
    expect(changeAppointmentStatus).toHaveBeenCalledWith("a-1", { status: "cancelled", cancellation_reason: "clinic_decision" });
  });

  it("explains a refused action", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockRejectedValue({ response: { status: 409, data: { error: { message: "Cannot change an appointment from cancelled to confirmed" } } } });
    renderPage();
    const [first] = await rows();
    await user.click(within(first).getByRole("button", { name: /Actions for John Doe/ }));
    await user.click(screen.getByRole("menuitem", { name: "Confirm appointment" }));
    expect(await screen.findByText(/Cannot change an appointment/)).toBeInTheDocument();
  });

  it("pages through the results", async () => {
    const user = userEvent.setup();
    renderPage();
    await rows();
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(lastList()).toMatchObject({ page: 2 }));
  });

  it("keeps a patient filter from the patient's record, with a way out", async () => {
    const user = userEvent.setup();
    renderPage("/appointments?patient=p-9");
    await rows();
    expect(lastList()).toMatchObject({ patient_id: "p-9" });
    expect(screen.getByRole("link", { name: /Book Appointment/ })).toHaveAttribute("href", "/appointments/book?patient=p-9");
    await user.click(screen.getByRole("button", { name: "Show all patients" }));
    await waitFor(() => expect(lastList()).not.toHaveProperty("patient_id"));
  });

  it("tells an empty list from no matches", async () => {
    const user = userEvent.setup();
    listAppointments.mockResolvedValue(page([]));
    renderPage();
    expect(await screen.findByText("No appointments yet.")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Status"), "no_show");
    expect(await screen.findByText("No appointments match your search or filters.")).toBeInTheDocument();
  });

  it("explains a loading failure and can retry", async () => {
    const user = userEvent.setup();
    listAppointments.mockRejectedValueOnce({ response: { data: { error: { message: "Service unavailable" } } } });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect((await rows()).length).toBe(2);
  });
});


describe("Admin > Appointments (D92)", () => {
  const ADMIN = [...PERMISSIONS.admin, "appointment:create", "appointment:manage", "department:manage"];

  it("says Add Appointment, offers inactive departments, and searches by MRN", async () => {
    listDepartments.mockResolvedValue({ data: { items: [{ id: "dep-1", name: "Cardiology", is_active: true }, { id: "dep-old", name: "Radiology", is_active: false }] } });
    const user = userEvent.setup();
    renderPage("/appointments", ADMIN);
    await rows();
    expect(screen.getByText("View and manage clinic appointments.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Add Appointment/ })).toHaveAttribute("href", "/appointments/book");
    expect(await screen.findByRole("option", { name: "Radiology (inactive)" })).toBeInTheDocument();
    expect(getPublicDepartments).not.toHaveBeenCalled();
    await user.type(screen.getByRole("searchbox", { name: "Search by patient name, doctor name or MRN" }), "MRN0001");
    await waitFor(() => expect(lastList()).toMatchObject({ q: "MRN0001", page: 1 }));
  });
});
