import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { anonymous, authAs, PERMISSIONS } from "../test/fixtures";
import Landing from "./Landing";

vi.mock("../context/useAuth");

function renderLanding(auth = anonymous) {
  useAuth.mockReturnValue(auth);
  Element.prototype.scrollIntoView = vi.fn();
  return render(
    <MemoryRouter>
      <Landing />
    </MemoryRouter>
  );
}

describe("public landing page", () => {
  it("links the header to each section and to the existing sign-in and registration pages", () => {
    renderLanding();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      "#home",
      "#features",
      "#architecture",
      "#security",
      "#pricing",
    ]);
    for (const id of ["home", "features", "architecture", "security", "pricing"]) {
      expect(document.getElementById(id)).not.toBeNull();
    }
    expect(screen.getAllByRole("link", { name: "Sign In" })[0]).toHaveAttribute("href", "/login");
    expect(screen.getAllByRole("link", { name: /Get Started/ })[0]).toHaveAttribute("href", "/register");
  });

  it("scrolls to a section when a navigation link is used", async () => {
    renderLanding();
    await userEvent.click(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Security" }));
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("sends the assistant shortcuts to real pages and asks visitors to sign in to chat", () => {
    renderLanding();
    expect(screen.getByRole("link", { name: "Find a Doctor" })).toHaveAttribute("href", "/doctors");
    expect(screen.getByRole("link", { name: "Book Appointment" })).toHaveAttribute("href", "/appointments/book");
    expect(screen.getByRole("link", { name: "Explain a Report" })).toHaveAttribute("href", "/profile");
    expect(screen.getByRole("link", { name: "Clinic Information" })).toHaveAttribute("href", "/departments");
    expect(screen.getByRole("link", { name: /Sign in to chat/ })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("opens and closes the mobile menu with Escape", async () => {
    renderLanding();
    const toggle = screen.getByRole("button", { name: "Open menu" });
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("navigation", { name: "Mobile" })).toBeVisible();
    await userEvent.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("expands FAQ answers and switches showcase tabs with the keyboard", async () => {
    renderLanding();
    const question = screen.getByRole("button", { name: "Does the AI replace medical professionals?" });
    expect(question).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(question);
    expect(question).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/It does not diagnose or prescribe/)).toBeVisible();

    const tabs = within(screen.getByRole("tablist", { name: "Workspaces" }));
    tabs.getByRole("tab", { name: "Admin" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(tabs.getByRole("tab", { name: "Patient" })).toHaveAttribute("aria-selected", "true");
  });

  it("offers signed-in users their dashboard instead of sign-in", () => {
    renderLanding(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    expect(screen.getAllByRole("link", { name: /Open dashboard/ })[0]).toHaveAttribute("href", "/dashboard");
    expect(within(screen.getByRole("banner")).queryByRole("link", { name: "Sign In" })).not.toBeInTheDocument();
  });
});
