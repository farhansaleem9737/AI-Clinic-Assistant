import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../../context/useAuth";
import AdminDashboard from "./AdminDashboard";
import { changeAppointmentStatus, listAppointments } from "../../services/appointmentService";
import { getAdminDashboard } from "../../services/dashboardService";
import { authAs, PERMISSIONS } from "../../test/fixtures";

vi.mock("../../context/useAuth");
vi.mock("../../services/dashboardService");
vi.mock("../../services/appointmentService");

const kpi = (key, total, previous, change_percent, trend) => ({ key, total, previous, change_percent, trend });
const DATA = {
  date: "2027-04-23",
  timezone: "Asia/Karachi",
  compared_to: "2027-03-31",
  kpis: [
    kpi("users", 28, 25, 12.0, "up"),
    kpi("doctors", 8, 8, 0.0, "flat"),
    kpi("patients", 240, 250, -4.0, "down"),
    kpi("appointments", 156, 125, 24.8, "up"),
    kpi("departments", 6, 0, null, "new"),
  ],
  recent_users: [
    { id: "u-1", name: "Ayesha Malik", email: "ayesha@clinic.example", roles: ["receptionist"], is_active: true, created_at: "2027-04-20T09:00:00Z" },
    { id: "u-2", name: "Ahmed Raza", email: "ahmed@clinic.example", roles: ["doctor"], is_active: false, created_at: "2027-04-18T09:00:00Z" },
  ],
};
const APPOINTMENT = {
  id: "a-1",
  status: "confirmed",
  starts_at: "2027-04-23T04:00:00Z",
  ends_at: "2027-04-23T04:30:00Z",
  timezone: "Asia/Karachi",
  doctor: { id: "d-1", name: "Sarah Khan", title: "Dr.", specialization: "Cardiologist", department_name: "Cardiology" },
  patient: { id: "p-1", name: "John Doe", mrn: "MRN00000001", photo_url: null },
  allowed_transitions: ["cancelled", "checked_in"],
  can_reschedule: true,
};

function renderPage() {
  useAuth.mockReturnValue(authAs("Admin User", ["admin"], PERMISSIONS.admin));
  return render(
    <MemoryRouter initialEntries={["/admin"]}>
      <AdminDashboard />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  getAdminDashboard.mockResolvedValue({ data: DATA });
  listAppointments.mockResolvedValue({ data: { items: [APPOINTMENT], total: 1, page: 1, page_size: 5 } });
});

describe("Admin Dashboard", () => {
  it("shows the five clinic totals with their change since last month", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Admin Dashboard" })).toBeInTheDocument();
    const users = (await screen.findByText("Total Users")).closest(".kpi-card");
    expect(users).toHaveTextContent("28");
    expect(users).toHaveTextContent("up 12%");
    expect(users).toHaveTextContent("vs end of March");
    expect(screen.getByText("Doctors").closest(".kpi-card")).toHaveTextContent("no change 0%");
    expect(screen.getByText("Patients").closest(".kpi-card")).toHaveTextContent("down 4%");
    expect(screen.getByText("Departments").closest(".kpi-card")).toHaveTextContent("New"); // nothing to compare with
    expect(getAdminDashboard).toHaveBeenCalledWith(undefined); // the server decides what today is
  });

  it("lists the day's appointments with the actions allowed", async () => {
    const user = userEvent.setup();
    renderPage();
    const card = await screen.findByRole("region", { name: "Recent Appointments" });
    await waitFor(() => expect(listAppointments).toHaveBeenCalledWith({ date_from: "2027-04-23", date_to: "2027-04-23", page_size: 5 }));
    const row = (await within(card).findAllByRole("row"))[1];
    for (const text of ["Apr 23, 2027", "09:00 AM", "John Doe", "MRN00000001", "Dr. Sarah Khan", "Cardiology", "Confirmed"]) {
      expect(row).toHaveTextContent(text);
    }
    expect(within(card).getByRole("link", { name: /View All/ })).toHaveAttribute("href", "/appointments?date=2027-04-23");
    await user.click(within(row).getByRole("button", { name: /Actions for John Doe/ }));
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "View Appointment",
      "View Patient",
      "View Doctor",
      "Reschedule Appointment",
      "Cancel Appointment",
    ]);
  });

  it("cancels only after confirming, then refreshes", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockResolvedValue({ data: {} });
    renderPage();
    const card = await screen.findByRole("region", { name: "Recent Appointments" });
    const row = (await within(card).findAllByRole("row"))[1];
    await user.click(within(row).getByRole("button", { name: /Actions for John Doe/ }));
    await user.click(screen.getByRole("menuitem", { name: "Cancel Appointment" }));
    expect(changeAppointmentStatus).not.toHaveBeenCalled();
    await user.click(within(screen.getByRole("dialog", { name: "Cancel appointment?" })).getByRole("button", { name: "Cancel appointment" }));
    expect(changeAppointmentStatus).toHaveBeenCalledWith("a-1", { status: "cancelled", cancellation_reason: "clinic_decision" });
    await waitFor(() => expect(getAdminDashboard).toHaveBeenCalledTimes(2)); // totals refreshed
  });

  it("lists the newest accounts with role, status and join date", async () => {
    renderPage();
    const card = await screen.findByRole("region", { name: "Recent Users" });
    const [, ayesha, ahmed] = within(card).getAllByRole("row");
    expect(ayesha).toHaveTextContent("Ayesha Malik");
    expect(ayesha).toHaveTextContent("Receptionist");
    expect(ayesha).toHaveTextContent("ayesha@clinic.example");
    expect(ayesha).toHaveTextContent("Active");
    expect(ayesha).toHaveTextContent("Apr 20, 2027");
    expect(ahmed).toHaveTextContent("Doctor");
    expect(ahmed).toHaveTextContent("Inactive");
    expect(within(card).getByRole("link", { name: /View All/ })).toHaveAttribute("href", "/admin/users");
  });

  it("the management shortcuts go to the existing pages", async () => {
    renderPage();
    const actions = screen.getByRole("region", { name: "Quick Management Actions" });
    const hrefs = within(actions).getAllByRole("link").map((l) => l.getAttribute("href"));
    expect(hrefs).toEqual(["/admin/users", "/admin/doctors", "/admin/departments", "/appointments"]);
    expect(within(actions).getByRole("link", { name: /Manage Departments/ })).toHaveTextContent("Create and manage clinic departments");
  });

  it("a new date reloads the totals and the day's appointments", async () => {
    renderPage();
    await screen.findByText("Total Users");
    getAdminDashboard.mockResolvedValue({ data: { ...DATA, date: "2027-04-20" } });
    fireEvent.change(screen.getByLabelText("Dashboard date"), { target: { value: "2027-04-20" } });
    await waitFor(() => expect(getAdminDashboard).toHaveBeenLastCalledWith("2027-04-20"));
    await waitFor(() => expect(listAppointments).toHaveBeenLastCalledWith(expect.objectContaining({ date_from: "2027-04-20" })));
  });

  it("says when the day has no appointments", async () => {
    listAppointments.mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 5 } });
    renderPage();
    expect(await screen.findByText(/No appointments on/)).toBeInTheDocument();
  });

  it("explains a loading failure and can retry", async () => {
    const user = userEvent.setup();
    getAdminDashboard.mockRejectedValueOnce({ response: { data: { error: { message: "Service unavailable" } } } });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Total Users")).toBeInTheDocument();
  });
});

describe("Admin Dashboard refinement (D95)", () => {
  it("the information strip adds up the five real totals and says when they were fetched", async () => {
    renderPage();
    await screen.findByText("Total Users");
    const strip = screen.getByText(/records across these five totals/).closest(".admin-strip");
    expect(within(strip).getByText("438")).toBeInTheDocument(); // 28 + 8 + 240 + 156 + 6
    expect(strip).toHaveTextContent("created up to Apr 23, 2027");
    expect(strip).toHaveTextContent("Change is measured against the end of March");
    expect(strip).toHaveTextContent(/Last updated: \w{3} \d{1,2}, \d{4}/);
    expect(strip).not.toHaveTextContent("Live"); // no claim the page updates itself
  });

  it("long names and emails in Recent Users keep their full text on hover", async () => {
    renderPage();
    const card = await screen.findByRole("region", { name: "Recent Users" });
    expect(within(card).getByText("ayesha@clinic.example")).toHaveAttribute("title", "ayesha@clinic.example");
    expect(within(card).getByText("Ayesha Malik")).toHaveAttribute("title", "Ayesha Malik");
  });
});
