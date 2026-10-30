import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createInvitation, listInvitations, resendInvitation, revokeInvitation } from "../../services/adminService";
import AdministratorAccess from "./AdministratorAccess";

vi.mock("../../services/adminService");

const invitation = (overrides = {}) => ({
  id: "i-1",
  email: "new@clinic.example",
  name: null,
  role: "admin",
  status: "pending",
  invited_by_name: "Ada Admin",
  created_at: "2027-04-23T05:00:00Z",
  expires_at: "2027-04-24T05:00:00Z",
  accepted_at: null,
  revoked_at: null,
  delivery_status: "sent",
  last_sent_at: "2027-04-23T05:00:00Z",
  ...overrides,
});

let onNotice;
let onInviteClose;
function renderSection(inviting = false) {
  onNotice = vi.fn();
  onInviteClose = vi.fn();
  return render(<AdministratorAccess inviting={inviting} onNotice={onNotice} onInviteClose={onInviteClose} />);
}

beforeEach(() => {
  vi.resetAllMocks();
  listInvitations.mockResolvedValue({ data: [invitation()] });
});

describe("Administrator invitations", () => {
  it("lists pending invitations with status, expiry and delivery", async () => {
    renderSection();
    const card = screen.getByRole("region", { name: "Administrator invitations" });
    const row = (await within(card).findByText("new@clinic.example")).closest("tr");
    expect(row).toHaveTextContent("Pending");
    expect(row).toHaveTextContent("Email sent");
    expect(row).toHaveTextContent("Apr 24, 2027");
    expect(within(card).getByRole("heading")).toHaveTextContent("(1 pending)");
  });

  it("says when there are no invitations", async () => {
    listInvitations.mockResolvedValue({ data: [] });
    renderSection();
    expect(await screen.findByText(/No invitations/)).toBeInTheDocument();
  });

  it("validates the invitation form before sending", async () => {
    const user = userEvent.setup();
    renderSection(true);
    const dialog = screen.getByRole("dialog", { name: "Invite Administrator" });
    expect(within(dialog).getByLabelText("Role")).toHaveValue("admin");
    expect(within(dialog).getByLabelText("Role")).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Email address"), "not-an-email");
    await user.click(within(dialog).getByRole("button", { name: "Send Invitation" }));
    expect(within(dialog).getByText("Enter a valid email address.")).toBeInTheDocument();
    expect(within(dialog).getByText("Enter your password to confirm.")).toBeInTheDocument();
    expect(createInvitation).not.toHaveBeenCalled();
  });

  it("sends an invitation and reports what the email provider said", async () => {
    const user = userEvent.setup();
    createInvitation.mockResolvedValue({ data: invitation({ email: "zoe@clinic.example", delivery_status: "outbox" }) });
    renderSection(true);
    const dialog = screen.getByRole("dialog", { name: "Invite Administrator" });
    await user.type(within(dialog).getByLabelText("Email address"), "zoe@clinic.example");
    await user.type(within(dialog).getByLabelText("Name (optional)"), "Zoe");
    await user.type(within(dialog).getByLabelText("Your password"), "my-password");
    await user.click(within(dialog).getByRole("button", { name: "Send Invitation" }));
    expect(createInvitation).toHaveBeenCalledWith({ email: "zoe@clinic.example", name: "Zoe", role: "admin", current_password: "my-password" });
    expect(onNotice).toHaveBeenCalledWith(expect.stringMatching(/saved to backend\/var\/outbox instead of being sent/));
    expect(onInviteClose).toHaveBeenCalled();
  });

  it("never says sent when the email failed", async () => {
    const user = userEvent.setup();
    createInvitation.mockResolvedValue({ data: invitation({ delivery_status: "failed" }) });
    renderSection(true);
    const dialog = screen.getByRole("dialog", { name: "Invite Administrator" });
    await user.type(within(dialog).getByLabelText("Email address"), "new@clinic.example");
    await user.type(within(dialog).getByLabelText("Your password"), "pw");
    await user.click(within(dialog).getByRole("button", { name: "Send Invitation" }));
    expect(onNotice).toHaveBeenCalledWith(expect.stringMatching(/the email could not be sent \(email failed\)/));
  });

  it("shows the server's refusal inside the dialog", async () => {
    const user = userEvent.setup();
    createInvitation.mockRejectedValue({ response: { status: 403, data: { error: { code: "REAUTHENTICATION_FAILED", message: "Your password is incorrect" } } } });
    renderSection(true);
    const dialog = screen.getByRole("dialog", { name: "Invite Administrator" });
    await user.type(within(dialog).getByLabelText("Email address"), "new@clinic.example");
    await user.type(within(dialog).getByLabelText("Your password"), "wrong");
    await user.click(within(dialog).getByRole("button", { name: "Send Invitation" }));
    expect(await within(dialog).findByText("Your password is incorrect")).toBeInTheDocument();
  });

  it("revokes an invitation only after confirming", async () => {
    const user = userEvent.setup();
    revokeInvitation.mockResolvedValue({ data: invitation({ status: "revoked" }) });
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Revoke invitation to new@clinic.example" }));
    expect(revokeInvitation).not.toHaveBeenCalled();
    await user.click(within(screen.getByRole("dialog", { name: "Revoke invitation?" })).getByRole("button", { name: "Revoke invitation" }));
    expect(revokeInvitation).toHaveBeenCalledWith("i-1");
    expect(onNotice).toHaveBeenCalledWith("The invitation to new@clinic.example was revoked.");
  });

  it("resends an invitation", async () => {
    const user = userEvent.setup();
    resendInvitation.mockResolvedValue({ data: invitation() });
    renderSection();
    await user.click(await screen.findByRole("button", { name: "Resend invitation to new@clinic.example" }));
    expect(resendInvitation).toHaveBeenCalledWith("i-1");
    expect(onNotice).toHaveBeenCalledWith("Invitation sent to new@clinic.example.");
  });
});
