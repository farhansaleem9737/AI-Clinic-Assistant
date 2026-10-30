import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import AppLayout from "../layouts/AppLayout";
import { getUnreadCount } from "../services/workspaceService";
import { authAs, PERMISSIONS } from "../test/fixtures";

vi.mock("../context/useAuth");
vi.mock("../services/workspaceService");

function Broken() {
  throw new Error("boom");
}

beforeEach(() => {
  vi.resetAllMocks();
  getUnreadCount.mockResolvedValue({ data: { unread: 0 } });
  useAuth.mockReturnValue(authAs("Ada", ["admin"], [...PERMISSIONS.admin, "settings:manage"]));
});

describe("ErrorBoundary in the app shell (D95)", () => {
  it("a page that throws keeps the sidebar and header, and navigating away recovers", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <MemoryRouter initialEntries={["/broken"]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/broken" element={<Broken />} />
            <Route path="/admin/users" element={<p>Users page</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    expect(screen.getByRole("heading", { name: "Unable to load this page" })).toBeInTheDocument();
    expect(screen.queryByText("boom")).not.toBeInTheDocument(); // no error details on screen
    expect(screen.getByRole("complementary", { name: "Main navigation" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Dashboard" })).toHaveAttribute("href", "/dashboard");
    await userEvent.click(screen.getByRole("link", { name: "Users" }));
    expect(screen.getByText("Users page")).toBeInTheDocument();
    spy.mockRestore();
  });
});
