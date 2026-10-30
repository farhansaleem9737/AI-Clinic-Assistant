import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { acceptInvitation, acceptInvitationAsSignedIn, previewInvitation } from "../services/adminService";
import AcceptAdminInvite from "./AcceptAdminInvite";

vi.mock("../context/useAuth");
vi.mock("../services/adminService");

const TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcd";
const preview = (overrides = {}) => ({
  data: { email: "grace@clinic.example", name: "Grace Hopper", status: "pending", expires_at: "2027-04-24T05:00:00Z", account_exists: false, ...overrides },
});

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.hash}</p>;
}

let auth;
function renderPage(entry = `/accept-admin-invite#token=${TOKEN}`) {
  useAuth.mockImplementation(() => auth);
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/accept-admin-invite" element={<AcceptAdminInvite />} />
        <Route path="/admin" element={<p>Admin dashboard</p>} />
        <Route path="/login" element={<p>Login page</p>} />
      </Routes>
      <Where />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  auth = { user: null, login: vi.fn().mockResolvedValue({}), logout: vi.fn(), fetchCurrentUser: vi.fn().mockResolvedValue({}) };
});

describe("Accept administrator invitation", () => {
  it("reads the token from the fragment, then removes it from the address bar", async () => {
    previewInvitation.mockResolvedValue(preview());
    renderPage();
    expect(await screen.findByText(/invited to administer Clinic AI Assistant/)).toBeInTheDocument();
    expect(previewInvitation).toHaveBeenCalledWith(TOKEN);
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/accept-admin-invite$/);
    expect(screen.getByLabelText("Email")).toHaveValue("grace@clinic.example");
    expect(screen.getByLabelText("Full name")).toHaveValue("Grace Hopper");
  });

  it("validates the new password before accepting", async () => {
    const user = userEvent.setup();
    previewInvitation.mockResolvedValue(preview());
    renderPage();
    await user.type(await screen.findByLabelText("Password"), "short");
    await user.type(screen.getByLabelText("Confirm Password"), "different");
    await user.click(screen.getByRole("button", { name: "Accept Invitation" }));
    expect(screen.getByText("Use at least 8 characters.")).toBeInTheDocument();
    expect(screen.getByText("The passwords do not match.")).toBeInTheDocument();
    expect(acceptInvitation).not.toHaveBeenCalled();
  });

  it("creates the account, signs in and opens the admin dashboard", async () => {
    const user = userEvent.setup();
    previewInvitation.mockResolvedValue(preview());
    acceptInvitation.mockResolvedValue({ data: { roles: ["admin"] } });
    renderPage();
    await user.type(await screen.findByLabelText("Password"), "N3w-admin-password");
    await user.type(screen.getByLabelText("Confirm Password"), "N3w-admin-password");
    await user.click(screen.getByRole("button", { name: "Accept Invitation" }));
    expect(acceptInvitation).toHaveBeenCalledWith({ token: TOKEN, name: "Grace Hopper", password: "N3w-admin-password" });
    expect(auth.login).toHaveBeenCalledWith("grace@clinic.example", "N3w-admin-password");
    expect(await screen.findByText("Admin dashboard")).toBeInTheDocument();
  });

  it.each([
    ["expired", "Invitation expired"],
    ["accepted", "Invitation already used"],
    ["revoked", "Invitation revoked"],
  ])("a %s invitation says so and offers no form", async (status, title) => {
    previewInvitation.mockResolvedValue(preview({ status }));
    renderPage();
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept Invitation" })).not.toBeInTheDocument();
  });

  it("an unknown or missing token is invalid", async () => {
    previewInvitation.mockRejectedValue({ response: { status: 404, data: { error: { code: "INVITATION_INVALID", message: "x" } } } });
    renderPage();
    expect(await screen.findByRole("heading", { name: "Invitation not valid" })).toBeInTheDocument();
  });

  it("no token at all never calls the server", () => {
    renderPage("/accept-admin-invite");
    expect(screen.getByRole("heading", { name: "Invitation not valid" })).toBeInTheDocument();
    expect(previewInvitation).not.toHaveBeenCalled();
  });

  it("a link used meanwhile switches to the used state", async () => {
    const user = userEvent.setup();
    previewInvitation.mockResolvedValue(preview());
    acceptInvitation.mockRejectedValue({ response: { status: 409, data: { error: { code: "INVITATION_USED", message: "used" } } } });
    renderPage();
    await user.type(await screen.findByLabelText("Password"), "N3w-admin-password");
    await user.type(screen.getByLabelText("Confirm Password"), "N3w-admin-password");
    await user.click(screen.getByRole("button", { name: "Accept Invitation" }));
    expect(await screen.findByRole("heading", { name: "Invitation already used" })).toBeInTheDocument();
  });

  it("an existing account signs in as itself, then accepts", async () => {
    const user = userEvent.setup();
    previewInvitation.mockResolvedValue(preview({ account_exists: true }));
    acceptInvitationAsSignedIn.mockResolvedValue({ data: { roles: ["admin", "patient"] } });
    renderPage();
    expect(await screen.findByText(/already has an account/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Confirm Password")).not.toBeInTheDocument(); // no new password
    await user.type(screen.getByLabelText("Password"), "my-password");
    await user.click(screen.getByRole("button", { name: "Accept Invitation" }));
    expect(auth.login).toHaveBeenCalledWith("grace@clinic.example", "my-password");
    expect(acceptInvitationAsSignedIn).toHaveBeenCalledWith(TOKEN, "my-password");
    await waitFor(() => expect(auth.fetchCurrentUser).toHaveBeenCalled());
    expect(await screen.findByText("Admin dashboard")).toBeInTheDocument();
  });

  it("signed in as someone else: must sign out first", async () => {
    auth.user = { email: "someone@else.example" };
    previewInvitation.mockResolvedValue(preview({ account_exists: true }));
    renderPage();
    expect(await screen.findByText(/You are signed in as someone@else.example/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept Invitation" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(auth.logout).toHaveBeenCalled();
  });
});
