import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { anonymous, authAs, PERMISSIONS } from "../test/fixtures";
import DirectoryLayout from "./DirectoryLayout";

vi.mock("../context/useAuth");

function renderLayout(auth) {
  useAuth.mockReturnValue(auth);
  return render(
    <MemoryRouter initialEntries={["/doctors"]}>
      <Routes>
        <Route element={<DirectoryLayout />}>
          <Route path="/doctors" element={<p>Directory page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

describe("layout of the public directory pages", () => {
  it("gives visitors the public top navigation with sign-in and sign-up", () => {
    renderLayout(anonymous);
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual(["Doctors", "Departments"]);
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(screen.getByRole("link", { name: "Create account" })).toHaveAttribute("href", "/register");
    expect(screen.getByRole("link", { name: "Search doctors" })).toHaveAttribute("href", "/doctors#search");
    expect(screen.getByText("Directory page")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Dashboard" })).not.toBeInTheDocument();
  });

  it("keeps signed-in users inside their app shell", () => {
    renderLayout(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sign in" })).not.toBeInTheDocument();
    expect(screen.getByText("Directory page")).toBeInTheDocument();
  });

  it("shows neither layout while the session is being restored", () => {
    renderLayout({ ...anonymous, initializing: true });
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(screen.queryByText("Directory page")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sign in" })).not.toBeInTheDocument();
  });

  it("never remounts the signed-in shell between the directory and the user's own pages", async () => {
    useAuth.mockReturnValue(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    render(
      <MemoryRouter initialEntries={["/doctors"]}>
        <Routes>
          <Route element={<DirectoryLayout />}>
            <Route path="/doctors" element={<p>Directory page</p>} />
            <Route path="/dashboard" element={<p>Dashboard page</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    // The shell holds the assistant's conversation: it must be the same element after navigating.
    const shell = document.querySelector(".shell");
    await userEvent.click(screen.getByRole("link", { name: "Dashboard" }));
    expect(await screen.findByText("Dashboard page")).toBeInTheDocument();
    expect(document.querySelector(".shell")).toBe(shell);
    await userEvent.click(screen.getByRole("link", { name: "Doctors" }));
    expect(await screen.findByText("Directory page")).toBeInTheDocument();
    expect(document.querySelector(".shell")).toBe(shell);
  });
});
