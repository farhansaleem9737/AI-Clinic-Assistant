import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { listAppointments } from "../services/appointmentService";
import { getDashboardSummary } from "../services/dashboardService";
import { getMyDoctorProfile } from "../services/doctorService";
import { getMyPatientProfile } from "../services/patientService";
import { appointment, authAs, doctorProfile, page, patientProfile, PERMISSIONS, summaries } from "../test/fixtures";
import Dashboard from "./Dashboard";

vi.mock("../context/useAuth");
vi.mock("../services/dashboardService");
vi.mock("../services/appointmentService");
vi.mock("../services/patientService");
vi.mock("../services/doctorService");

const apiError = (message) => ({ response: { data: { error: { code: "X", message } } } });

function renderDashboard(role, name = "John Doe") {
  useAuth.mockReturnValue(authAs(name, [role], PERMISSIONS[role] ?? []));
  return render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  listAppointments.mockResolvedValue(page([appointment()]));
  getMyPatientProfile.mockResolvedValue({ data: patientProfile });
  getMyDoctorProfile.mockResolvedValue({ data: doctorProfile });
});

describe("patient dashboard", () => {
  beforeEach(() => getDashboardSummary.mockResolvedValue({ data: summaries.patient }));

  it("greets the user and shows their four summary cards from the API", async () => {
    renderDashboard("patient");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(/John!$/);

    for (const [label, value] of [
      ["Upcoming Appointments", "2"],
      ["Total Appointments", "5"],
      ["My Doctors", "3"],
      ["Account Status", "Active"],
    ]) {
      const card = (await screen.findAllByText(label)).map((el) => el.closest(".stat-card")).find(Boolean);
      expect(within(card).getByText(value)).toBeInTheDocument();
    }
  });

  it("lists upcoming appointments with doctor, room and status, linking to the detail page", async () => {
    renderDashboard("patient");
    const section = await screen.findByRole("region", { name: "Upcoming Appointments" });
    const row = await within(section).findByRole("article", { name: /Dr\. Sarah Khan/ });
    expect(row).toHaveTextContent("Cardiologist · Cardiology");
    expect(row).toHaveTextContent("Room B-12");
    expect(row).toHaveTextContent("Confirmed");
    expect(row).toHaveTextContent("Oct5Mon"); // date block, in the clinic's timezone
    expect(within(row).getByRole("link", { name: /View details/ })).toHaveAttribute("href", "/appointments/appt-1");
    // The doctor gets the illustrated avatar, not initials or a photo.
    expect(row.querySelector('[data-avatar="doctor"]')).not.toBeNull();
    expect(row.querySelector("img")).toBeNull();
    // Asked for with the same "upcoming" rule the count uses.
    expect(listAppointments).toHaveBeenCalledWith({ upcoming: true, page_size: 3 });
  });

  it("shows the counts from the summary, not from the list", async () => {
    renderDashboard("patient");
    const card = (label) => screen.getAllByText(label).map((el) => el.closest(".stat-card")).find(Boolean);
    await screen.findByRole("region", { name: "Upcoming Appointments" });
    expect(card("Upcoming Appointments")).toHaveTextContent("2");
    expect(card("Total Appointments")).toHaveTextContent("5");
    expect(card("My Doctors")).toHaveTextContent("3");
    expect(card("Account Status")).toHaveTextContent("Active");
    expect(within(card("My Doctors")).getByRole("link", { name: /View doctors/ })).toHaveAttribute("href", "/doctors");
  });

  it("shows the profile summary with the MRN, formatted details and an active badge", async () => {
    renderDashboard("patient");
    const profile = await screen.findByRole("region", { name: "My Profile" });
    expect(await within(profile).findByText("MRN00000001")).toBeInTheDocument();
    expect(profile).toHaveTextContent("John Doe");
    expect(profile).toHaveTextContent("Active");
    expect(profile).toHaveTextContent(new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(new Date("1990-01-01T00:00:00Z")));
    expect(profile).toHaveTextContent("Male");
    expect(profile).toHaveTextContent("123 Main St");
    expect(within(profile).getByRole("link", { name: /View profile/ })).toHaveAttribute("href", "/profile");
    // Patients get initials until they upload a picture.
    expect(profile.querySelector('[data-avatar="initials"]')).toHaveTextContent("JD");
  });

  it("says when a profile detail is missing instead of leaving it blank", async () => {
    getMyPatientProfile.mockResolvedValue({ data: { ...patientProfile, phone: null, address: null } });
    renderDashboard("patient");
    const profile = await screen.findByRole("region", { name: "My Profile" });
    await within(profile).findByText("MRN00000001");
    expect(within(profile).getAllByText("Not provided")).toHaveLength(2);
    expect(profile).not.toHaveTextContent(/null|undefined/);
  });

  it("offers help and support without inventing contact details", async () => {
    renderDashboard("patient");
    const help = await screen.findByRole("region", { name: "Need Help?" });
    expect(within(help).getByRole("link", { name: /Contact Support/ })).toHaveAttribute("href", "/help#contact");
  });

  it("offers the quick actions and profile, all pointing at existing pages", async () => {
    renderDashboard("patient");
    const actions = await screen.findByRole("region", { name: "Quick Actions" });
    const hrefs = within(actions).getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/appointments/book", "/doctors", "/appointments", "/profile"]);

    const profile = await screen.findByRole("region", { name: "My Profile" });
    expect(await within(profile).findByText("MRN00000001")).toBeInTheDocument();
    expect(within(profile).getByRole("link", { name: /Edit Profile/ })).toHaveAttribute("href", "/profile");
  });

  it("shows no staff sections", async () => {
    renderDashboard("patient");
    await screen.findByRole("region", { name: "Upcoming Appointments" });
    expect(screen.queryByText("Today's Worklist")).not.toBeInTheDocument();
    expect(screen.queryByText("Clinic Overview")).not.toBeInTheDocument();
  });

  it("shows an empty state with a way to find a doctor when there are no upcoming appointments", async () => {
    listAppointments.mockResolvedValue(page([]));
    renderDashboard("patient");
    expect(await screen.findByText("No upcoming appointments.")).toBeInTheDocument();
    const section = screen.getByRole("region", { name: "Upcoming Appointments" });
    expect(within(section).getByRole("link", { name: /Find a doctor/ })).toHaveAttribute("href", "/doctors");
  });

  it("asks a patient without a profile to complete it", async () => {
    getDashboardSummary.mockResolvedValue({
      data: { ...summaries.patient, patient: { ...summaries.patient.patient, has_profile: false, profile_active: false } },
    });
    renderDashboard("patient");
    expect(await screen.findByText("Incomplete")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Complete profile" })).toHaveAttribute("href", "/profile");
    expect(getMyPatientProfile).not.toHaveBeenCalled();
    expect(listAppointments).not.toHaveBeenCalled();
  });

  it("keeps the rest of the page when one section fails to load", async () => {
    listAppointments.mockRejectedValue(apiError("Appointments are unavailable"));
    renderDashboard("patient");
    expect((await screen.findAllByText("Appointments are unavailable")).length).toBeGreaterThan(0);
    expect(screen.getByText("My Doctors")).toBeInTheDocument();
    expect(await screen.findByText("MRN00000001")).toBeInTheDocument();
  });
});

describe("other roles", () => {
  it("doctor: today's workload and patients, no clinic-wide figures", async () => {
    getDashboardSummary.mockResolvedValue({ data: summaries.doctor });
    renderDashboard("doctor", "Dr. Sarah Khan");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(/Sarah!$/);
    const todays = await screen.findByRole("region", { name: "Today's Appointments" });
    expect(await within(todays).findByRole("link", { name: /John Doe/ })).toBeInTheDocument();
    expect(screen.getByText("Waiting (checked in)")).toBeInTheDocument();
    expect(screen.getByText("My Patients").closest(".stat-card")).toHaveTextContent("14");
    expect(screen.queryByText("Clinic Overview")).not.toBeInTheDocument();
    expect(screen.queryByText("Today's Worklist")).not.toBeInTheDocument();
  });

  it("doctor login without a profile gets an explanation instead of a broken page", async () => {
    getDashboardSummary.mockResolvedValue({
      data: { ...summaries.doctor, doctor: { has_profile: false, today: null, upcoming_appointments: 0, my_patients: 0 } },
    });
    renderDashboard("doctor");
    expect(await screen.findByText(/no doctor profile yet/)).toBeInTheDocument();
  });

  it("receptionist: worklist and only the totals the API sent", async () => {
    getDashboardSummary.mockResolvedValue({ data: summaries.receptionist });
    renderDashboard("receptionist");
    const worklist = await screen.findByRole("region", { name: "Today's Worklist" });
    expect(await within(worklist).findByRole("article", { name: /John Doe/ })).toHaveTextContent("MRN00000001 · Dr. Sarah Khan");
    expect(screen.getByText("Awaiting Check-in").closest(".stat-card")).toHaveTextContent("3");

    const overview = screen.getByRole("region", { name: "Clinic Overview" });
    expect(within(overview).getByText("Active patients")).toBeInTheDocument();
    expect(within(overview).queryByText("Active users")).not.toBeInTheDocument();
    expect(within(overview).queryByText("Departments")).not.toBeInTheDocument();
  });

  it("admin: the full clinic overview with links to the admin pages", async () => {
    getDashboardSummary.mockResolvedValue({ data: summaries.admin });
    renderDashboard("admin");
    const overview = await screen.findByRole("region", { name: "Clinic Overview" });
    const users = within(overview).getByText("Active users").closest(".stat-card");
    expect(users).toHaveTextContent("24");
    expect(within(users).getByRole("link")).toHaveAttribute("href", "/admin/users");
    expect(within(overview).getByText("Departments").closest(".stat-card")).toHaveTextContent("5");
  });
});

describe("page states", () => {
  it("shows a loading state until the summary arrives", () => {
    getDashboardSummary.mockReturnValue(new Promise(() => {}));
    renderDashboard("patient");
    expect(screen.getByRole("status", { name: "Loading dashboard" })).toBeInTheDocument();
  });

  it("shows the API error when the summary fails", async () => {
    getDashboardSummary.mockRejectedValue(apiError("Could not validate credentials"));
    renderDashboard("patient");
    expect(await screen.findByText("Could not validate credentials")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading dashboard" })).not.toBeInTheDocument();
  });

  it("explains itself to an account with no role", async () => {
    getDashboardSummary.mockResolvedValue({ data: summaries.noRole });
    renderDashboard("none");
    expect(await screen.findByText(/no role with a dashboard yet/)).toBeInTheDocument();
    expect(listAppointments).not.toHaveBeenCalled();
  });
});
