import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { cancelGoogleLink, getGoogleLinkTicket, sendGoogleLinkCode, verifyGoogleLink } from "../services/googleAuthService";
import GoogleLink, { LINKED } from "./GoogleLink";

vi.mock("../services/googleAuthService");
const signInWithToken = vi.fn();
vi.mock("../context/useAuth", () => ({ useAuth: () => ({ signInWithToken }) }));

const ticket = (overrides = {}) => ({
  data: { email: "alice@example.com", methods: ["password", "email_code"], code_sent: false, resend_in: 0, attempts_left: 5, ...overrides },
});
const refused = (code, details) => ({ response: { status: 400, data: { error: { code, message: "internal", details } } } });

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function show() {
  return render(
    <MemoryRouter initialEntries={["/login/link-google"]}>
      <Routes>
        <Route path="/login/link-google" element={<GoogleLink />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  signInWithToken.mockResolvedValue(undefined);
});

describe("Link your Google account", () => {
  it("links with the password, signs in, and only then says so", async () => {
    getGoogleLinkTicket.mockResolvedValue(ticket());
    verifyGoogleLink
      .mockRejectedValueOnce(refused("LINK_PROOF_INVALID", { attempts_left: 4 }))
      .mockResolvedValueOnce({ data: { access_token: "access" } });
    const user = userEvent.setup();
    show();
    expect(await screen.findByRole("heading", { name: "Link your Google account" })).toBeInTheDocument();
    expect(screen.getByText(/An account already exists with this email address/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Verify and link Google" }));
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(verifyGoogleLink).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Password for this account"), "wrong one");
    await user.click(screen.getByRole("button", { name: "Verify and link Google" }));
    expect(await screen.findByText("The password is incorrect. 4 tries left.")).toBeInTheDocument();
    expect(screen.queryByText("internal")).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText("Password for this account"));
    await user.type(screen.getByLabelText("Password for this account"), "right one");
    await user.click(screen.getByRole("button", { name: "Verify and link Google" }));
    expect(await screen.findByText(new RegExp(LINKED))).toBeInTheDocument();
    expect(verifyGoogleLink).toHaveBeenLastCalledWith({ password: "right one" });
    expect(signInWithToken).toHaveBeenCalledWith("access");
    await user.click(screen.getByRole("button", { name: "Continue to your dashboard" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/dashboard");
  });

  it("links with an emailed code", async () => {
    getGoogleLinkTicket.mockResolvedValue(ticket());
    sendGoogleLinkCode.mockResolvedValue({});
    verifyGoogleLink.mockResolvedValue({ data: { access_token: "access" } });
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("radio", { name: "Email code" }));
    await user.click(screen.getByRole("button", { name: "Send code" }));
    expect(await screen.findByText("We sent a 6-digit code to alice@example.com.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Resend code in/ })).toBeDisabled();
    await user.keyboard("123456");
    await waitFor(() => expect(verifyGoogleLink).toHaveBeenCalledWith({ code: "123456" }));
    expect(await screen.findByText(new RegExp(LINKED))).toBeInTheDocument();
  });

  it("staff see the password only", async () => {
    getGoogleLinkTicket.mockResolvedValue(ticket({ methods: ["password"] }));
    show();
    expect(await screen.findByLabelText("Password for this account")).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Email code" })).not.toBeInTheDocument();
  });

  it("cancelling links nothing and goes back to sign in", async () => {
    getGoogleLinkTicket.mockResolvedValue(ticket());
    cancelGoogleLink.mockResolvedValue({});
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: /Don't link/ }));
    expect(cancelGoogleLink).toHaveBeenCalled();
    expect(verifyGoogleLink).not.toHaveBeenCalled();
    expect(screen.getByTestId("where")).toHaveTextContent("/login");
  });

  it("an expired or used-up step is explained", async () => {
    getGoogleLinkTicket.mockRejectedValue(refused("GOOGLE_STATE_INVALID"));
    show();
    expect(await screen.findByRole("heading", { name: "This step has expired" })).toBeInTheDocument();
    expect(signInWithToken).not.toHaveBeenCalled();
  });
});
