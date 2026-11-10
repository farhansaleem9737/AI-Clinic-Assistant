import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { checkResetToken, requestPasswordReset, resetPassword } from "../services/authService";
import ForgotPassword from "./ForgotPassword";
import ResetPassword from "./ResetPassword";

vi.mock("../services/authService");

const TOKEN = "t".repeat(43);
const refused = (code) => ({ response: { status: 400, data: { error: { code, message: "internal detail" } } } });

function Where() {
  const location = useLocation();
  return (
    <p data-testid="where">
      {location.pathname} {location.state?.notice}
    </p>
  );
}

function at(path, hash = "") {
  window.history.replaceState(null, "", `${path}${hash}`);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => vi.resetAllMocks());

describe("Forgot password", () => {
  it("sends the trimmed address once and answers the same way for any address", async () => {
    let finish;
    requestPasswordReset.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const user = userEvent.setup();
    at("/forgot-password");
    await user.type(screen.getByLabelText("Email address"), "  nadia@example.com ");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();
    finish({ data: { message: "server text" } });
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(screen.getByText(/If an account exists for this address, you'll receive a password reset link shortly/)).toBeInTheDocument();
    expect(screen.queryByText("server text")).not.toBeInTheDocument();
    expect(requestPasswordReset).toHaveBeenCalledTimes(1);
    expect(requestPasswordReset).toHaveBeenCalledWith("nadia@example.com");
  });

  it("checks the address first and never shows a backend message", async () => {
    requestPasswordReset.mockRejectedValue({ response: { status: 500, data: { error: { message: "Traceback" } } } });
    const user = userEvent.setup();
    at("/forgot-password");
    await user.type(screen.getByLabelText("Email address"), "not-an-email");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument();
    expect(requestPasswordReset).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("Email address"));
    await user.type(screen.getByLabelText("Email address"), "a@example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByText(/couldn't send the request right now/)).toBeInTheDocument();
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument();
  });
});

describe("Reset password", () => {
  it("checks the link, hides it from the address bar, and sets the password after confirmation", async () => {
    checkResetToken.mockResolvedValue({});
    resetPassword.mockResolvedValue({ data: { message: "ok" } });
    const user = userEvent.setup();
    at("/reset-password", `#token=${TOKEN}`);
    const next = await screen.findByLabelText("New password");
    expect(checkResetToken).toHaveBeenCalledWith(TOKEN);
    expect(window.location.hash).toBe("");
    expect(document.querySelector('meta[name="referrer"]')).toHaveAttribute("content", "no-referrer");

    await user.type(next, "short");
    expect(screen.getByText("At least 8 characters (5 so far).")).toBeInTheDocument();
    await user.clear(next);
    await user.type(next, "a long passphrase");
    await user.type(screen.getByLabelText("Confirm new password"), "a long passphrasE");
    await user.click(screen.getByRole("button", { name: "Reset password" }));
    expect(screen.getByText("Passwords do not match.")).toBeInTheDocument();
    expect(resetPassword).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("Confirm new password"));
    await user.type(screen.getByLabelText("Confirm new password"), "a long passphrase");
    await user.click(screen.getAllByRole("button", { name: "Show password" })[0]);
    expect(next).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Reset password" }));
    await waitFor(() => expect(resetPassword).toHaveBeenCalledWith(TOKEN, "a long passphrase"));
    expect(await screen.findByRole("heading", { name: "Password reset" })).toBeInTheDocument();
    expect(sessionStorage.length + localStorage.length).toBe(0);

    await user.click(screen.getByRole("link", { name: "Return to sign in" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/login Your password has been reset.");
  });

  it.each([
    ["RESET_TOKEN_EXPIRED", "This link has expired"],
    ["RESET_TOKEN_USED", "This link was already used"],
    ["RESET_TOKEN_INVALID", "This link isn't valid"],
  ])("explains a %s link before any password is typed", async (code, title) => {
    checkResetToken.mockRejectedValue(refused(code));
    at("/reset-password", `#token=${TOKEN}`);
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request a new link" })).toHaveAttribute("href", "/forgot-password");
  });

  it("a link without a token is not valid", () => {
    at("/reset-password");
    expect(screen.getByRole("heading", { name: "This link isn't valid" })).toBeInTheDocument();
    expect(checkResetToken).not.toHaveBeenCalled();
  });

  it("a link used in another tab meanwhile is explained on submit", async () => {
    checkResetToken.mockResolvedValue({});
    resetPassword.mockRejectedValue(refused("RESET_TOKEN_USED"));
    const user = userEvent.setup();
    at("/reset-password", `#token=${TOKEN}`);
    await user.type(await screen.findByLabelText("New password"), "a long passphrase");
    await user.type(screen.getByLabelText("Confirm new password"), "a long passphrase");
    await user.click(screen.getByRole("button", { name: "Reset password" }));
    expect(await screen.findByRole("heading", { name: "This link was already used" })).toBeInTheDocument();
  });
});
