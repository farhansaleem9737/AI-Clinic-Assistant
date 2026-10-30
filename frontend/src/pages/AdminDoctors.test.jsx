import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { getPublicDepartments, listDepartments } from "../services/departmentService";
import {
  approveApplication,
  getApplication,
  getApplicationDocumentLink,
  listApplications,
  rejectApplication,
} from "../services/doctorApplicationService";
import {
  activateDoctor,
  createDoctor,
  deactivateDoctor,
  getDoctor,
  getDoctorCareer,
  listAllSpecializations,
  listDoctors,
  updateDoctor,
} from "../services/doctorService";
import { authAs, PERMISSIONS } from "../test/fixtures";
import AdminDoctors from "./AdminDoctors";

vi.mock("../context/useAuth");
vi.mock("../services/departmentService");
vi.mock("../services/doctorService");
vi.mock("../services/doctorApplicationService", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    listApplications: vi.fn(),
    getApplication: vi.fn(),
    getApplicationDocumentLink: vi.fn(),
    approveApplication: vi.fn(),
    rejectApplication: vi.fn(),
  };
});

const ADMIN = [...PERMISSIONS.admin, "doctor:read", "doctor:create", "doctor:update", "doctor:deactivate", "schedule:manage_any", "department:manage", "doctor_application:review"];
const doctor = (id, name, overrides = {}) => ({
  id,
  name,
  title: "Dr.",
  email: `${name.split(" ")[0].toLowerCase()}@clinic.example`,
  department_id: "dep-1",
  department_name: "Cardiology",
  specialization: "Cardiologist",
  years_of_experience: 10,
  is_active: true,
  photo_url: null,
  phone: null,
  license_number: null,
  qualifications: null,
  languages: null,
  consultation_fee: null,
  room_number: null,
  bio: null,
  is_verified: false,
  ...overrides,
});
const SARAH = doctor("d-1", "Sarah Khan");
const MICHAEL = doctor("d-2", "Michael Brown", { department_id: "dep-2", department_name: "Orthopedics", specialization: "Orthopedic Surgeon", years_of_experience: 15, is_active: false });
const page = (items, total = items.length) => ({ data: { items, total, page: 1, page_size: 10, total_pages: Math.max(1, Math.ceil(total / 10)) } });
const APPLICATION = {
  id: "app-1",
  status: "pending_review",
  name: "Lisa Chen",
  email: "lisa@clinic.example",
  license_number: "PMDC-1",
  registration_authority: null,
  specialization: "Pediatrician",
  department_id: "dep-3",
  department_name: "Pediatrics",
  years_of_experience: 6,
  qualifications: "MBBS",
  institution: null,
  bio: null,
  consultation_fee: null,
  languages: null,
  phone: null,
  submitted_at: "2027-04-20T09:00:00Z",
  reviewed_at: null,
  review_notes: null,
  doctor_id: null,
  documents: [{ id: "doc-1", document_type: "degree_certificate", filename: "degree.pdf", content_type: "application/pdf", size_bytes: 1000, uploaded_at: "2027-04-20T09:00:00Z" }],
  missing_for_approval: [],
};

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderPage(permissions = ADMIN, entry = "/admin/doctors") {
  useAuth.mockReturnValue(authAs("Ada Admin", ["admin"], permissions));
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/admin/doctors" element={<AdminDoctors />} />
        <Route path="/schedule" element={<p>Schedule page</p>} />
      </Routes>
      <Where />
    </MemoryRouter>
  );
}
const lastParams = () => listDoctors.mock.calls.at(-1)[0];
const rowOf = async (name) => (await screen.findByRole("button", { name })).closest("tr");

beforeEach(() => {
  vi.resetAllMocks();
  listDoctors.mockResolvedValue(page([SARAH, MICHAEL], 23));
  listDepartments.mockResolvedValue({ data: { items: [{ id: "dep-1", name: "Cardiology", is_active: true }, { id: "dep-2", name: "Orthopedics", is_active: false }] } });
  getPublicDepartments.mockResolvedValue({ data: { items: [{ id: "dep-1", name: "Cardiology" }, { id: "dep-3", name: "Pediatrics" }] } });
  listAllSpecializations.mockResolvedValue({ data: ["Cardiologist", "Orthopedic Surgeon"] });
  listApplications.mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 50 } });
});

describe("Doctors list", () => {
  it("renders real rows with email, department, specialization, experience and status", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Doctors" })).toBeInTheDocument();
    expect(screen.getByText("Manage clinic doctors, their details and schedules.")).toBeInTheDocument();
    const sarah = await rowOf("Dr. Sarah Khan");
    for (const text of ["sarah@clinic.example", "Cardiology", "Cardiologist", "10 years", "Active"]) expect(sarah).toHaveTextContent(text);
    const michael = await rowOf("Dr. Michael Brown");
    expect(michael).toHaveTextContent("15 years");
    expect(michael).toHaveTextContent("Inactive");
    expect(screen.getByText("Showing 1 to 10 of 23 doctors")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Page 3" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Page 4" })).not.toBeInTheDocument();
  });

  it("filters (inactive departments included) combine with search and reset to page 1", async () => {
    const u = userEvent.setup();
    renderPage();
    await rowOf("Dr. Sarah Khan");
    expect(within(screen.getByLabelText("Department")).getByRole("option", { name: "Orthopedics (inactive)" })).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Page 2" }));
    await u.selectOptions(screen.getByLabelText("Department"), "dep-1");
    await u.selectOptions(screen.getByLabelText("Specialization"), "Cardiologist");
    await u.selectOptions(screen.getByLabelText("Status"), "active");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search doctors by name, email or phone" }), { target: { value: "0300" } });
    await waitFor(() =>
      expect(lastParams()).toEqual({ page: 1, page_size: 10, sort: "name_asc", q: "0300", department_id: "dep-1", specialization: "Cardiologist", is_active: true })
    );
    await u.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(lastParams()).toEqual({ page: 1, page_size: 10, sort: "name_asc" }));
  });

  it("a department link from Departments preselects the filter", async () => {
    renderPage(ADMIN, "/admin/doctors?department=dep-1");
    await rowOf("Dr. Sarah Khan");
    expect(listDoctors.mock.calls[0][0]).toEqual(expect.objectContaining({ department_id: "dep-1" }));
  });

  it("sorts every column on the server", async () => {
    const u = userEvent.setup();
    renderPage();
    await rowOf("Dr. Sarah Khan");
    await u.click(screen.getByRole("button", { name: /^Experience/ }));
    await waitFor(() => expect(lastParams().sort).toBe("experience_asc"));
    await u.click(screen.getByRole("button", { name: /^Experience/ }));
    await waitFor(() => expect(lastParams().sort).toBe("experience_desc"));
    await u.click(screen.getByRole("button", { name: /^Department/ }));
    await waitFor(() => expect(lastParams().sort).toBe("department_asc"));
    expect(screen.getByRole("columnheader", { name: /Department/ })).toHaveAttribute("aria-sort", "ascending");
  });

  it("empty, no-match and error states", async () => {
    listDoctors.mockResolvedValue(page([]));
    const u = userEvent.setup();
    renderPage();
    expect(await screen.findByText(/No doctors yet/)).toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText("Status"), "inactive");
    expect(await screen.findByText("No doctors match your search or filters.")).toBeInTheDocument();
  });

  it("explains a loading failure and retries", async () => {
    listDoctors.mockRejectedValueOnce({ response: { data: { error: { message: "Service unavailable" } } } });
    const u = userEvent.setup();
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await u.click(screen.getByRole("button", { name: "Try again" }));
    expect(await rowOf("Dr. Sarah Khan")).toBeInTheDocument();
  });
});

describe("Actions", () => {
  it("the menu offers only what the permissions allow", async () => {
    const u = userEvent.setup();
    renderPage();
    await u.click(within(await rowOf("Dr. Sarah Khan")).getByRole("button", { name: "Actions for Dr. Sarah Khan" }));
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "View Profile",
      "Edit Doctor",
      "Manage Schedule",
      "Manage Department",
      "Deactivate Doctor",
    ]);
  });

  it("a read-only viewer only views", async () => {
    const u = userEvent.setup();
    renderPage(["doctor:read"]);
    await u.click(within(await rowOf("Dr. Sarah Khan")).getByRole("button", { name: "Actions for Dr. Sarah Khan" }));
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["View Profile"]);
    expect(screen.queryByRole("button", { name: /Add Doctor/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Doctor applications" })).not.toBeInTheDocument();
  });

  it("Manage Schedule opens the schedule for that doctor", async () => {
    const u = userEvent.setup();
    renderPage();
    await u.click(within(await rowOf("Dr. Sarah Khan")).getByRole("button", { name: "Actions for Dr. Sarah Khan" }));
    await u.click(screen.getByRole("menuitem", { name: "Manage Schedule" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/schedule?doctor=d-1");
  });

  it("View Profile shows the record and career", async () => {
    const u = userEvent.setup();
    getDoctor.mockResolvedValue({ data: { ...SARAH, license_number: "PMDC-9", upcoming_appointments: 2 } });
    getDoctorCareer.mockResolvedValue({ data: { experience: [{ title: "Consultant", organization: "City Hospital", start_year: 2015, end_year: null }], education: [] } });
    renderPage();
    await u.click(await screen.findByRole("button", { name: "Dr. Sarah Khan" }));
    const dialog = screen.getByRole("dialog", { name: "Doctor profile" });
    expect(await within(dialog).findByText("PMDC-9")).toBeInTheDocument();
    expect(await within(dialog).findByText("Consultant")).toBeInTheDocument();
    expect(dialog).toHaveTextContent("2 appointments");
    expect(within(dialog).getByRole("link", { name: "Open public profile" })).toHaveAttribute("href", "/doctors/d-1");
  });

  it("Edit Doctor validates and saves professional details", async () => {
    const u = userEvent.setup();
    updateDoctor.mockResolvedValue({ data: { ...SARAH, years_of_experience: 12 } });
    renderPage();
    await u.click(within(await rowOf("Dr. Sarah Khan")).getByRole("button", { name: "Actions for Dr. Sarah Khan" }));
    await u.click(screen.getByRole("menuitem", { name: "Edit Doctor" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Dr. Sarah Khan" });
    expect(within(dialog).queryByLabelText("Email")).not.toBeInTheDocument();
    await u.clear(within(dialog).getByLabelText("Years of experience"));
    await u.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(within(dialog).getByText("Enter whole years between 0 and 80.")).toBeInTheDocument();
    await u.type(within(dialog).getByLabelText("Years of experience"), "12");
    await u.type(within(dialog).getByLabelText("Phone (internal)"), "abc");
    await u.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(within(dialog).getByText("Enter a valid phone number.")).toBeInTheDocument();
    await u.clear(within(dialog).getByLabelText("Phone (internal)"));
    await u.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(updateDoctor).toHaveBeenCalledWith("d-1", expect.objectContaining({ years_of_experience: 12, specialization: "Cardiologist", department_id: "dep-1", phone: null }));
    expect(await screen.findByText("Saved Dr. Sarah Khan.")).toBeInTheDocument();
  });

  it("Manage Department offers only active departments", async () => {
    const u = userEvent.setup();
    updateDoctor.mockResolvedValue({ data: { ...SARAH, department_id: "dep-3", department_name: "Pediatrics" } });
    renderPage();
    await u.click(within(await rowOf("Dr. Sarah Khan")).getByRole("button", { name: "Actions for Dr. Sarah Khan" }));
    await u.click(screen.getByRole("menuitem", { name: "Manage Department" }));
    const dialog = screen.getByRole("dialog", { name: "Manage department" });
    expect(within(within(dialog).getByLabelText("Department")).getAllByRole("option").map((o) => o.textContent)).toEqual(["Cardiology", "Pediatrics"]);
    await u.selectOptions(within(dialog).getByLabelText("Department"), "dep-3");
    await u.click(within(dialog).getByRole("button", { name: "Save department" }));
    expect(updateDoctor).toHaveBeenCalledWith("d-1", { department_id: "dep-3" });
    expect(await screen.findByText("Dr. Sarah Khan moved to Pediatrics.")).toBeInTheDocument();
  });

  it("deactivation is held back while upcoming appointments exist", async () => {
    const u = userEvent.setup();
    getDoctor.mockResolvedValue({ data: { ...SARAH, upcoming_appointments: 3 } });
    renderPage();
    await u.click(within(await rowOf("Dr. Sarah Khan")).getByRole("button", { name: "Actions for Dr. Sarah Khan" }));
    await u.click(screen.getByRole("menuitem", { name: "Deactivate Doctor" }));
    const dialog = screen.getByRole("dialog", { name: "Deactivate doctor?" });
    expect(await within(dialog).findByText(/3 upcoming appointments/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Deactivate|Please wait/ })).toBeDisabled();
    expect(deactivateDoctor).not.toHaveBeenCalled();
  });

  it("deactivates after confirming when nothing is booked; activates another", async () => {
    const u = userEvent.setup();
    getDoctor.mockResolvedValue({ data: { ...SARAH, upcoming_appointments: 0 } });
    deactivateDoctor.mockResolvedValue({ data: {} });
    activateDoctor.mockResolvedValue({ data: {} });
    renderPage();
    await u.click(within(await rowOf("Dr. Sarah Khan")).getByRole("button", { name: "Actions for Dr. Sarah Khan" }));
    await u.click(screen.getByRole("menuitem", { name: "Deactivate Doctor" }));
    const dialog = screen.getByRole("dialog", { name: "Deactivate doctor?" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Deactivate" })).toBeEnabled());
    await u.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    expect(deactivateDoctor).toHaveBeenCalledWith("d-1");
    expect(await screen.findByText("Dr. Sarah Khan is now inactive.")).toBeInTheDocument();

    await u.click(within(await rowOf("Dr. Michael Brown")).getByRole("button", { name: "Actions for Dr. Michael Brown" }));
    await u.click(screen.getByRole("menuitem", { name: "Activate Doctor" }));
    await u.click(within(screen.getByRole("dialog", { name: "Activate doctor?" })).getByRole("button", { name: "Activate" }));
    expect(activateDoctor).toHaveBeenCalledWith("d-2");
  });
});

describe("Add Doctor", () => {
  it("validates, creates the account and profile together, and reports duplicates", async () => {
    const u = userEvent.setup();
    createDoctor.mockRejectedValueOnce({ response: { data: { error: { code: "EMAIL_TAKEN", message: "Email already registered" } } } });
    createDoctor.mockResolvedValueOnce({ data: doctor("d-9", "Emily Carter") });
    renderPage();
    await u.click(screen.getByRole("button", { name: /Add Doctor/ }));
    const dialog = screen.getByRole("dialog", { name: "Add Doctor" });
    await u.click(within(dialog).getByRole("button", { name: "Add Doctor" }));
    for (const message of ["Enter the doctor's full name.", "Enter a valid email address.", "Use at least 8 characters.", "Enter the specialization.", "Choose a department."])
      expect(within(dialog).getByText(message)).toBeInTheDocument();
    await u.type(within(dialog).getByLabelText("Full name"), "Emily Carter");
    await u.type(within(dialog).getByLabelText("Email"), "emily@clinic.example");
    await u.type(within(dialog).getByLabelText("Temporary password"), "Temp-pass-123");
    await u.type(within(dialog).getByLabelText("Confirm password"), "Temp-pass-123");
    await u.type(within(dialog).getByLabelText("Specialization"), "Dermatologist");
    await u.selectOptions(within(dialog).getByLabelText("Department"), "dep-1");
    await u.type(within(dialog).getByLabelText("Consultation fee"), "2500");
    await u.click(within(dialog).getByRole("button", { name: "Add Doctor" }));
    expect(await within(dialog).findByText("An account with this email already exists.")).toBeInTheDocument();
    await u.click(within(dialog).getByRole("button", { name: "Add Doctor" }));
    expect(createDoctor).toHaveBeenLastCalledWith(
      expect.objectContaining({
        account: { name: "Emily Carter", email: "emily@clinic.example", password: "Temp-pass-123" },
        specialization: "Dermatologist",
        department_id: "dep-1",
        consultation_fee: "2500",
        years_of_experience: 0,
      })
    );
    expect(await screen.findByText("Added Dr. Emily Carter.")).toBeInTheDocument();
  });
});

describe("Doctor applications", () => {
  beforeEach(() => {
    listApplications.mockResolvedValue({
      data: { items: [{ id: "app-1", status: "pending_review", name: "Lisa Chen", email: "lisa@clinic.example", specialization: "Pediatrician", department_name: "Pediatrics", document_count: 1, submitted_at: "2027-04-20T09:00:00Z" }], total: 1, page: 1, page_size: 50 },
    });
    getApplication.mockResolvedValue({ data: APPLICATION });
  });

  it("lists pending applications, separate from doctors", async () => {
    renderPage();
    const panel = await screen.findByRole("region", { name: "Doctor applications" });
    expect(await within(panel).findByText("Lisa Chen")).toBeInTheDocument();
    expect(within(panel).getByRole("heading")).toHaveTextContent("(1 pending)");
    expect(listApplications).toHaveBeenCalledWith({ status: "pending_review", page_size: 50 });
    expect(within(screen.getByRole("region", { name: "Doctors list" })).queryByText("Lisa Chen")).not.toBeInTheDocument();
  });

  it("opens documents through short-lived links, then approves", async () => {
    const u = userEvent.setup();
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    getApplicationDocumentLink.mockResolvedValue({ data: { url: "https://signed.example/doc", expires_at: "2027-04-20T09:05:00Z" } });
    approveApplication.mockResolvedValue({ data: { ...APPLICATION, status: "approved" } });
    renderPage();
    await u.click(await screen.findByRole("button", { name: "Review application from Lisa Chen" }));
    const dialog = screen.getByRole("dialog", { name: "Doctor application" });
    await u.click(await within(dialog).findByRole("button", { name: "Open" }));
    expect(getApplicationDocumentLink).toHaveBeenCalledWith("app-1", "doc-1");
    expect(open).toHaveBeenCalledWith("https://signed.example/doc", "_blank", "noopener,noreferrer");
    await u.click(within(dialog).getByRole("button", { name: "Approve…" }));
    const confirm = screen.getByRole("dialog", { name: "Approve Lisa Chen?" });
    await u.type(within(confirm).getByLabelText("Notes (optional)"), "Verified PMDC");
    await u.click(within(confirm).getByRole("button", { name: "Approve" }));
    expect(approveApplication).toHaveBeenCalledWith("app-1", "Verified PMDC");
    expect(await screen.findByText("Lisa Chen was approved and is now a doctor.")).toBeInTheDocument();
    open.mockRestore();
  });

  it("rejecting needs a reason; a refusal is shown", async () => {
    const u = userEvent.setup();
    rejectApplication.mockRejectedValue({ response: { data: { error: { message: "Already reviewed" } } } });
    renderPage();
    await u.click(await screen.findByRole("button", { name: "Review application from Lisa Chen" }));
    await u.click(await within(screen.getByRole("dialog", { name: "Doctor application" })).findByRole("button", { name: "Reject…" }));
    const confirm = screen.getByRole("dialog", { name: "Reject Lisa Chen?" });
    await u.click(within(confirm).getByRole("button", { name: "Reject application" }));
    expect(within(confirm).getByText("Give the applicant a reason.")).toBeInTheDocument();
    expect(rejectApplication).not.toHaveBeenCalled();
    await u.type(within(confirm).getByLabelText("Reason"), "License could not be verified");
    await u.click(within(confirm).getByRole("button", { name: "Reject application" }));
    expect(rejectApplication).toHaveBeenCalledWith("app-1", "License could not be verified");
    expect(await within(confirm).findByText("Already reviewed")).toBeInTheDocument();
  });
});
