import { render, screen, within } from "@testing-library/react";
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
});
