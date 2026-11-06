import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken } from "../services/api";
import { changePassword, getPasswordStatus } from "../services/authService";
import ChangePasswordModal from "./ChangePasswordModal";

vi.mock("../services/authService");
vi.mock("../services/api", () => ({ setAccessToken: vi.fn() }));

const httpError = (status, code) => ({ response: { status, data: { error: { code, message: "internal detail" } } } });

async function open({ needCurrent = false } = {}) {
  getPasswordStatus.mockResolvedValue({ data: { current_password_required: needCurrent } });
  const onClose = vi.fn();
  const onChanged = vi.fn();
  const user = userEvent.setup();
  render(<ChangePasswordModal onClose={onClose} onChanged={onChanged} />);
  const dialog = screen.getByRole("dialog", { name: "Change Password" });
  await within(dialog).findByLabelText("New password");
  return { user, dialog, onClose, onChanged };
}

async function fill(user, dialog, next = "a long passphrase 1", confirm = next, current) {
  if (current !== undefined) await user.type(within(dialog).getByLabelText("Current password"), current);
  await user.type(within(dialog).getByLabelText("New password"), next);
  await user.type(within(dialog).getByLabelText("Confirm new password"), confirm);
}

const update = (dialog) => within(dialog).getByRole("button", { name: /Update Password|Please wait/ });

beforeEach(() => vi.resetAllMocks());

describe("Change Password dialog", () => {
  it("has its title, explanation and close button, and asks only for the new password right after sign-in", async () => {
    const { user, dialog, onClose } = await open();
    expect(dialog).toHaveAccessibleDescription("Update your account password to keep your information secure.");
    expect(within(dialog).queryByLabelText("Current password")).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("New password")).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("show/hide works on each field independently", async () => {
    const { user, dialog } = await open();
    await fill(user, dialog, "secret phrase");
    const [first, second] = within(dialog).getAllByRole("button", { name: "Show password" });
    await user.click(first);
    expect(within(dialog).getByLabelText("New password")).toHaveAttribute("type", "text");
    expect(within(dialog).getByLabelText("Confirm new password")).toHaveAttribute("type", "password");
    expect(second).toHaveAttribute("aria-pressed", "false");
  });

  it("checks length and matching while typing, and sends nothing until both are right", async () => {
    const { user, dialog } = await open();
    await fill(user, dialog, "short", "shorter");
    expect(within(dialog).getByText("At least 8 characters (5 so far).")).toBeInTheDocument();
    expect(within(dialog).getByText("Passwords do not match.")).toBeInTheDocument();
    await user.click(update(dialog));
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("success: keeps the user signed in with the new session and reports it once", async () => {
    let finish;
    changePassword.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const { user, dialog, onClose, onChanged } = await open();
    await fill(user, dialog, "my new passphrase !");
    await user.click(update(dialog));
    await user.click(update(dialog)); // a second click while it runs
    expect(update(dialog)).toBeDisabled();
    expect(changePassword).toHaveBeenCalledOnce();
    expect(changePassword).toHaveBeenCalledWith({ new_password: "my new passphrase !" });
    finish({ data: { access_token: "fresh", token_type: "bearer", expires_in: 900 } });
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(setAccessToken).toHaveBeenCalledWith("fresh");
    expect(onChanged).toHaveBeenCalledWith("Your password has been updated successfully.");
  });

  it("later on, the current password is required and sent", async () => {
    changePassword.mockResolvedValue({ data: { access_token: "t" } });
    const { user, dialog } = await open({ needCurrent: true });
    expect(within(dialog).getByLabelText("Current password")).toHaveFocus();
    await user.type(within(dialog).getByLabelText("New password"), "another passphrase");
    await user.type(within(dialog).getByLabelText("Confirm new password"), "another passphrase");
    await user.click(update(dialog));
    expect(within(dialog).getByText("Enter your current password.")).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Current password"), "old one");
    await user.click(update(dialog));
    expect(changePassword).toHaveBeenCalledWith({ new_password: "another passphrase", current_password: "old one" });
  });

  it("if the server wants re-authentication, the current-password field appears", async () => {
    changePassword.mockRejectedValueOnce(httpError(403, "REAUTHENTICATION_REQUIRED"));
    const { user, dialog, onClose } = await open();
    await fill(user, dialog);
    await user.click(update(dialog));
    expect(await within(dialog).findByLabelText("Current password")).toHaveFocus();
    expect(within(dialog).getByText("Enter your current password to continue.")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it.each([
    [httpError(400, "INCORRECT_PASSWORD"), "The current password is incorrect.", true],
    [httpError(400, "PASSWORD_UNCHANGED"), "Choose a password different from your current one."],
    [httpError(422, "VALIDATION_ERROR"), "Use 8 to 128 characters."],
    [httpError(429, "RATE_LIMITED"), "Too many attempts. Please wait a minute and try again."],
    [httpError(401, "SESSION_REQUIRED"), "Your session has expired. Please sign in again, then change your password."],
    [new Error("Network Error"), "We couldn't reach the server. Check your connection and try again."],
    [httpError(500, "INTERNAL_ERROR"), "Your password could not be changed right now. Please try again."],
  ])("explains a failure clearly and stays open (%#)", async (error, message, needCurrent = false) => {
    changePassword.mockRejectedValueOnce(error);
    const { user, dialog, onClose } = await open({ needCurrent });
    await fill(user, dialog, undefined, undefined, needCurrent ? "old one" : undefined);
    await user.click(update(dialog));
    expect(await within(dialog).findByText(message)).toBeInTheDocument();
    expect(within(dialog).queryByText(/internal detail/)).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(update(dialog)).toBeEnabled();
  });
});
