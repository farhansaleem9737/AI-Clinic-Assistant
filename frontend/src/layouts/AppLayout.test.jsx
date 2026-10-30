import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProtectedRoute from "../components/ProtectedRoute";
import { useAuth } from "../context/useAuth";
import { getUnreadCount, globalSearch, listNotifications, markNotificationRead } from "../services/workspaceService";
import { authAs, PERMISSIONS } from "../test/fixtures";
import { ADMIN_PERMISSIONS } from "../routes/navigation";
import AppLayout from "./AppLayout";

vi.mock("../context/useAuth");
vi.mock("../services/workspaceService");

const ADMIN = [...PERMISSIONS.admin, "settings:manage"];

beforeEach(() => {
  vi.resetAllMocks();
  getUnreadCount.mockResolvedValue({ data: { unread: 0 } });
});

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderShell(auth, initial = "/dashboard") {
  useAuth.mockReturnValue(auth);
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route
            path="/admin"
            element={
              <ProtectedRoute allOf={ADMIN_PERMISSIONS}>
                <p>Admin dashboard</p>
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/users"
            element={
              <ProtectedRoute permission="user:read">
                <p>Users page</p>
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Where />} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

const menu = () => within(screen.getByRole("navigation")).getAllByRole("link").map((a) => a.textContent);

describe("sidebar navigation is role-aware", () => {
  it("patient", () => {
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    expect(menu()).toEqual(["Dashboard", "Appointments", "Doctors", "Departments", "My Profile"]);
  });

  it("doctor", () => {
    renderShell(authAs("Sarah Khan", ["doctor"], PERMISSIONS.doctor));
    expect(menu()).toEqual(["Dashboard", "Appointments", "Schedule", "Doctors", "Departments", "My Profile"]);
  });

  it("receptionist", () => {
    renderShell(authAs("Rita", ["receptionist"], PERMISSIONS.receptionist));
    expect(menu()).toEqual([
      "Dashboard", "Appointments", "Book appointment", "Doctors / Schedules", "Departments", "Patients", "Manage doctors",
    ]);
  });

  it("admin: the administrator's own sidebar, with Settings and Logout at the bottom", () => {
    renderShell(authAs("Ada", ["admin"], ADMIN));
    expect(menu()).toEqual(["Dashboard", "Users", "Departments", "Doctors", "Patients", "Appointments", "Profile"]);
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/admin");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/admin/settings");
    expect(screen.getByRole("button", { name: "Logout" })).toBeInTheDocument();
  });

  it("anonymous visitors see only the public pages and the sign-in actions", () => {
    renderShell({ user: null, initializing: false, can: () => false, logout: async () => {} }, "/doctors");
    expect(menu()).toEqual(["Doctors", "Departments"]);
    expect(screen.getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("button", { name: "Logout" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Help/ })).not.toBeInTheDocument();
  });
});

describe("shell behaviour", () => {
  it("shows the signed-in user and their role, opening the account menu", async () => {
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    const me = screen.getByRole("button", { name: /John Doe, Patient: account menu/ });
    expect(me).toHaveTextContent("John Doe");
    expect(me).toHaveTextContent("Patient");
    await userEvent.click(me);
    const menu = screen.getByRole("menu", { name: "Account" });
    expect(within(menu).getByRole("menuitem", { name: "View Profile" })).toHaveAttribute("href", "/profile");
    expect(within(menu).queryByRole("menuitem", { name: "Settings" })).not.toBeInTheDocument();
  });

  it("administrators' account menu has their profile and Settings", async () => {
    renderShell(authAs("Ada", ["admin"], ADMIN));
    await userEvent.click(screen.getByRole("button", { name: /Ada, Administrator: account menu/ }));
    expect(screen.getByRole("menuitem", { name: "View Profile" })).toHaveAttribute("href", "/account");
    expect(screen.getByRole("menuitem", { name: "Settings" })).toHaveAttribute("href", "/admin/settings");
  });

  it("shows a doctor with the illustrated doctor avatar", () => {
    const { container } = renderShell(authAs("Sarah Khan", ["doctor"], PERMISSIONS.doctor));
    expect(container.querySelector('.topbar [data-avatar="doctor"]')).not.toBeNull();
  });

  it("offers Help & Support next to Logout", () => {
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    expect(screen.getByRole("link", { name: "Help & Support" })).toHaveAttribute("href", "/help");
  });

  it("the bell shows the real unread count and opens the notifications", async () => {
    getUnreadCount.mockResolvedValue({ data: { unread: 2 } });
    const note = { id: "n-1", type: "appointment_booked", title: "New appointment", message: "An appointment was booked.", link: "/appointments/a-1", read_at: null, created_at: "2027-04-23T05:00:00Z" };
    listNotifications.mockResolvedValue({ data: { items: [note], unread: 2 } });
    markNotificationRead.mockResolvedValue({ data: { ...note, read_at: "2027-04-23T06:00:00Z" } });
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    const bell = await screen.findByRole("button", { name: "Notifications, 2 unread" });
    await userEvent.click(bell);
    const panel = screen.getByRole("dialog", { name: "Notifications" });
    await userEvent.click(await within(panel).findByRole("button", { name: /New appointment/ }));
    expect(markNotificationRead).toHaveBeenCalledWith("n-1");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/appointments/a-1"));
  });

  it("the bell says when there is nothing", async () => {
    listNotifications.mockResolvedValue({ data: { items: [], unread: 0 } });
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    await userEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("You have no notifications.")).toBeInTheDocument();
  });

  it("signed-in search looks across records and opens the chosen one", async () => {
    globalSearch.mockResolvedValue({
      data: {
        query: "khan",
        patients: [{ id: "p-1", name: "Ali Khan", mrn: "MRN00000001" }],
        doctors: [{ id: "d-1", name: "Dr. Sarah Khan", specialization: "Cardiologist" }],
        appointments: [],
        users: null,
      },
    });
    renderShell(authAs("Rita", ["receptionist"], PERMISSIONS.receptionist));
    const box = screen.getByRole("combobox", { name: /Search patients, doctors/ });
    await userEvent.type(box, "khan");
    const results = await screen.findByRole("listbox", { name: "Search results" });
    expect((await within(results).findAllByRole("option")).map((o) => o.getAttribute("aria-label"))).toEqual([
      "Patients: Ali Khan, MRN00000001",
      "Doctors: Dr. Sarah Khan, Cardiologist",
    ]);
    expect(globalSearch).toHaveBeenCalledTimes(1);
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent("/doctors/d-1");
  });

  it("one letter does not search", async () => {
    renderShell(authAs("Rita", ["receptionist"], PERMISSIONS.receptionist));
    await userEvent.type(screen.getByRole("combobox", { name: /Search patients, doctors/ }), "k");
    expect(globalSearch).not.toHaveBeenCalled();
  });

  it("visitors still search the doctor directory", async () => {
    renderShell({ user: null, initializing: false, can: () => false, logout: async () => {} }, "/doctors");
    await userEvent.type(screen.getByRole("searchbox", { name: "Search doctors" }), "cardio{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent("/doctors?q=cardio");
  });

  it("logging out calls the session logout and returns to the login page", async () => {
    const auth = authAs("John Doe", ["patient"], PERMISSIONS.patient);
    auth.logout = vi.fn().mockResolvedValue();
    renderShell(auth);
    await userEvent.click(screen.getByRole("button", { name: "Logout" }));
    expect(auth.logout).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/login"));
  });
});

describe("unauthorized access", () => {
  it("a page the user lacks permission for sends them back to the dashboard", () => {
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient), "/admin/users");
    expect(screen.queryByText("Users page")).not.toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/dashboard");
  });

  it("a signed-out visitor is sent to the login page", () => {
    renderShell({ user: null, initializing: false, can: () => false, logout: async () => {} }, "/admin/users");
    expect(screen.getByTestId("where")).toHaveTextContent("/login");
  });

  it("the permitted user sees the page", () => {
    renderShell(authAs("Ada", ["admin"], PERMISSIONS.admin), "/admin/users");
    expect(screen.getByText("Users page")).toBeInTheDocument();
  });

  it("/admin: visitors go to sign in, other roles to their dashboard, administrators get in", () => {
    const { unmount } = renderShell({ user: null, initializing: false, can: () => false, logout: async () => {} }, "/admin");
    expect(screen.getByTestId("where")).toHaveTextContent("/login");
    unmount();
    for (const role of ["patient", "doctor", "receptionist"]) {
      const view = renderShell(authAs("Someone", [role], PERMISSIONS[role]), "/admin");
      expect(screen.queryByText("Admin dashboard")).not.toBeInTheDocument();
      expect(screen.getByTestId("where")).toHaveTextContent("/dashboard");
      view.unmount();
    }
    renderShell(authAs("Ada", ["admin"], ADMIN), "/admin");
    expect(screen.getByText("Admin dashboard")).toBeInTheDocument();
  });
});

describe("profile link", () => {
  it("is not offered to a doctor login that has no doctor profile", () => {
    const auth = authAs("New Doctor", ["doctor"], PERMISSIONS.doctor);
    auth.user.doctor_id = null;
    renderShell(auth);
    expect(menu()).not.toContain("My Profile");
  });
});
