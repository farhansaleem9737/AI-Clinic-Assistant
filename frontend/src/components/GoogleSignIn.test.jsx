import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import GoogleComplete from "../pages/GoogleComplete";
import GoogleSignup from "../pages/GoogleSignup";
import { getPublicDepartments } from "../services/departmentService";
import {
  completeGoogleSignIn,
  getGoogleIdentity,
  getGoogleSignup,
  getSignInProviders,
  googleSignup,
  linkGoogle,
  unlinkGoogle,
} from "../services/googleAuthService";
import ConnectedAccounts from "./account/ConnectedAccounts";
import SocialSignIn from "./SocialSignIn";

vi.mock("../context/useAuth");
vi.mock("../services/departmentService");
vi.mock("../services/googleAuthService", async (original) => {
  const real = await original();
  return {
    ...real,
    getSignInProviders: vi.fn(),
    completeGoogleSignIn: vi.fn(),
    getGoogleSignup: vi.fn(),
    googleSignup: vi.fn(),
    getGoogleIdentity: vi.fn(),
    linkGoogle: vi.fn(),
    unlinkGoogle: vi.fn(),
  };
});

const assign = vi.fn();
const signInWithToken = vi.fn();

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname}</p>;
}

function at(path, element) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={path.split("?")[0]} element={element} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal("location", { ...window.location, assign });
  useAuth.mockReturnValue({ signInWithToken });
  signInWithToken.mockResolvedValue({});
});
afterEach(() => vi.unstubAllGlobals());

describe("Continue with Google button", () => {
  it("goes to the backend's Google start, once, carrying Remember me", async () => {
    getSignInProviders.mockResolvedValue({ data: { google: true } });
    at("/login", <SocialSignIn intent="login" remember />);
    const button = await screen.findByRole("button", { name: /Continue with Google/ });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    await userEvent.click(screen.getByRole("button", { name: /Opening Google/ }));
    expect(assign).toHaveBeenCalledTimes(1);
    expect(assign.mock.calls[0][0]).toMatch(/\/auth\/google\/start\?intent=login&remember=true$/);
  });

  it("is unavailable until the clinic configures it, and explains Google's answers", async () => {
    getSignInProviders.mockResolvedValue({ data: { google: false } });
    at("/login?google=link_required", <SocialSignIn />);
    expect(await screen.findByText("Google sign-in is not set up for this clinic yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Continue with Google/ })).toBeDisabled();
    expect(screen.getByText(/An account with this email address already exists/)).toBeInTheDocument();
  });

  it("says Sign up with Google on the registration page", async () => {
    getSignInProviders.mockResolvedValue({ data: { google: true } });
    at("/register", <SocialSignIn intent="register" />);
    expect(await screen.findByRole("button", { name: /Sign up with Google/ })).toBeInTheDocument();
  });
});

describe("after Google", () => {
  it("a known account finishes its session and goes home", async () => {
    completeGoogleSignIn.mockResolvedValue({ data: { access_token: "tok" } });
    at("/auth/google/complete", <GoogleComplete />);
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/dashboard"));
    expect(signInWithToken).toHaveBeenCalledWith("tok");
    expect(completeGoogleSignIn).toHaveBeenCalledTimes(1);
  });

  it("a used or expired handoff says so instead of signing in", async () => {
    completeGoogleSignIn.mockRejectedValue({ response: { status: 400, data: { error: { code: "GOOGLE_STATE_INVALID" } } } });
    at("/auth/google/complete", <GoogleComplete />);
    expect(await screen.findByText(/expired or was already used/)).toBeInTheDocument();
    expect(signInWithToken).not.toHaveBeenCalled();
  });

  it("a new person completes the patient form without a password", async () => {
    getGoogleSignup.mockResolvedValue({ data: { email: "nadia@gmail.com", given_name: "Nadia", family_name: "Noor" } });
    googleSignup.mockResolvedValue({ data: { access_token: "new" } });
    const user = userEvent.setup();
    at("/register/google", <GoogleSignup />);
    expect(await screen.findByDisplayValue("nadia@gmail.com")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Full name")).toHaveValue("Nadia Noor");
    expect(screen.queryByLabelText(/Password/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByText(/You must agree to the Terms/)).toBeInTheDocument();
    expect(googleSignup).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Date of birth"), "1990-05-01");
    await user.selectOptions(screen.getByLabelText("Gender"), "female");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(googleSignup).toHaveBeenCalledTimes(1));
    const body = googleSignup.mock.calls[0][0];
    expect(body).toEqual({ account_type: "patient", first_name: "Nadia", last_name: "Noor", date_of_birth: "1990-05-01", sex_at_birth: "female" });
    expect(signInWithToken).toHaveBeenCalledWith("new");
  });

  it("offers only Patient or a reviewed Doctor application", async () => {
    getGoogleSignup.mockResolvedValue({ data: { email: "d@gmail.com", given_name: null, family_name: null } });
    getPublicDepartments.mockResolvedValue({ data: { items: [] } });
    at("/register/google", <GoogleSignup />);
    const type = await screen.findByLabelText("Account Type");
    expect([...type.options].map((o) => o.value)).toEqual(["patient", "doctor"]);
  });

  it("an expired sign-up ticket asks to start again", async () => {
    getGoogleSignup.mockRejectedValue({ response: { status: 400 } });
    at("/register/google", <GoogleSignup />);
    expect(await screen.findByText(/expired or was already completed/)).toBeInTheDocument();
  });
});

describe("Connected accounts", () => {
  it("linking asks for the password when the sign-in is not recent, then goes to Google", async () => {
    getGoogleIdentity.mockResolvedValue({ data: { enabled: true, linked: false, email: null, has_password: true } });
    linkGoogle
      .mockRejectedValueOnce({ response: { status: 403, data: { error: { code: "REAUTHENTICATION_REQUIRED" } } } })
      .mockResolvedValueOnce({ data: { authorize_url: "https://accounts.google.com/o/oauth2/v2/auth?x" } });
    const user = userEvent.setup();
    at("/account", <ConnectedAccounts />);
    await user.click(await screen.findByRole("button", { name: "Link Google account" }));
    await user.type(await screen.findByLabelText(/Your password/), "secret-pass");
    await user.click(screen.getByRole("button", { name: "Continue to Google" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://accounts.google.com/o/oauth2/v2/auth?x"));
    expect(linkGoogle).toHaveBeenLastCalledWith("secret-pass");
  });

  it("Google cannot be unlinked while it is the only way to sign in", async () => {
    getGoogleIdentity.mockResolvedValue({ data: { enabled: true, linked: true, email: "me@gmail.com", has_password: false } });
    at("/account?google=linked", <ConnectedAccounts />);
    expect(await screen.findByText(/connected as me@gmail.com/)).toBeInTheDocument();
    expect(screen.getByText(/Your Google account is now linked/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unlink Google" })).not.toBeInTheDocument();
    expect(unlinkGoogle).not.toHaveBeenCalled();
  });
});
