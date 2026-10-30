import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { listInvitations, revokeAdminRole } from "../services/adminService";
import {
  activateUser,
  bulkSetUserStatus,
  createUser,
  deactivateUser,
  getUser,
  listRoles,
  listUsers,
  setUserRoles,
  updateUser,
} from "../services/userService";
import { authAs, PERMISSIONS } from "../test/fixtures";
import { presetRange } from "../utils/adminUsers";
import AdminUsers from "./AdminUsers";

vi.mock("../context/useAuth");
vi.mock("../services/userService");
vi.mock("../services/adminService");
vi.mock("../services/patientService");

const ADMIN = [...PERMISSIONS.admin, "admin_invitation:manage", "user:create", "user:update", "user:deactivate", "user:assign_role", "patient:create", "doctor:create"];
const ROLES = [
  { code: "patient", name: "Patient", description: null, permissions: [] },
  { code: "admin", name: "Administrator", description: null, permissions: [] },
  { code: "doctor", name: "Doctor", description: null, permissions: [] },
  { code: "receptionist", name: "Receptionist", description: null, permissions: [] },
];
const user = (id, name, roles, overrides = {}) => ({
  id,
  name,
  email: `${name.split(" ")[0].toLowerCase()}@clinic.example`,
  roles,
  is_active: true,
  created_at: "2027-04-20T09:00:00Z",
  phone: null,
  photo_url: null,
  doctor_id: null,
  patient_id: null,
  ...overrides,
});
const ME = user("u-1", "Ada Admin", ["admin"]);
const AYESHA = user("u-2", "Ayesha Malik", ["admin"]);
const AHMED = user("u-3", "Ahmed Raza", ["doctor"], { phone: "+1 555 987 6543", doctor_id: "d-1" });
const ROBERT = user("u-4", "Robert Brown", ["patient", "receptionist"], { is_active: false, patient_id: "p-1" });
const page = (items, total = items.length) => ({ data: { items, total, page: 1, page_size: 10, total_pages: Math.ceil(total / 10) } });

function renderPage(permissions = ADMIN) {
  const auth = authAs("Ada Admin", ["admin"], permissions);
  auth.user.id = "u-1";
  useAuth.mockReturnValue(auth);
  return render(
    <MemoryRouter initialEntries={["/admin/users"]}>
      <Routes>
        <Route path="/admin/users" element={<AdminUsers />} />
        <Route path="/admin/doctors" element={<p>Doctors page</p>} />
      </Routes>
    </MemoryRouter>
  );
}

const lastParams = () => listUsers.mock.calls.at(-1)[0];
const table = () => screen.getByRole("region", { name: "User accounts" });
const rowOf = async (name) => (await within(table()).findByText(name)).closest("tr");

beforeEach(() => {
  vi.resetAllMocks();
  listRoles.mockResolvedValue({ data: ROLES });
  listUsers.mockResolvedValue(page([ME, AYESHA, AHMED, ROBERT], 28));
  listInvitations.mockResolvedValue({ data: [] });
});

describe("Users list", () => {
  it("renders real rows: avatar, phone, coloured role badges, status, joined date", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Users" })).toBeInTheDocument();
    expect(screen.getByText("Manage all system users including doctors, receptionists and patients.")).toBeInTheDocument();
    const ahmed = await rowOf("Ahmed Raza");
    expect(ahmed).toHaveTextContent("+1 555 987 6543");
    expect(within(ahmed).getByText("Doctor")).toHaveClass("role-doctor");
    expect(ahmed).toHaveTextContent("Apr 20, 2027");
    const robert = await rowOf("Robert Brown");
    expect(within(robert).getByText("Patient")).toHaveClass("role-patient");
    expect(within(robert).getByText("Receptionist")).toHaveClass("role-receptionist"); // no role dropped
    expect(robert).toHaveTextContent("Inactive");
    expect(within(await rowOf("Ayesha Malik")).getByText("Admin")).toHaveClass("role-admin");
    expect(screen.getByText("Showing 1 to 10 of 28 users")).toBeInTheDocument();
    expect(lastParams()).toEqual({ page: 1, page_size: 10, sort: "name" });
  });

  it("searches after a pause, server-side", async () => {
    renderPage();
    await rowOf("Ahmed Raza");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search users by name, email or phone" }), { target: { value: "555" } });
    await waitFor(() => expect(lastParams()).toEqual(expect.objectContaining({ q: "555", page: 1 })));
  });

  it("role, status and date filters combine and reset to page 1", async () => {
    const u = userEvent.setup();
    renderPage();
    await rowOf("Ahmed Raza");
    await u.click(screen.getByRole("button", { name: "Page 2" }));
    await waitFor(() => expect(lastParams().page).toBe(2));
    await u.selectOptions(screen.getByLabelText("Role"), "receptionist");
    await u.selectOptions(screen.getByLabelText("Status"), "inactive");
    await u.selectOptions(screen.getByLabelText("Joined date"), "7d");
    const { from, to } = presetRange("7d");
    await waitFor(() =>
      expect(lastParams()).toEqual({ page: 1, page_size: 10, sort: "name", role: "receptionist", is_active: false, joined_from: from, joined_to: to })
    );
    // Administrator is listed as a role to filter by.
    expect(within(screen.getByLabelText("Role")).getByRole("option", { name: "Administrator" })).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(lastParams()).toEqual({ page: 1, page_size: 10, sort: "name" }));
  });

  it("sorts on the server, toggling direction", async () => {
    const u = userEvent.setup();
    renderPage();
    await rowOf("Ahmed Raza");
    await u.click(screen.getByRole("button", { name: /Joined On/ }));
    await waitFor(() => expect(lastParams().sort).toBe("created_at"));
    await u.click(screen.getByRole("button", { name: /Joined On/ }));
    await waitFor(() => expect(lastParams().sort).toBe("-created_at"));
    expect(screen.getByRole("columnheader", { name: /Joined On/ })).toHaveAttribute("aria-sort", "descending");
  });

  it("says when nothing matches and offers to clear", async () => {
    listUsers.mockResolvedValue(page([]));
    const u = userEvent.setup();
    renderPage();
    await screen.findByText("No users yet.");
    await u.selectOptions(screen.getByLabelText("Status"), "inactive");
    expect(await screen.findByText("No users match your search or filters.")).toBeInTheDocument();
  });

  it("explains a loading failure and retries", async () => {
    listUsers.mockRejectedValueOnce({ response: { data: { error: { message: "Service unavailable" } } } });
    const u = userEvent.setup();
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await u.click(screen.getByRole("button", { name: "Try again" }));
    expect(await rowOf("Ahmed Raza")).toBeInTheDocument();
  });
});

describe("Row actions", () => {
  it("offers only what is allowed; never on yourself", async () => {
    const u = userEvent.setup();
    renderPage();
    await u.click(within(await rowOf("Ayesha Malik")).getByRole("button", { name: "Actions for Ayesha Malik" }));
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual([
      "View User",
      "Edit User",
      "Manage Roles",
      "Deactivate User",
      "Remove Administrator Role",
    ]);
    await u.keyboard("{Escape}");
    await u.click(within(await rowOf("Ada Admin")).getByRole("button", { name: "Actions for Ada Admin" }));
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["View User", "Edit User", "Manage Roles"]);
    expect(within(await rowOf("Ada Admin")).queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("a viewer without management permissions only views", async () => {
    const u = userEvent.setup();
    renderPage(["user:read"]);
    await u.click(within(await rowOf("Ahmed Raza")).getByRole("button", { name: "Actions for Ahmed Raza" }));
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["View User", "Open Doctor Profile"]);
    expect(screen.queryByRole("button", { name: /Add User/ })).not.toBeInTheDocument();
  });

  it("View User shows the account and its linked profile", async () => {
    const u = userEvent.setup();
    getUser.mockResolvedValue({ data: AHMED });
    renderPage();
    await u.click(within(await rowOf("Ahmed Raza")).getByRole("button", { name: "Ahmed Raza" }));
    const dialog = screen.getByRole("dialog", { name: "User details" });
    expect(dialog).toHaveTextContent("ahmed@clinic.example");
    expect(dialog).toHaveTextContent("+1 555 987 6543");
    expect(within(dialog).getByRole("link", { name: "Open doctor profile" })).toHaveAttribute("href", "/doctors/d-1");
    expect(getUser).toHaveBeenCalledWith("u-3");
  });

  it("Edit User validates and saves name and email only", async () => {
    const u = userEvent.setup();
    updateUser.mockResolvedValue({ data: { ...AHMED, name: "Ahmed R." } });
    renderPage();
    await u.click(within(await rowOf("Ahmed Raza")).getByRole("button", { name: "Actions for Ahmed Raza" }));
    await u.click(screen.getByRole("menuitem", { name: "Edit User" }));
    const dialog = screen.getByRole("dialog", { name: "Edit user" });
    await u.clear(within(dialog).getByLabelText("Full name"));
    await u.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(within(dialog).getByText("Enter the full name.")).toBeInTheDocument();
    await u.type(within(dialog).getByLabelText("Full name"), "Ahmed R.");
    await u.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(updateUser).toHaveBeenCalledWith("u-3", { name: "Ahmed R.", email: "ahmed@clinic.example" });
    expect(await screen.findByText("Saved Ahmed R..")).toBeInTheDocument();
  });

  it("Manage Roles never offers Administrator and keeps an admin's admin role", async () => {
    const u = userEvent.setup();
    setUserRoles.mockResolvedValue({ data: AYESHA });
    renderPage();
    await u.click(within(await rowOf("Ayesha Malik")).getByRole("button", { name: "Actions for Ayesha Malik" }));
    await u.click(screen.getByRole("menuitem", { name: "Manage Roles" }));
    const dialog = screen.getByRole("dialog", { name: "Manage roles: Ayesha Malik" });
    expect(within(dialog).queryByLabelText("Administrator")).not.toBeInTheDocument();
    await u.click(within(dialog).getByLabelText("Receptionist"));
    await u.click(within(dialog).getByRole("button", { name: "Save roles" }));
    expect(setUserRoles).toHaveBeenCalledWith("u-2", ["admin", "receptionist"]);
  });

  it("deactivating asks first, then refreshes", async () => {
    const u = userEvent.setup();
    deactivateUser.mockResolvedValue({ data: {} });
    renderPage();
    await u.click(within(await rowOf("Ahmed Raza")).getByRole("button", { name: "Actions for Ahmed Raza" }));
    await u.click(screen.getByRole("menuitem", { name: "Deactivate User" }));
    expect(deactivateUser).not.toHaveBeenCalled();
    await u.click(within(screen.getByRole("dialog", { name: "Deactivate user?" })).getByRole("button", { name: "Deactivate" }));
    expect(deactivateUser).toHaveBeenCalledWith("u-3");
    expect(await screen.findByText("Ahmed Raza is now inactive.")).toBeInTheDocument();
    await waitFor(() => expect(listUsers).toHaveBeenCalledTimes(2));
  });

  it("a refusal (e.g. last administrator) is shown in the dialog", async () => {
    const u = userEvent.setup();
    activateUser.mockRejectedValue({ response: { data: { error: { message: "Cannot do that" } } } });
    renderPage();
    await u.click(within(await rowOf("Robert Brown")).getByRole("button", { name: "Actions for Robert Brown" }));
    await u.click(screen.getByRole("menuitem", { name: "Activate User" }));
    const dialog = screen.getByRole("dialog", { name: "Activate user?" });
    await u.click(within(dialog).getByRole("button", { name: "Activate" }));
    expect(await within(dialog).findByText("Cannot do that")).toBeInTheDocument();
  });

  it("removing an administrator role needs your password", async () => {
    const u = userEvent.setup();
    revokeAdminRole.mockResolvedValue({ data: null });
    renderPage();
    await u.click(within(await rowOf("Ayesha Malik")).getByRole("button", { name: "Actions for Ayesha Malik" }));
    await u.click(screen.getByRole("menuitem", { name: "Remove Administrator Role" }));
    const dialog = screen.getByRole("dialog", { name: "Remove administrator role?" });
    await u.type(within(dialog).getByLabelText("Your password"), "secret");
    await u.click(within(dialog).getByRole("button", { name: "Remove role" }));
    expect(revokeAdminRole).toHaveBeenCalledWith("u-2", "secret");
    expect(await screen.findByText("Ayesha Malik is no longer an administrator.")).toBeInTheDocument();
  });
});

describe("Bulk selection", () => {
  it("selects the page (except yourself) and reports partial failures", async () => {
    const u = userEvent.setup();
    bulkSetUserStatus.mockResolvedValue({
      data: [
        { user_id: "u-2", ok: false, code: "LAST_ADMIN", message: "Cannot deactivate the last active administrator" },
        { user_id: "u-3", ok: true },
        { user_id: "u-4", ok: true },
      ],
    });
    renderPage();
    await rowOf("Ahmed Raza");
    await u.click(screen.getByRole("checkbox", { name: "Select all users on this page" }));
    expect(screen.getByText("3 users selected")).toBeInTheDocument();
    await u.click(screen.getByRole("checkbox", { name: "Select Robert Brown" }));
    expect(screen.getByText("2 users selected")).toBeInTheDocument();
    await u.click(screen.getByRole("checkbox", { name: "Select Robert Brown" }));
    await u.click(screen.getByRole("button", { name: "Deactivate" }));
    expect(bulkSetUserStatus).not.toHaveBeenCalled();
    await u.click(within(screen.getByRole("dialog", { name: "Deactivate selected users?" })).getByRole("button", { name: "Deactivate" }));
    expect(bulkSetUserStatus).toHaveBeenCalledWith(["u-2", "u-3", "u-4"], false);
    expect(await screen.findByText(/2 users deactivated\. 1 could not be changed/)).toBeInTheDocument();
    expect(screen.getByText("Ayesha Malik: Cannot deactivate the last active administrator")).toBeInTheDocument();
  });
});

describe("Add User", () => {
  it("creates a receptionist with validation", async () => {
    const u = userEvent.setup();
    createUser.mockResolvedValue({ data: user("u-9", "Emily Carter", ["receptionist"]) });
    renderPage();
    await u.click(await screen.findByRole("button", { name: /Add User/ }));
    const dialog = screen.getByRole("dialog", { name: "Add User" });
    expect(within(within(dialog).getByLabelText("Role")).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Receptionist",
      "Patient",
      "Doctor",
      "Administrator",
    ]);
    await u.click(within(dialog).getByRole("button", { name: "Create user" }));
    expect(within(dialog).getByText("Enter the full name.")).toBeInTheDocument();
    expect(createUser).not.toHaveBeenCalled();
    await u.type(within(dialog).getByLabelText("Full name"), "Emily Carter");
    await u.type(within(dialog).getByLabelText("Email"), "emily@clinic.example");
    await u.type(within(dialog).getByLabelText("Temporary password"), "Temp-pass-123");
    await u.type(within(dialog).getByLabelText("Confirm password"), "Temp-pass-123");
    await u.click(within(dialog).getByRole("button", { name: "Create user" }));
    expect(createUser).toHaveBeenCalledWith({ name: "Emily Carter", email: "emily@clinic.example", password: "Temp-pass-123", roles: ["receptionist"] });
    expect(await screen.findByText("Created Emily Carter (emily@clinic.example).")).toBeInTheDocument();
  });

  it("Administrator opens the invitation, never a password form", async () => {
    const u = userEvent.setup();
    renderPage();
    await u.click(await screen.findByRole("button", { name: /Add User/ }));
    const dialog = screen.getByRole("dialog", { name: "Add User" });
    await u.selectOptions(within(dialog).getByLabelText("Role"), "admin");
    expect(within(dialog).queryByLabelText("Temporary password")).not.toBeInTheDocument();
    await u.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("dialog", { name: "Invite Administrator" })).toBeInTheDocument();
  });

  it("Doctor goes to the doctor workflow", async () => {
    const u = userEvent.setup();
    renderPage();
    await u.click(await screen.findByRole("button", { name: /Add User/ }));
    const dialog = screen.getByRole("dialog", { name: "Add User" });
    await u.selectOptions(within(dialog).getByLabelText("Role"), "doctor");
    await u.click(within(dialog).getByRole("button", { name: "Go to Doctors" }));
    expect(screen.getByText("Doctors page")).toBeInTheDocument();
  });

  it("Patient opens the patient registration form", async () => {
    const u = userEvent.setup();
    renderPage();
    await u.click(await screen.findByRole("button", { name: /Add User/ }));
    await u.selectOptions(within(screen.getByRole("dialog", { name: "Add User" })).getByLabelText("Role"), "patient");
    await u.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByLabelText(/First name/)).toBeInTheDocument();
  });

  it("invitations are shown only to those who may invite", async () => {
    renderPage(["user:read", "user:create"]);
    await rowOf("Ahmed Raza");
    expect(screen.queryByRole("region", { name: "Administrator invitations" })).not.toBeInTheDocument();
    expect(listInvitations).not.toHaveBeenCalled();
  });
});
