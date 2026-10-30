import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  activateDepartment,
  createDepartment,
  deactivateDepartment,
  getDepartment,
  getDepartmentSummary,
  getPublicDepartments,
  listDepartments,
  updateDepartment,
} from "../services/departmentService";
import { listDoctors, updateDoctor } from "../services/doctorService";
import { getClinicSettings } from "../services/workspaceService";
import { departmentLook, timezoneLabel } from "../utils/departments";
import AdminDepartments from "./AdminDepartments";

vi.mock("../services/departmentService");
vi.mock("../services/doctorService");
vi.mock("../services/workspaceService");

const doc = (id, name, extra = {}) => ({ id, name, title: "Dr.", photo_url: null, ...extra });
const dept = (id, name, overrides = {}) => ({
  id,
  name,
  description: null,
  timezone: "Asia/Karachi",
  is_active: true,
  icon: null,
  color: null,
  created_at: "2027-01-01T00:00:00Z",
  updated_at: "2027-02-01T00:00:00Z",
  doctor_count: 0,
  doctors_preview: [],
  ...overrides,
});
const CARDIO = dept("dep-1", "Cardiology", { doctor_count: 5, doctors_preview: [doc("d1", "Ayesha Khan"), doc("d2", "Bilal Ahmed"), doc("d3", "Sara Ali")] });
const PEDS = dept("dep-2", "Pediatrics", { is_active: false, doctor_count: 1, doctors_preview: [doc("d4", "Omar Farooq")] });
const EMPTY = dept("dep-3", "Radiology");
const page = (items, total = items.length) => ({ data: { items, total, page: 1, page_size: 10, total_pages: Math.max(1, Math.ceil(total / 10)) } });

function renderPage() {
  return render(
    <MemoryRouter>
      <AdminDepartments />
    </MemoryRouter>
  );
}
const lastParams = () => listDepartments.mock.calls.at(-1)[0];
const rowOf = async (name) => (await screen.findByRole("button", { name })).closest("li");

beforeEach(() => {
  vi.resetAllMocks();
  listDepartments.mockResolvedValue(page([CARDIO, PEDS, EMPTY], 30));
  getDepartmentSummary.mockResolvedValue({ data: { total: 6, active: 5, inactive: 1, doctors: 18 } });
  getClinicSettings.mockResolvedValue({ data: { operational: { timezone: "Asia/Karachi" } } });
  getPublicDepartments.mockResolvedValue({ data: { items: [{ id: "dep-1", name: "Cardiology" }, { id: "dep-9", name: "Neurology" }] } });
});

describe("Departments list", () => {
  it("renders a card per department: status, description, doctor avatars and count, View Doctors", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Departments" })).toBeInTheDocument();
    expect(screen.getByText("Manage clinic departments and their details.")).toBeInTheDocument();
    const cardio = await rowOf("Cardiology");
    expect(cardio).toHaveTextContent("Active");
    expect(cardio).toHaveTextContent("+2");
    expect(cardio).toHaveTextContent("5 doctors");
    expect(within(cardio).getByRole("link", { name: "View doctors in Cardiology" })).toHaveAttribute("href", "/admin/doctors?department=dep-1");
    const peds = await rowOf("Pediatrics");
    expect(peds).toHaveTextContent("1 doctor");
    expect(peds.querySelector(".avatar-stack-more")).toBeNull(); // 1 doctor, 1 avatar: no "+N"
    expect(peds).toHaveTextContent("Inactive");
    const empty = await rowOf("Radiology");
    expect(empty).toHaveTextContent("0 doctors");
    expect(empty).toHaveTextContent("No description provided.");
    expect(empty.querySelector("img")).toBeNull(); // no stock photos anywhere
    expect(screen.getByText("Showing 1 to 12 of 30 departments")).toBeInTheDocument();
    expect(lastParams()).toEqual({ page: 1, page_size: 12, sort: "name" });
  });

  it("shows clinic-wide totals that the filters do not change", async () => {
    const u = userEvent.setup();
    renderPage();
    const totals = screen.getByRole("region", { name: "Department totals" });
    for (const label of ["Total Departments: 6", "Active Departments: 5", "Inactive Departments: 1", "Total Doctors: 18"])
      expect(await within(totals).findByLabelText(label)).toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText("Status"), "inactive");
    await waitFor(() => expect(lastParams()).toMatchObject({ is_active: false }));
    expect(getDepartmentSummary).toHaveBeenCalledTimes(1);
  });

  it("totals refresh after a change", async () => {
    const u = userEvent.setup();
    activateDepartment.mockResolvedValue({ data: { ...PEDS, is_active: true } });
    renderPage();
    await u.click(within(await rowOf("Pediatrics")).getByRole("button", { name: "Actions for Pediatrics" }));
    await u.click(screen.getByRole("menuitem", { name: "Activate Department" }));
    await u.click(within(screen.getByRole("dialog", { name: "Activate department?" })).getByRole("button", { name: "Activate" }));
    await waitFor(() => expect(getDepartmentSummary).toHaveBeenCalledTimes(2));
  });

  it("a failed totals request shows dashes, not made-up numbers", async () => {
    getDepartmentSummary.mockRejectedValue(new Error("down"));
    renderPage();
    expect(await screen.findByLabelText("Total Departments: unavailable")).toHaveTextContent("—");
  });

  it("searches after a pause and filters by status, back to page 1", async () => {
    const u = userEvent.setup();
    renderPage();
    await rowOf("Cardiology");
    await u.click(screen.getByRole("button", { name: "Page 2" }));
    await waitFor(() => expect(lastParams().page).toBe(2));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search departments" }), { target: { value: "card" } });
    await waitFor(() => expect(lastParams()).toEqual({ page: 1, page_size: 12, sort: "name", q: "card" }));
    await u.selectOptions(screen.getByLabelText("Status"), "inactive");
    await waitFor(() => expect(lastParams()).toEqual({ page: 1, page_size: 12, sort: "name", q: "card", is_active: false }));
  });

  it("empty and no-match states", async () => {
    listDepartments.mockResolvedValue(page([]));
    const u = userEvent.setup();
    renderPage();
    expect(await screen.findByText(/No departments yet/)).toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText("Status"), "active");
    expect(await screen.findByText("No departments match your search or filters.")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Clear search and filters" }));
    await waitFor(() => expect(lastParams()).toEqual({ page: 1, page_size: 12, sort: "name" }));
  });

  it("explains a loading failure and retries", async () => {
    listDepartments.mockRejectedValueOnce({ response: { data: { error: { message: "Service unavailable" } } } });
    const u = userEvent.setup();
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await u.click(screen.getByRole("button", { name: "Try again" }));
    expect(await rowOf("Cardiology")).toBeInTheDocument();
  });

  it("actions menu offers view, edit, manage doctors and the status change", async () => {
    const u = userEvent.setup();
    renderPage();
    await u.click(within(await rowOf("Pediatrics")).getByRole("button", { name: "Actions for Pediatrics" }));
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "View Department",
      "Edit Department",
      "Manage Doctors",
      "Activate Department",
    ]);
  });
});

describe("Add and edit", () => {
  it("validates, then creates with the clinic timezone by default", async () => {
    const u = userEvent.setup();
    createDepartment.mockResolvedValue({ data: dept("dep-7", "Neurology") });
    renderPage();
    await u.click(screen.getByRole("button", { name: /Add Department/ }));
    const dialog = screen.getByRole("dialog", { name: "Add Department" });
    await waitFor(() => expect(within(dialog).getByLabelText("Timezone")).toHaveValue("Asia/Karachi"));
    await u.click(within(dialog).getByRole("button", { name: "Add Department" }));
    expect(within(dialog).getByText("Enter the department name.")).toBeInTheDocument();
    await u.type(within(dialog).getByLabelText("Department name"), "  Neurology ");
    await u.selectOptions(within(dialog).getByLabelText("Icon (optional)"), "brain");
    await u.selectOptions(within(dialog).getByLabelText("Icon colour (optional)"), "orange");
    await u.click(within(dialog).getByRole("button", { name: "Add Department" }));
    expect(createDepartment).toHaveBeenCalledWith({
      name: "Neurology",
      description: null,
      timezone: "Asia/Karachi",
      icon: "brain",
      color: "orange",
      is_active: true,
    });
    expect(await screen.findByText("Added Neurology.")).toBeInTheDocument();
    await waitFor(() => expect(listDepartments).toHaveBeenCalledTimes(2));
  });

  it("a duplicate name is shown on the field", async () => {
    const u = userEvent.setup();
    createDepartment.mockRejectedValue({ response: { status: 409, data: { error: { code: "DEPARTMENT_EXISTS", message: "Department already exists" } } } });
    renderPage();
    await u.click(screen.getByRole("button", { name: /Add Department/ }));
    const dialog = screen.getByRole("dialog", { name: "Add Department" });
    await u.type(within(dialog).getByLabelText("Department name"), "Cardiology");
    await u.click(within(dialog).getByRole("button", { name: "Add Department" }));
    expect(await within(dialog).findByText("A department with this name already exists.")).toBeInTheDocument();
  });

  it("edits name, description and timezone; status is not in the form", async () => {
    const u = userEvent.setup();
    updateDepartment.mockResolvedValue({ data: { ...CARDIO, name: "Cardiac Care" } });
    renderPage();
    await u.click(within(await rowOf("Cardiology")).getByRole("button", { name: "Actions for Cardiology" }));
    await u.click(screen.getByRole("menuitem", { name: "Edit Department" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Department" });
    expect(within(dialog).queryByLabelText("Status")).not.toBeInTheDocument();
    await u.clear(within(dialog).getByLabelText("Department name"));
    await u.type(within(dialog).getByLabelText("Department name"), "Cardiac Care");
    await u.type(within(dialog).getByLabelText("Description (optional)"), "Heart");
    await u.selectOptions(within(dialog).getByLabelText("Timezone"), "Europe/London");
    await u.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(updateDepartment).toHaveBeenCalledWith("dep-1", { name: "Cardiac Care", description: "Heart", timezone: "Europe/London", icon: null, color: null });
    expect(await screen.findByText("Saved Cardiac Care.")).toBeInTheDocument();
  });
});

describe("Details, doctors and status", () => {
  const DETAIL = {
    ...CARDIO,
    doctors: [
      { ...doc("d1", "Ayesha Khan"), specialization: "Cardiologist", is_active: true },
      { ...doc("d8", "Retired Doc"), specialization: "Cardiologist", is_active: false },
    ],
    upcoming_appointments: 4,
  };

  it("View Department lists every doctor, practising or not", async () => {
    const u = userEvent.setup();
    getDepartment.mockResolvedValue({ data: DETAIL });
    renderPage();
    await u.click(await screen.findByRole("button", { name: "Cardiology" }));
    const dialog = screen.getByRole("dialog", { name: "Department details" });
    const list = await within(dialog).findByRole("list", { name: "Doctors in this department" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("Dr. Ayesha Khan"),
      expect.stringContaining("Inactive"),
    ]);
    expect(dialog).toHaveTextContent("4 appointments");
    expect(dialog).toHaveTextContent("(GMT+05:00) Karachi");
  });

  it("deactivating warns about upcoming appointments that are kept", async () => {
    const u = userEvent.setup();
    getDepartment.mockResolvedValue({ data: DETAIL });
    deactivateDepartment.mockResolvedValue({ data: { ...CARDIO, is_active: false } });
    renderPage();
    await u.click(within(await rowOf("Cardiology")).getByRole("button", { name: "Actions for Cardiology" }));
    await u.click(screen.getByRole("menuitem", { name: "Deactivate Department" }));
    const dialog = screen.getByRole("dialog", { name: "Deactivate department?" });
    expect(await within(dialog).findByText(/4 upcoming appointments will be kept as booked/)).toBeInTheDocument();
    expect(deactivateDepartment).not.toHaveBeenCalled();
    await u.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    expect(deactivateDepartment).toHaveBeenCalledWith("dep-1");
    expect(await screen.findByText("Cardiology is now inactive.")).toBeInTheDocument();
  });

  it("activating shows the server's refusal in the dialog", async () => {
    const u = userEvent.setup();
    activateDepartment.mockRejectedValue({ response: { data: { error: { message: "Not allowed" } } } });
    renderPage();
    await u.click(within(await rowOf("Pediatrics")).getByRole("button", { name: "Actions for Pediatrics" }));
    await u.click(screen.getByRole("menuitem", { name: "Activate Department" }));
    const dialog = screen.getByRole("dialog", { name: "Activate department?" });
    await u.click(within(dialog).getByRole("button", { name: "Activate" }));
    expect(await within(dialog).findByText("Not allowed")).toBeInTheDocument();
  });

  it("Manage Doctors moves a doctor in and another out", async () => {
    const u = userEvent.setup();
    getDepartment.mockResolvedValue({ data: DETAIL });
    listDoctors.mockResolvedValue({
      data: { items: [{ ...doc("d20", "Zara Malik"), department_id: "dep-9", department_name: "Neurology" }, { ...doc("d1", "Ayesha Khan"), department_id: "dep-1" }] },
    });
    updateDoctor.mockResolvedValue({ data: {} });
    renderPage();
    await u.click(within(await rowOf("Cardiology")).getByRole("button", { name: "Actions for Cardiology" }));
    await u.click(screen.getByRole("menuitem", { name: "Manage Doctors" }));
    const dialog = screen.getByRole("dialog", { name: "Manage doctors: Cardiology" });

    await u.type(within(dialog).getByRole("searchbox", { name: "Search doctors to add" }), "zara{Enter}");
    expect(listDoctors).toHaveBeenCalledWith({ q: "zara", page_size: 20 });
    const candidates = await within(dialog).findByRole("list", { name: "Doctors you can add" });
    expect(within(candidates).getAllByRole("listitem")).toHaveLength(1); // already-assigned doctors are not offered
    await u.click(within(candidates).getByRole("button", { name: "Add Zara Malik to Cardiology" }));
    expect(updateDoctor).toHaveBeenCalledWith("d20", { department_id: "dep-1" });
    expect(await within(dialog).findByText("Zara Malik moved to Cardiology.")).toBeInTheDocument();

    await u.click(within(dialog).getByRole("button", { name: "Remove Ayesha Khan from Cardiology" }));
    const move = within(dialog).getByRole("button", { name: "Move" });
    expect(move).toBeDisabled(); // a doctor must land in another department
    await u.selectOptions(within(dialog).getByLabelText("Move Ayesha Khan to"), "dep-9");
    await u.click(move);
    expect(updateDoctor).toHaveBeenLastCalledWith("d1", { department_id: "dep-9" });
    // Only other active departments are offered as destinations.
    expect(getPublicDepartments).toHaveBeenCalled();
  });
});

describe("Department helpers", () => {
  it("labels timezones with the offset in force on the date (DST)", () => {
    expect(timezoneLabel("Asia/Karachi")).toBe("(GMT+05:00) Karachi");
    expect(timezoneLabel("America/New_York", new Date("2027-01-15T12:00:00Z"))).toBe("(GMT-05:00) New York");
    expect(timezoneLabel("America/New_York", new Date("2027-07-15T12:00:00Z"))).toBe("(GMT-04:00) New York");
    expect(timezoneLabel("UTC")).toBe("(GMT+00:00) UTC");
  });

  it("uses the saved icon, otherwise a guess from the name", () => {
    expect(departmentLook({ name: "Cardiology", icon: null, color: null })).toEqual({ icon: "heart-pulse", color: "red" });
    expect(departmentLook({ name: "ENT", icon: null, color: null })).toEqual({ icon: "ear", color: "yellow" });
    expect(departmentLook({ name: "Cardiology", icon: "brain", color: "teal" })).toEqual({ icon: "brain", color: "teal" });
  });
});

describe("Blank-screen regression (D95)", () => {
  // Exactly what a server older than D89 returns: no doctor fields.
  const OLD_SHAPE = {
    id: "dep-old",
    name: "Cardiology",
    description: "Heart care",
    timezone: "Asia/Karachi",
    is_active: true,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
  };

  it("loads past the skeleton and keeps the cards on screen with an older server's response", async () => {
    let resolve;
    listDepartments.mockReturnValue(new Promise((r) => (resolve = r)));
    getDepartmentSummary.mockRejectedValue({ response: { status: 422 } });
    renderPage();
    expect(screen.getByRole("status", { name: "Loading departments" })).toBeInTheDocument();
    resolve(page([OLD_SHAPE]));
    const card = await rowOf("Cardiology");
    expect(screen.queryByRole("status", { name: "Loading departments" })).not.toBeInTheDocument();
    expect(card).toHaveTextContent("Heart care");
    expect(card).toHaveTextContent("Doctor count unavailable"); // honest, not "0 doctors"
    expect(screen.getByLabelText("Total Departments: unavailable")).toBeInTheDocument();
  });

  it("an unexpected render error shows a message with Try again, not a blank page", async () => {
    // A department whose name is not text makes the card throw while rendering.
    listDepartments.mockResolvedValue(page([{ ...EMPTY, name: { bad: true } }]));
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    renderPage();
    expect(await screen.findByRole("heading", { name: "Unable to load departments" })).toBeInTheDocument();
    expect(screen.getByText("Something went wrong while displaying this page.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Departments" })).toBeInTheDocument(); // header and filters stay
    listDepartments.mockResolvedValue(page([CARDIO]));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await rowOf("Cardiology")).toBeInTheDocument();
    spy.mockRestore();
  });
});
