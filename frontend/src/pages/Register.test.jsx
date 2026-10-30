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
  type: () => screen.getByLabelText("Account Type"),
  name: () => screen.getByLabelText("Full name"),
  dob: () => screen.getByLabelText("Date of birth"),
  email: () => screen.getByLabelText("Email address"),
  password: () => screen.getByLabelText("Password"),
  confirm: () => screen.getByLabelText("Confirm password"),
  agree: () => screen.getByRole("checkbox", { name: /I agree to the/ }),
};
const submit = () => screen.getByRole("button", { name: /^Create account|Creating account/ });

const VALID = { name: "Amina Khan", dob: "1990-05-17", email: "amina@example.com", password: "secret-123", confirm: "secret-123" };

async function fill(values = VALID, { agree = true, type = "patient" } = {}) {
  if (type) await userEvent.selectOptions(field.type(), type);
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

  it("shows the three benefits and offers only Patient or Doctor as the account type", () => {
    renderRegister();
    for (const title of ["Trusted Doctors", "Easy Appointments", "Better Care"]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
    expect(screen.queryByLabelText(/role/i)).not.toBeInTheDocument();
    const type = field.type();
    expect(type).toHaveValue("");
    expect(within(type).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Select your account type",
      "Patient",
      "Doctor",
    ]);
    expect(within(type).getByRole("option", { name: "Select your account type" })).toBeDisabled();
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
    expect(screen.getByText("Choose an account type.")).toBeInTheDocument();
    expect(field.type()).toHaveAttribute("aria-invalid", "true");
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
      account_type: "patient",
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

describe("registering as a doctor", () => {
  const DEPARTMENTS = [
    { id: "dep-1", name: "Cardiology" },
    { id: "dep-2", name: "Neurology" },
  ];
  const DOCTOR = { name: "Sara Malik", email: "sara@example.com", password: "secret-123", confirm: "secret-123" };
  const pdf = (name = "pmdc.pdf", size = 1000) => new File([new Uint8Array(size)], name, { type: "application/pdf" });

  beforeEach(() => {
    api.get.mockImplementation((url) =>
      Promise.resolve(url.startsWith("/public/departments") ? { data: { items: DEPARTMENTS } } : { data: USER })
    );
  });

  const chooseDoctor = () => userEvent.selectOptions(field.type(), "doctor");

  it("shows the professional sections only for doctors, without a date of birth", async () => {
    renderRegister();
    expect(screen.queryByRole("region", { name: "Professional Information" })).not.toBeInTheDocument();
    await chooseDoctor();
    expect(screen.getByRole("region", { name: "Professional Information" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Professional Verification Documents" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Date of birth")).not.toBeInTheDocument();
    // Every professional field says it is optional, and none is required.
    for (const label of [/Medical License Number/, /Specialization/, /^Department/, /Years of Experience/, /Consultation Fee/]) {
      const control = screen.getByLabelText(label);
      expect(control).not.toBeRequired();
      expect(document.querySelector(`label[for="${control.id}"]`)).toHaveTextContent("(optional)");
    }
    expect(await screen.findByRole("option", { name: "Cardiology" })).toBeInTheDocument();
    expect(screen.getByText(/You can also provide these later/)).toBeInTheDocument();
  });

  it("keeps the common fields when switching account type", async () => {
    renderRegister();
    await chooseDoctor();
    await userEvent.type(field.name(), "Sara Malik");
    await userEvent.type(field.email(), "sara@example.com");
    await userEvent.selectOptions(field.type(), "patient");
    expect(field.name()).toHaveValue("Sara Malik");
    expect(field.email()).toHaveValue("sara@example.com");
    expect(screen.getByLabelText("Date of birth")).toBeInTheDocument();
  });

  it("creates the account with basic information only and explains the pending review", async () => {
    renderRegister();
    await fill(DOCTOR, { type: "doctor" });
    await userEvent.click(submit());

    expect(await screen.findByRole("heading", { name: "Doctor Account Created" })).toBeInTheDocument();
    expect(screen.getByText(/pending verification/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue to my application" })).toHaveAttribute("href", "/doctor/application");
    expect(api.post).toHaveBeenNthCalledWith(1, "/auth/register", {
      account_type: "doctor",
      name: "Sara Malik",
      email: "sara@example.com",
      password: "secret-123",
    });
    // Register and sign in, nothing else: no documents were chosen.
    expect(api.post).toHaveBeenCalledTimes(2);
  });

  it("sends the optional details given and uploads the chosen documents after signing in", async () => {
    renderRegister();
    await fill(DOCTOR, { type: "doctor" });
    await userEvent.type(screen.getByLabelText(/Medical License Number/), " PMC-1 ");
    await screen.findByRole("option", { name: "Neurology" });
    await userEvent.selectOptions(screen.getByLabelText(/^Department/), "dep-2");
    await userEvent.type(screen.getByLabelText(/Years of Experience/), "7");
    await userEvent.type(screen.getByLabelText(/Consultation Fee/), "2000");
    await userEvent.upload(screen.getByLabelText("Medical Registration Certificate file"), pdf());
    expect(screen.getByText("pmdc.pdf")).toBeInTheDocument();
    await userEvent.click(submit());

    expect(await screen.findByText(/^uploaded$/)).toBeInTheDocument();
    expect(api.post.mock.calls[0][1]).toEqual({
      account_type: "doctor",
      name: "Sara Malik",
      email: "sara@example.com",
      password: "secret-123",
      license_number: "PMC-1",
      department_id: "dep-2",
      years_of_experience: 7,
      consultation_fee: "2000",
    });
    const [url, body] = api.post.mock.calls[2];
    expect(url).toBe("/doctor-applications/me/documents");
    expect(body.get("document_type")).toBe("registration_certificate");
    expect(body.get("file").name).toBe("pmdc.pdf");
  });

  it("says honestly when a document could not be uploaded", async () => {
    api.post
      .mockResolvedValueOnce({ data: {} })
      .mockResolvedValueOnce({ data: { access_token: "token" } })
      .mockRejectedValueOnce({ response: { status: 503, data: { error: { code: "STORAGE_NOT_CONFIGURED" } } } });
    renderRegister();
    await fill(DOCTOR, { type: "doctor" });
    await userEvent.upload(screen.getByLabelText("Medical Degree / Qualification Certificate file"), pdf("degree.pdf"));
    await userEvent.click(submit());
    expect(await screen.findByRole("heading", { name: "Doctor Account Created" })).toBeInTheDocument();
    expect(screen.getByText(/not uploaded\. Document storage is not available right now\./)).toBeInTheDocument();
    expect(screen.getByText(/upload these documents again/)).toBeInTheDocument();
  });

  it("rejects files of the wrong type or size before anything is sent", async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderRegister();
    await chooseDoctor();
    const input = screen.getByLabelText("Additional Supporting Document file");
    await user.upload(input, new File(["MZ"], "setup.exe", { type: "application/x-msdownload" }));
    expect(screen.getByText("Choose a PDF, JPG, JPEG or PNG file.")).toBeInTheDocument();
    await user.upload(input, pdf("huge.pdf", 20 * 1024 * 1024 + 1));
    expect(screen.getByText(/The file must be .* or smaller\./)).toBeInTheDocument();
    expect(screen.queryByText("huge.pdf")).not.toBeInTheDocument();
  });

  it("can remove a chosen document before submitting", async () => {
    renderRegister();
    await fill(DOCTOR, { type: "doctor" });
    await userEvent.upload(screen.getByLabelText("Medical Registration Certificate file"), pdf());
    await userEvent.click(screen.getByRole("button", { name: "Remove Medical Registration Certificate" }));
    expect(screen.queryByText("pmdc.pdf")).not.toBeInTheDocument();
    await userEvent.click(submit());
    await screen.findByRole("heading", { name: "Doctor Account Created" });
    expect(api.post).toHaveBeenCalledTimes(2);
  });

  it("checks optional values only when they are given", async () => {
    renderRegister();
    await fill(DOCTOR, { type: "doctor" });
    await userEvent.type(screen.getByLabelText(/Years of Experience/), "90");
    await userEvent.click(submit());
    expect(screen.getByText("Enter whole years from 0 to 80.")).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("never sends doctor details with a patient registration", async () => {
    renderRegister();
    await chooseDoctor();
    await userEvent.type(screen.getByLabelText(/Medical License Number/), "PMC-9");
    await userEvent.upload(screen.getByLabelText("Medical Registration Certificate file"), pdf());
    await fill(VALID, { type: "patient" });
    await userEvent.click(submit());
    expect(await screen.findByTestId("where")).toHaveTextContent("/dashboard");
    const sent = api.post.mock.calls[0][1];
    expect(sent.account_type).toBe("patient");
    expect(sent).not.toHaveProperty("license_number");
    expect(sent).not.toHaveProperty("name");
    expect(api.post.mock.calls.map(([url]) => url)).toEqual(["/auth/register", "/auth/login"]);
  });

  it("moves to the first problem when the form is submitted with a mistake", async () => {
    renderRegister();
    await fill({ ...DOCTOR, email: "not-an-email" }, { type: "doctor" });
    await userEvent.click(submit());
    expect(field.email()).toHaveAttribute("aria-invalid", "true");
    expect(field.email()).toHaveFocus();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("shows a visible message when the server rejects a doctor request with patient-only errors", async () => {
    // What a server without doctor sign-up answers: it expects a patient.
    api.post.mockRejectedValueOnce(
      httpError(422, "VALIDATION_ERROR", {
        errors: [
          { loc: ["body", "first_name"], msg: "Field required" },
          { loc: ["body", "date_of_birth"], msg: "Field required" },
        ],
      })
    );
    renderRegister();
    await fill(DOCTOR, { type: "doctor" });
    await userEvent.click(submit());
    const alert = await screen.findByText("Please check your details and try again.");
    expect(alert.closest(".register-form-alert")).toHaveFocus();
    expect(screen.queryByText("Enter your first and last name.")).not.toBeInTheDocument();
    expect(submit()).toBeEnabled();
  });

  it("puts a server department error under the department field", async () => {
    api.post.mockRejectedValueOnce(httpError(400, "DEPARTMENT_UNAVAILABLE", { field: "department_id" }));
    renderRegister();
    await fill(DOCTOR, { type: "doctor" });
    await userEvent.click(submit());
    expect(await screen.findByText("Choose one of the listed departments.")).toBeInTheDocument();
    expect(submit()).toBeEnabled();
  });
});
