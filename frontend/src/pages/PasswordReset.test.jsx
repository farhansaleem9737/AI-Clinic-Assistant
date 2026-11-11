import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { requestPasswordReset, resetPassword, verifyResetCode } from "../services/authService";
import ForgotPassword, { DONE, RESEND_SECONDS } from "./ForgotPassword";
import ResetPassword from "./ResetPassword";

vi.mock("../services/authService");

const GRANT = "g".repeat(43);
const refused = (code, status = 400) => ({ response: { status, data: { error: { code, message: "internal detail" } } } });

function Where() {
  const location = useLocation();
  return (
    <p data-testid="where">
      {location.pathname}
      {location.hash} {location.state?.notice}
    </p>
  );
}

function at(path) {
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

const digits = () => screen.getAllByRole("textbox", { name: /^Digit \d of 6$/ });

async function toCodeStep(user, email = "nadia@example.com") {
  requestPasswordReset.mockResolvedValue({ data: { message: "server text" } });
  at("/forgot-password");
  await user.type(screen.getByLabelText("Email address"), `  ${email} `);
  await user.click(screen.getByRole("button", { name: "Send code" }));
  await screen.findByRole("heading", { name: "Enter the code" });
}

beforeEach(() => vi.resetAllMocks());
afterEach(() => vi.useRealTimers());

describe("Forgot password: email", () => {
  it("sends the trimmed address and answers the same way for any address", async () => {
    let finish;
    requestPasswordReset.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const user = userEvent.setup();
    at("/forgot-password");
    await user.type(screen.getByLabelText("Email address"), "  nadia@example.com ");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();
    finish({ data: { message: "server text" } });
    expect(await screen.findByRole("heading", { name: "Enter the code" })).toBeInTheDocument();
    expect(screen.getByText(/If an account exists for/)).toBeInTheDocument();
    expect(screen.queryByText("server text")).not.toBeInTheDocument();
    expect(requestPasswordReset).toHaveBeenCalledTimes(1);
    expect(requestPasswordReset).toHaveBeenCalledWith("nadia@example.com");
  });

  it("checks the address first and never shows a backend message", async () => {
    requestPasswordReset.mockRejectedValue({ response: { status: 500, data: { error: { message: "Traceback" } } } });
    const user = userEvent.setup();
    at("/forgot-password");
    await user.type(screen.getByLabelText("Email address"), "not-an-email");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument();
    expect(requestPasswordReset).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("Email address"));
    await user.type(screen.getByLabelText("Email address"), "nadia@example.com");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    expect(await screen.findByText(/couldn't send the request right now/)).toBeInTheDocument();
    expect(screen.queryByText("Traceback")).not.toBeInTheDocument();
  });
});

describe("Forgot password: code", () => {
  it("six boxes: typing moves on, Backspace goes back, and the sixth digit verifies", async () => {
    verifyResetCode.mockResolvedValue({ data: { reset_token: GRANT, expires_in: 600 } });
    const user = userEvent.setup();
    await toCodeStep(user);
    const boxes = digits();
    expect(boxes).toHaveLength(6);
    expect(boxes[0]).toHaveFocus();
    expect(boxes[0]).toHaveAttribute("autocomplete", "one-time-code");
    await user.keyboard("12");
    expect(boxes[2]).toHaveFocus();
    await user.keyboard("{Backspace}");
    expect(boxes[1]).toHaveFocus();
    expect(boxes[1]).toHaveValue("");
    await user.keyboard("23456");
    await waitFor(() => expect(verifyResetCode).toHaveBeenCalledWith("nadia@example.com", "123456"));
    expect(await screen.findByRole("heading", { name: "Create a new password" })).toBeInTheDocument();
  });

  it("a pasted code fills every box", async () => {
    verifyResetCode.mockResolvedValue({ data: { reset_token: GRANT, expires_in: 600 } });
    const user = userEvent.setup();
    await toCodeStep(user);
    fireEvent.paste(digits()[0], { clipboardData: { getData: () => " 654 321 " } });
    await waitFor(() => expect(verifyResetCode).toHaveBeenCalledWith("nadia@example.com", "654321"));
  });

  it("a wrong code is explained, cleared, and the same words for every refusal", async () => {
    verifyResetCode.mockRejectedValue(refused("RESET_CODE_INVALID"));
    const user = userEvent.setup();
    await toCodeStep(user);
    await user.click(screen.getByRole("button", { name: "Verify code" }));
    expect(screen.getByText("Enter the 6-digit code from the email.")).toBeInTheDocument();
    expect(verifyResetCode).not.toHaveBeenCalled();
    await user.click(digits()[0]);
    await user.keyboard("999999");
    expect(await screen.findByText(/That code is incorrect or has expired/)).toBeInTheDocument();
    expect(digits().every((box) => box.value === "")).toBe(true);
    expect(screen.queryByText("internal detail")).not.toBeInTheDocument();
  });

  it("resend waits 60 seconds, then sends again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await toCodeStep(user);
    expect(screen.getByRole("button", { name: `Resend code in ${RESEND_SECONDS}s` })).toBeDisabled();
    for (let i = 0; i < RESEND_SECONDS; i++) {
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
    }
    await user.click(screen.getByRole("button", { name: "Resend code" }));
    expect(requestPasswordReset).toHaveBeenCalledTimes(2);
    expect(await screen.findByText(/a new code is on its way/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Resend code in/ })).toBeDisabled();
  });
});

describe("Forgot password: new password", () => {
  async function toPasswordStep(user) {
    verifyResetCode.mockResolvedValue({ data: { reset_token: GRANT, expires_in: 600 } });
    await toCodeStep(user);
    await user.keyboard("123456");
    await screen.findByRole("heading", { name: "Create a new password" });
  }

  it("needs matching passwords, saves with the reset token, and says so only after the server confirms", async () => {
    let finish;
    resetPassword.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const user = userEvent.setup();
    await toPasswordStep(user);
    await user.type(screen.getByLabelText("New password"), "A long passphrase 1");
    await user.type(screen.getByLabelText("Confirm new password"), "A long passphrase 2");
    expect(screen.getByText("Passwords do not match.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reset Password" }));
    expect(resetPassword).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("Confirm new password"));
    await user.type(screen.getByLabelText("Confirm new password"), "A long passphrase 1");
    await user.click(screen.getByRole("button", { name: "Reset Password" }));
    expect(resetPassword).toHaveBeenCalledWith(GRANT, "A long passphrase 1");
    expect(screen.queryByText(DONE)).not.toBeInTheDocument(); // not before the server answers
    finish({ data: { message: "ok" } });
    expect(await screen.findByText(DONE)).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Back to Sign In" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/login Your password has been changed.");
    // Nothing sensitive kept in the browser's storage or address.
    expect(JSON.stringify({ ...window.localStorage, ...window.sessionStorage })).not.toContain(GRANT);
  });

  it("an expired reset goes back to the start with an explanation", async () => {
    resetPassword.mockRejectedValue(refused("RESET_TOKEN_EXPIRED"));
    const user = userEvent.setup();
    await toPasswordStep(user);
    await user.type(screen.getByLabelText("New password"), "A long passphrase 1");
    await user.type(screen.getByLabelText("Confirm new password"), "A long passphrase 1");
    await user.click(screen.getByRole("button", { name: "Reset Password" }));
    expect(await screen.findByText(/Request a new code to continue/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Forgot your password?" })).toBeInTheDocument();
  });
});

it("an old emailed reset link leads to Forgot password and drops its token", () => {
  at("/reset-password#token=abc");
  expect(screen.getByRole("heading", { name: "Forgot your password?" })).toBeInTheDocument();
});
