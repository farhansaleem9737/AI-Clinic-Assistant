import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProtectedRoute from "../components/ProtectedRoute";
import { useAuth } from "../context/useAuth";
import { getPasswordStatus } from "../services/authService";
import { getUnreadCount, globalSearch, listNotifications, markNotificationRead } from "../services/workspaceService";
import { authAs, PERMISSIONS } from "../test/fixtures";
import { ADMIN_PERMISSIONS } from "../routes/navigation";
import AppLayout from "./AppLayout";

vi.mock("../context/useAuth");
vi.mock("../services/workspaceService");
vi.mock("../services/authService");

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

// Top-level sidebar entries in order: links, and groups (their sections are inside).
const menu = () =>
  [...screen.getByRole("navigation").querySelectorAll(":scope > a, :scope > .nav-group > .nav-group-toggle")].map((el) => el.textContent);

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
    expect(me).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(me);
    expect(me).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("menu", { name: "Account" });
    expect(menu).toHaveTextContent("user@example.com"); // the account header: who is signed in
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent.trim())).toEqual([
      "My Profile", "Account Settings", "Change Password", "Logout",
    ]);
    expect(within(menu).getByRole("menuitem", { name: "My Profile" })).toHaveAttribute("href", "/profile");
    expect(within(menu).getByRole("menuitem", { name: "Account Settings" })).toHaveAttribute("href", "/account");
    expect(within(menu).getByRole("menuitem", { name: "My Profile" })).toHaveFocus(); // focus moves into the menu
  });

  it.each([
    ["doctor", "Sarah Khan", PERMISSIONS.doctor, "Doctor", ["My Profile", "Account Settings", "Change Password", "Logout"], "/doctor/profile"],
    ["receptionist", "Rita", PERMISSIONS.receptionist, "Receptionist", ["My Profile", "Change Password", "Logout"], "/account"],
    ["admin", "Ada", ADMIN, "Administrator", ["My Profile", "Clinic Settings", "Change Password", "Logout"], "/account"],
  ])("the %s's menu has only their real destinations", async (role, name, permissions, label, items, profile) => {
    renderShell(authAs(name, [role], permissions));
    await userEvent.click(screen.getByRole("button", { name: new RegExp(`${name}, ${label}: account menu`) }));
    const menu = screen.getByRole("menu", { name: "Account" });
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent.trim())).toEqual(items);
    expect(within(menu).getByRole("menuitem", { name: "My Profile" })).toHaveAttribute("href", profile);
  });

  it("closes on a second click, an outside tap, Escape (even from the trigger) and Tab", async () => {
    const user = userEvent.setup();
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    const me = screen.getByRole("button", { name: /account menu/ });
    await user.click(me);
    await user.click(me);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(me);
    await user.pointer({ keys: "[MouseLeft]", target: screen.getByTestId("where") }); // a tap outside
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(me);
    me.focus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(me).toHaveFocus();

    await user.click(me);
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Account Settings" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("menuitem", { name: "Logout" })).toHaveFocus();
    await user.tab();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("My Profile navigates and closes the menu; Logout uses the app's own logout", async () => {
    const auth = authAs("John Doe", ["patient"], PERMISSIONS.patient);
    auth.logout = vi.fn(async () => {});
    renderShell(auth);
    await userEvent.click(screen.getByRole("button", { name: /account menu/ }));
    await userEvent.click(screen.getByRole("menuitem", { name: "My Profile" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/profile");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /account menu/ }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Logout" }));
    expect(auth.logout).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/login"));
  });

  it("stays open when focus blurs to nothing, as Safari does when an item is pressed", async () => {
    const auth = authAs("John Doe", ["patient"], PERMISSIONS.patient);
    auth.logout = vi.fn(async () => {});
    renderShell(auth);
    await userEvent.click(screen.getByRole("button", { name: /account menu/ }));
    // Safari doesn't focus a pressed button: the focused item blurs with no relatedTarget.
    act(() => screen.getByRole("menuitem", { name: "My Profile" }).blur());
    const logout = screen.getByRole("menuitem", { name: "Logout" });
    await userEvent.click(logout);
    expect(auth.logout).toHaveBeenCalledOnce();
  });

  it("Change Password opens the shared dialog above the page", async () => {
    getPasswordStatus.mockResolvedValue({ data: { current_password_required: false } });
    renderShell(authAs("Rita", ["receptionist"], PERMISSIONS.receptionist));
    await userEvent.click(screen.getByRole("button", { name: /account menu/ }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Change Password" }));
    const dialog = await screen.findByRole("dialog", { name: "Change Password" });
    expect(dialog.closest(".topbar")).toBeNull(); // rendered in <body>, not clipped by the top bar
    expect(await within(dialog).findByLabelText("New password")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
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
    const note = { id: "n-1", type: "appointment_booked", title: "New appointment", message: "An appointment was booked.", link: "/appointments/01a0ed6e-7dcf-7b64-bc44-8d7e5496d463", read_at: null, created_at: "2027-04-23T05:00:00Z" };
    listNotifications.mockResolvedValue({ data: { items: [note], unread: 2 } });
    markNotificationRead.mockResolvedValue({ data: { ...note, read_at: "2027-04-23T06:00:00Z" } });
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    const bell = await screen.findByRole("button", { name: "Notifications, 2 unread" });
    await userEvent.click(bell);
    const panel = screen.getByRole("dialog", { name: "Notifications" });
    await userEvent.click(await within(panel).findByRole("button", { name: /New appointment/ }));
    expect(markNotificationRead).toHaveBeenCalledWith("n-1");
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/appointments/01a0ed6e-7dcf-7b64-bc44-8d7e5496d463"));
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
        doctors: [{ id: "d-1", name: "Dr. Sarah Khan", specialization: "Cardiologist", department_name: "Cardiology" }],
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
      "Doctors: Dr. Sarah Khan, Cardiologist · Cardiology",
    ]);
    expect(globalSearch).toHaveBeenCalledTimes(1);
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent("/doctors/d-1");
  });

  it("an older, slower answer never replaces the newer one", async () => {
    const pending = {};
    globalSearch.mockImplementation((term) => new Promise((resolve) => (pending[term] = resolve)));
    const answer = (term, name) =>
      pending[term]({ data: { query: term, patients: null, doctors: [{ id: name, name, specialization: "GP" }], appointments: [], users: null } });
    renderShell(authAs("Rita", ["receptionist"], PERMISSIONS.receptionist));
    const box = screen.getByRole("combobox", { name: /Search patients, doctors/ });
    await userEvent.type(box, "dr sa");
    await waitFor(() => expect(globalSearch).toHaveBeenCalledWith("dr sa", expect.anything()));
    await userEvent.type(box, "rah");
    await waitFor(() => expect(globalSearch).toHaveBeenCalledWith("dr sarah", expect.anything()));
    expect(globalSearch.mock.calls[0][1].signal.aborted).toBe(true); // the replaced request is cancelled
    expect(globalSearch).toHaveBeenCalledTimes(2); // typing is debounced: one request per pause
    await act(async () => answer("dr sarah", "Dr. Sarah Khan"));
    await act(async () => answer("dr sa", "Dr. Saad Ali")); // arrives late: ignored
    const results = await screen.findByRole("listbox", { name: "Search results" });
    expect(within(results).getAllByRole("option").map((o) => o.getAttribute("aria-label"))).toEqual(["Doctors: Dr. Sarah Khan, GP"]);
  });

  it("is a clinic search box, not a login field (no saved-password suggestions)", () => {
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    const box = screen.getByRole("combobox", { name: "Search doctors or departments" });
    expect(box).toHaveAttribute("type", "search");
    expect(box).toHaveAttribute("autocomplete", "off");
    expect(box).toHaveAttribute("name", "clinic-global-search");
    expect(box).toHaveAttribute("placeholder", "Search doctors or departments...");
    expect(box.closest("form")).toBeNull(); // nothing for a password manager to treat as a sign-in form
    expect(box.getAttribute("placeholder")).not.toMatch(/user|email|login|password/i);
  });

  it.each([
    ["receptionist", PERMISSIONS.receptionist, "Search patients, doctors or departments..."],
    ["doctor", PERMISSIONS.doctor, "Search doctors, departments or your patients..."],
    ["admin", ADMIN, "Search users, doctors, patients, departments..."],
  ])("the %s's placeholder names what they may search", (role, permissions, placeholder) => {
    renderShell(authAs("Someone", [role], permissions));
    expect(screen.getByRole("combobox")).toHaveAttribute("placeholder", placeholder);
  });

  it("a patient finds doctors and departments; a department keeps the doctors-page filters", async () => {
    globalSearch.mockResolvedValue({
      data: {
        query: "cardio",
        categories: ["doctors", "departments"],
        patients: null,
        doctors: [{ id: "d-1", name: "Dr. Sarah Khan", specialization: "Cardiologist", department_name: "Cardiology", photo_url: null }],
        departments: [{ id: "dep-1", name: "Cardiology", description: "Heart care", icon: null, color: null }],
        appointments: null,
        users: null,
      },
    });
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient), "/doctors?min_experience=10&sort=fee_asc&page=3");
    await userEvent.type(screen.getByRole("combobox"), "cardio");
    const results = await screen.findByRole("listbox", { name: "Search results" });
    expect((await within(results).findAllByRole("option")).map((o) => o.getAttribute("aria-label"))).toEqual([
      "Doctors: Dr. Sarah Khan, Cardiologist · Cardiology",
      "Departments: Cardiology, Heart care",
    ]);
    await userEvent.click(within(results).getByRole("option", { name: /Departments: Cardiology/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/doctors?min_experience=10&sort=fee_asc&department=dep-1");
  });

  it("shows errors and empty results, clears, and closes on Escape", async () => {
    globalSearch.mockRejectedValueOnce({ response: { data: { error: { message: "Too many attempts" } } } });
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    const box = screen.getByRole("combobox");
    await userEvent.type(box, "zz");
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts");
    globalSearch.mockResolvedValue({ data: { query: "zzz", doctors: [], departments: [] } });
    await userEvent.type(box, "z");
    expect(await screen.findByText(/No results for “zzz”/)).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(box).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(box).toHaveValue("");
    expect(box).toHaveFocus();
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

describe("the patient's My Profile group (D110)", () => {
  const patient = () => authAs("Farhan Saleem", ["patient"], PERMISSIONS.patient);
  const group = () => screen.getByRole("button", { name: "My Profile" });

  it("is open and active on its pages, with the current section highlighted", () => {
    renderShell(patient(), "/profile/medical-information");
    expect(group()).toHaveAttribute("aria-expanded", "true");
    expect(group()).toHaveClass("active");
    const nav = screen.getByRole("navigation");
    expect(within(nav).getByRole("link", { name: "Medical Information" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Personal Information" })).not.toHaveAttribute("aria-current");
    expect(within(nav).getByRole("link", { name: "Contact Information" })).toHaveAttribute("href", "/profile/contact");
  });

  it("opens elsewhere without closing the mobile drawer, and its links navigate", async () => {
    const user = userEvent.setup();
    renderShell(patient(), "/dashboard");
    expect(group()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Medical Information" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open menu" }));
    await user.click(group());
    expect(group()).toHaveAttribute("aria-expanded", "true");
    expect(document.querySelector(".shell")).toHaveClass("nav-open");
    await user.click(screen.getByRole("link", { name: "Medical Information" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/profile/medical-information");
    expect(document.querySelector(".shell")).not.toHaveClass("nav-open");
  });

  it("is not in other roles' menus", () => {
    renderShell(authAs("Dr Who", ["doctor"], PERMISSIONS.doctor));
    expect(screen.queryByRole("button", { name: "My Profile" })).not.toBeInTheDocument();
    expect(screen.queryByText("Medical Information")).not.toBeInTheDocument();
  });
});
