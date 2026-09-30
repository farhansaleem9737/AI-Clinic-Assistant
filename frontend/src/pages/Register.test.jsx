import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../context/AuthContext";
import AuthLayout from "../layouts/AuthLayout";
import api, { mayHaveSession, refreshAccessToken } from "../services/api";
import { splitFullName } from "../utils/validation";
import LegalDocument from "./LegalDocument";
import Login from "./Login";
import Register from "./Register";

// Only the HTTP boundary is replaced: the real AuthProvider, routing and
// pages run as they do in the app.
vi.mock("../services/api", () => ({
  default: { post: vi.fn(), get: vi.fn() },
  csrfHeaders: vi.fn(() => ({})),
  mayHaveSession: vi.fn(() => false),
  refreshAccessToken: vi.fn(),
  setAccessToken: vi.fn(),
  setSessionExpiredHandler: vi.fn(),
  getErrorMessage: (err, fallback) => err?.response?.data?.error?.message ?? fallback,
}));

const USER = { id: "u-1", name: "Amina Khan", email: "amina@example.com", roles: ["patient"], permissions: [] };
const httpError = (status, code, details) => ({
  response: { status, data: { error: { code, message: "internal detail: ix_users_email", details } } },
});

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname}</p>;
}

function renderRegister() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/register"]}>
        <Routes>
          <Route element={<AuthLayout variant="register" />}>
            <Route path="/register" element={<Register />} />
            <Route path="/terms" element={<LegalDocument document="terms" />} />
          </Route>
          <Route element={<AuthLayout variant="login" />}>
            <Route path="/login" element={<Login />} />
          </Route>
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  );
}

const field = {
  name: () => screen.getByLabelText("Full name"),
  dob: () => screen.getByLabelText("Date of birth"),
  email: () => screen.getByLabelText("Email address"),
  password: () => screen.getByLabelText("Password"),
  confirm: () => screen.getByLabelText("Confirm password"),
  agree: () => screen.getByRole("checkbox", { name: /I agree to the/ }),
};
const submit = () => screen.getByRole("button", { name: /^Create account|Creating account/ });

const VALID = { name: "Amina Khan", dob: "1990-05-17", email: "amina@example.com", password: "secret-123", confirm: "secret-123" };

async function fill(values = VALID, { agree = true } = {}) {
  for (const [key, value] of Object.entries(values)) {
    if (value) await userEvent.type(field[key](), value);
  }
  if (agree) await userEvent.click(field.agree());
}

beforeEach(() => {
  vi.resetAllMocks();
  mayHaveSession.mockReturnValue(false);
  api.post.mockResolvedValue({ data: { access_token: "token" } });
  api.get.mockResolvedValue({ data: USER });
  localStorage.clear();
  sessionStorage.clear();
});

describe("splitFullName", () => {
  it("uses the last word as the family name and keeps any script", () => {
    expect(splitFullName("  Amina   Khan ")).toEqual({ first_name: "Amina", last_name: "Khan" });
    expect(splitFullName("José María Nguyễn-O'Brien")).toEqual({ first_name: "José María", last_name: "Nguyễn-O'Brien" });
    expect(splitFullName("秀英 李")).toEqual({ first_name: "秀英", last_name: "李" });
  });

  it("needs at least two words", () => {
    expect(splitFullName("Madonna")).toBeNull();
    expect(splitFullName("   ")).toBeNull();
  });
});

describe("rendering", () => {
  it("shows the create-account form with labelled fields and correct autocomplete", () => {
    renderRegister();
    expect(screen.getByRole("heading", { name: "Create your account" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Your Health.Our Priority.");
    expect(field.name()).toHaveAttribute("autocomplete", "name");
    expect(field.email()).toHaveAttribute("type", "email");
    expect(field.password()).toHaveAttribute("autocomplete", "new-password");
    expect(field.confirm()).toHaveAttribute("autocomplete", "new-password");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });

  it("shows the three benefits and offers no role choice", () => {
    renderRegister();
    for (const title of ["Trusted Doctors", "Easy Appointments", "Better Care"]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
    expect(screen.queryByLabelText(/role/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("does not pre-tick consent, and links to the legal pages", () => {
    renderRegister();
    expect(field.agree()).not.toBeChecked();
    expect(screen.getByRole("link", { name: "Terms of Service" })).toHaveAttribute("href", "/terms");
    expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute("href", "/privacy");
  });

  it("offers Google and Microsoft only as unavailable", () => {
    renderRegister();
    expect(screen.getByRole("button", { name: /Continue with Google/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Continue with Microsoft/ })).toBeDisabled();
  });
});

describe("validation", () => {
  it("reports every problem next to its field and sends nothing", async () => {
    renderRegister();
    await userEvent.click(submit());
    expect(screen.getByText("Enter your full name.")).toBeInTheDocument();
    expect(screen.getByText("Enter your date of birth.")).toBeInTheDocument();
    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByText("Create a password.")).toBeInTheDocument();
    expect(screen.getByText("Confirm your password.")).toBeInTheDocument();
    expect(screen.getByText(/You must agree to the Terms of Service and Privacy Policy/)).toBeInTheDocument();
    expect(field.name()).toHaveAttribute("aria-invalid", "true");
    expect(field.name()).toHaveAttribute("aria-describedby", "register-name-error");
    expect(api.post).not.toHaveBeenCalled();
  });

  it("asks for first and last name", async () => {
    renderRegister();
    await fill({ ...VALID, name: "Madonna" });
    await userEvent.click(submit());
    expect(screen.getByText("Enter your first and last name.")).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("rejects a malformed email and a short password", async () => {
    renderRegister();
    await fill({ ...VALID, email: "not-an-email", password: "short", confirm: "short" });
    await userEvent.click(submit());
    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByText("Use at least 8 characters.")).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("requires the passwords to match", async () => {
    renderRegister();
    await fill({ ...VALID, confirm: "different-123" });
    await userEvent.click(submit());
    expect(screen.getByText("Passwords do not match.")).toBeInTheDocument();
    expect(field.confirm()).toHaveAttribute("aria-invalid", "true");
    expect(api.post).not.toHaveBeenCalled();
  });

  it("requires explicit consent", async () => {
    renderRegister();
    await fill(VALID, { agree: false });
    await userEvent.click(submit());
    expect(screen.getByText(/You must agree to the Terms of Service and Privacy Policy/)).toBeInTheDocument();
    expect(field.agree()).toHaveAttribute("aria-invalid", "true");
    expect(api.post).not.toHaveBeenCalled();
  });

  it("clears a field error once the field is edited", async () => {
    renderRegister();
    await userEvent.click(submit());
    await userEvent.type(field.name(), "A");
    expect(screen.queryByText("Enter your full name.")).not.toBeInTheDocument();
  });
});

describe("password visibility", () => {
  it("each password field toggles independently without losing its value", async () => {
    renderRegister();
    await userEvent.type(field.password(), "secret-123");
    await userEvent.type(field.confirm(), "secret-123");
    const [showPassword, showConfirm] = screen.getAllByRole("button", { name: "Show password" });

    await userEvent.click(showPassword);
    expect(field.password()).toHaveAttribute("type", "text");
    expect(field.password()).toHaveValue("secret-123");
    expect(field.confirm()).toHaveAttribute("type", "password");

    await userEvent.click(showConfirm);
    expect(field.confirm()).toHaveAttribute("type", "text");
    expect(api.post).not.toHaveBeenCalled(); // toggles never submit
    expect(screen.getAllByRole("button", { name: "Hide password" })).toHaveLength(2);
  });
});

describe("creating an account", () => {
  it("sends only the registration fields, signs in, and lands on the dashboard", async () => {
    renderRegister();
    await fill({ ...VALID, name: "  Amina  Bibi Khan ", email: " amina@example.com " });
    await userEvent.click(submit());
    expect(await screen.findByTestId("where")).toHaveTextContent("/dashboard");

    expect(api.post).toHaveBeenNthCalledWith(1, "/auth/register", {
      first_name: "Amina Bibi",
      last_name: "Khan",
      date_of_birth: "1990-05-17",
      email: "amina@example.com",
      password: "secret-123",
    });
    // No role, no consent flag, no password confirmation leave the browser.
    const sent = api.post.mock.calls[0][1];
    for (const forbidden of ["role", "roles", "permissions", "confirm_password", "confirmPassword", "agreed", "mrn"]) {
      expect(sent).not.toHaveProperty(forbidden);
    }
    // Established lifecycle: register, then log in (session cookie, not remembered).
    expect(api.post).toHaveBeenNthCalledWith(2, "/auth/login", {
      email: "amina@example.com",
      password: "secret-123",
      remember_me: false,
    });
  });

  it("stores nothing in browser storage", async () => {
    renderRegister();
    await fill();
    await userEvent.click(submit());
    await screen.findByTestId("where");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("disables the button while submitting and ignores repeated submits", async () => {
    let finish;
    api.post.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
    renderRegister();
    await fill();
    await userEvent.click(submit());

    expect(submit()).toBeDisabled();
    expect(submit()).toHaveTextContent("Creating account…");
    await userEvent.type(field.confirm(), "{Enter}");
    expect(api.post).toHaveBeenCalledOnce();

    finish({ data: {} });
    expect(await screen.findByTestId("where")).toHaveTextContent("/dashboard");
  });

  it("pressing Enter in a field submits the form", async () => {
    renderRegister();
    await fill();
    await userEvent.type(field.confirm(), "{Enter}");
    expect(await screen.findByTestId("where")).toHaveTextContent("/dashboard");
  });
});

describe("failures", () => {
  it("duplicate email: a field message that points to sign-in, no server internals", async () => {
    api.post.mockRejectedValueOnce(httpError(409, "EMAIL_TAKEN"));
    renderRegister();
    await fill();
    await userEvent.click(submit());
    expect(await screen.findByText(/An account with this email already exists/)).toBeInTheDocument();
    expect(field.email()).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText(/ix_users_email|internal detail/)).not.toBeInTheDocument();
    expect(submit()).toBeEnabled();
  });

  it("maps backend validation errors to their fields", async () => {
    api.post.mockRejectedValueOnce(
      httpError(422, "VALIDATION_ERROR", { errors: [{ loc: ["body", "password"], msg: "x" }, { loc: ["body", "last_name"], msg: "y" }] })
    );
    renderRegister();
    await fill();
    await userEvent.click(submit());
    expect(await screen.findByText("Use 8 to 128 characters.")).toBeInTheDocument();
    expect(screen.getByText("Enter your first and last name.")).toBeInTheDocument();
  });

  it("network failure is reported as such, not as bad input", async () => {
    api.post.mockRejectedValueOnce(new Error("Network Error"));
    renderRegister();
    await fill();
    await userEvent.click(submit());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("We couldn't create your account right now. Please try again.");
    expect(screen.queryByText(/valid email|already exists/)).not.toBeInTheDocument();
    expect(field.email()).toHaveValue("amina@example.com"); // nothing the user typed is lost
  });

  it("server error shows the same safe message", async () => {
    api.post.mockRejectedValueOnce(httpError(500, "INTERNAL_ERROR"));
    renderRegister();
    await fill();
    await userEvent.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't create your account right now");
  });

  it("account created but automatic sign-in failed: go to sign-in with a notice", async () => {
    api.post.mockResolvedValueOnce({ data: {} }).mockRejectedValueOnce(new Error("Network Error"));
    renderRegister();
    await fill();
    await userEvent.click(submit());
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(screen.getByText("Your account was created. Please sign in.")).toBeInTheDocument();
  });
});

describe("navigation", () => {
  it("Sign in goes to the login page without a reload", async () => {
    renderRegister();
    await userEvent.click(screen.getByRole("link", { name: "Sign in" }));
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
  });

  it("a signed-in visitor is sent to the dashboard instead of the form", async () => {
    mayHaveSession.mockReturnValue(true);
    refreshAccessToken.mockResolvedValue("token");
    renderRegister();
    expect(await screen.findByTestId("where")).toHaveTextContent("/dashboard");
  });

  it("the legal pages say plainly that the documents are not published", () => {
    render(
      <MemoryRouter initialEntries={["/terms"]}>
        <Routes>
          <Route path="/terms" element={<LegalDocument document="terms" />} />
        </Routes>
      </MemoryRouter>
    );
    expect(screen.getByRole("heading", { name: "Terms of Service" })).toBeInTheDocument();
    expect(within(document.body).getByText("This document has not been published yet.")).toBeInTheDocument();
  });
});
