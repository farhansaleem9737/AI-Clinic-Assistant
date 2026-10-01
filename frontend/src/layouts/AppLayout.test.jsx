import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ProtectedRoute from "../components/ProtectedRoute";
import { useAuth } from "../context/useAuth";
import { authAs, PERMISSIONS } from "../test/fixtures";
import AppLayout from "./AppLayout";

vi.mock("../context/useAuth");

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
      "Dashboard", "Appointments", "Book appointment", "Schedule", "Doctors", "Departments", "Patients", "Manage doctors",
    ]);
  });

  it("admin", () => {
    renderShell(authAs("Ada", ["admin"], PERMISSIONS.admin));
    expect(menu()).toContain("Users");
    expect(menu()).toContain("Manage departments");
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
  it("shows the signed-in user and their role in the top bar", () => {
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    const me = screen.getByRole("link", { name: /John Doe, Patient/ });
    expect(me).toHaveAttribute("href", "/profile");
    expect(me).toHaveTextContent("John Doe");
    expect(me).toHaveTextContent("Patient");
  });

  it("shows a doctor with the illustrated doctor avatar", () => {
    const { container } = renderShell(authAs("Sarah Khan", ["doctor"], PERMISSIONS.doctor));
    expect(container.querySelector('.topbar [data-avatar="doctor"]')).not.toBeNull();
  });

  it("offers Help & Support next to Logout", () => {
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    expect(screen.getByRole("link", { name: "Help & Support" })).toHaveAttribute("href", "/help");
  });

  it("does not show a notification bell (there are no notifications yet)", () => {
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    expect(screen.queryByRole("button", { name: /notification/i })).not.toBeInTheDocument();
  });

  it("searching from the top bar opens the doctor directory with the query", async () => {
    renderShell(authAs("John Doe", ["patient"], PERMISSIONS.patient));
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
});

describe("profile link", () => {
  it("is not offered to a doctor login that has no doctor profile", () => {
    const auth = authAs("New Doctor", ["doctor"], PERMISSIONS.doctor);
    auth.user.doctor_id = null;
    renderShell(auth);
    expect(menu()).not.toContain("My Profile");
  });
});
