import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../context/AuthContext";
import AuthLayout from "../layouts/AuthLayout";
import api, { mayHaveSession, refreshAccessToken } from "../services/api";
import ForgotPassword from "./ForgotPassword";
import Login from "./Login";

// Only the HTTP boundary is replaced: the real AuthProvider, routing and
// login page run as they do in the app.
vi.mock("../services/api", () => ({
  default: { post: vi.fn(), get: vi.fn() },
  csrfHeaders: vi.fn(() => ({})),
  mayHaveSession: vi.fn(() => false),
  refreshAccessToken: vi.fn(),
  setAccessToken: vi.fn(),
  setSessionExpiredHandler: vi.fn(),
  getErrorMessage: (err, fallback) => err?.response?.data?.error?.message ?? fallback,
}));

const USER = { id: "u-1", name: "John Doe", email: "john@example.com", roles: ["patient"], permissions: ["appointment:read_own"] };
const httpError = (status, code) => ({ response: { status, data: { error: { code, message: "internal detail" } } } });

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname}</p>;
}

function renderLogin(entry = "/login") {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route element={<AuthLayout />}>
            <Route path="/login" element={<Login />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
          </Route>
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  );
}

const email = () => screen.getByLabelText("Email address");
const password = () => screen.getByLabelText("Password");
const submit = () => screen.getByRole("button", { name: /^Sign in|Signing in/ });

async function fill(emailValue, passwordValue) {
  if (emailValue) await userEvent.type(email(), emailValue);
  if (passwordValue) await userEvent.type(password(), passwordValue);
}

beforeEach(() => {
  vi.resetAllMocks();
  mayHaveSession.mockReturnValue(false);
  api.post.mockResolvedValue({ data: { access_token: "token" } });
  api.get.mockResolvedValue({ data: USER });
  localStorage.clear();
  sessionStorage.clear();
});

describe("rendering", () => {
  it("shows the sign-in form with labelled fields and the expected links", () => {
    renderLogin();
    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Better Care.Smarter Tomorrow.");
    expect(email()).toHaveAttribute("type", "email");
    expect(email()).toHaveAttribute("autocomplete", "email");
    expect(password()).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByRole("checkbox", { name: "Remember me" })).toBeChecked();
    expect(screen.getByRole("link", { name: "Forgot password?" })).toHaveAttribute("href", "/forgot-password");
    expect(screen.getByRole("link", { name: "Create account" })).toHaveAttribute("href", "/register");
  });

  it("offers Google and Microsoft only as unavailable", () => {
    renderLogin();
    expect(screen.getByRole("button", { name: /Continue with Google/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Continue with Microsoft/ })).toBeDisabled();
    expect(screen.getByText(/not available yet/)).toBeInTheDocument();
  });

  it("the forgot-password page is honest that reset is not available", async () => {
    renderLogin();
    await userEvent.click(screen.getByRole("link", { name: "Forgot password?" }));
    expect(screen.getByText("Online password reset is not available yet.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Back to sign in/ })).toHaveAttribute("href", "/login");
  });
});

describe("validation", () => {
  it("rejects a malformed email without calling the server", async () => {
    renderLogin();
    await fill("not-an-email", "secret123");
    await userEvent.click(submit());
    const message = screen.getByText("Enter a valid email address.");
    expect(email()).toHaveAttribute("aria-invalid", "true");
    expect(email()).toHaveAttribute("aria-describedby", message.id);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("requires a password", async () => {
    renderLogin();
    await fill("john@example.com", "");
    await userEvent.click(submit());
    expect(screen.getByText("Password is required.")).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("clears a field error once the user edits the field", async () => {
    renderLogin();
    await userEvent.click(submit());
    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument();
    await userEvent.type(email(), "j");
    expect(screen.queryByText("Enter a valid email address.")).not.toBeInTheDocument();
  });
});

describe("password visibility", () => {
  it("toggles between hidden and shown without changing the value", async () => {
    renderLogin();
    await userEvent.type(password(), "secret123");
    expect(password()).toHaveAttribute("type", "password");

    await userEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(password()).toHaveAttribute("type", "text");
    expect(password()).toHaveValue("secret123");

    await userEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password()).toHaveAttribute("type", "password");
    expect(password()).toHaveValue("secret123");
  });

  it("the toggle is reachable by keyboard and does not submit the form", async () => {
    renderLogin();
    await userEvent.type(password(), "secret123");
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Show password" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(password()).toHaveAttribute("type", "text");
    expect(api.post).not.toHaveBeenCalled();
  });
});

describe("signing in", () => {
  it("sends the credentials once, then lands on the dashboard", async () => {
    renderLogin();
    await fill("  john@example.com ", "secret123");
    await userEvent.keyboard("{Enter}"); // Enter in the password field submits
    expect(await screen.findByTestId("where")).toHaveTextContent("/dashboard");
    expect(api.post).toHaveBeenCalledExactlyOnceWith("/auth/login", {
      email: "john@example.com",
      password: "secret123",
      remember_me: true,
    });
    expect(api.get).toHaveBeenCalledWith("/auth/me");
  });

  it("passes the Remember me choice through", async () => {
    renderLogin();
    await userEvent.click(screen.getByRole("checkbox", { name: "Remember me" }));
    await fill("john@example.com", "secret123");
    await userEvent.click(submit());
    await screen.findByTestId("where");
    expect(api.post.mock.calls[0][1].remember_me).toBe(false);
  });

  it("stores nothing in browser storage", async () => {
    renderLogin();
    await fill("john@example.com", "secret123");
    await userEvent.click(submit());
    await screen.findByTestId("where");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("disables the button while submitting and ignores repeated submits", async () => {
    let finish;
    api.post.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    renderLogin();
    await fill("john@example.com", "secret123");
    await userEvent.click(submit());

    expect(submit()).toBeDisabled();
    expect(submit()).toHaveTextContent("Signing in…");
    await userEvent.type(password(), "{Enter}");
    expect(api.post).toHaveBeenCalledOnce();

    finish({ data: { access_token: "token" } });
    expect(await screen.findByTestId("where")).toHaveTextContent("/dashboard");
  });

  it("returns to the page that required sign-in", async () => {
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={[{ pathname: "/login", state: { from: "/appointments" } }]}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );
    await fill("john@example.com", "secret123");
    await userEvent.click(submit());
    expect(await screen.findByTestId("where")).toHaveTextContent("/appointments");
  });

  it("ignores a return address outside the app", async () => {
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={[{ pathname: "/login", state: { from: "//evil.example/steal" } }]}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );
    await fill("john@example.com", "secret123");
    await userEvent.click(submit());
    expect(await screen.findByTestId("where")).toHaveTextContent("/dashboard");
  });
});

describe("failures", () => {
  it("shows one generic message for wrong credentials and never the server detail", async () => {
    api.post.mockRejectedValue(httpError(401, "INVALID_CREDENTIALS"));
    renderLogin();
    await fill("john@example.com", "wrong-password");
    await userEvent.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(screen.queryByText(/internal detail/)).not.toBeInTheDocument();
    expect(submit()).toBeEnabled();
    expect(screen.queryByTestId("where")).not.toBeInTheDocument();
  });

  it("tells a deactivated account to contact the clinic", async () => {
    api.post.mockRejectedValue(httpError(403, "ACCOUNT_INACTIVE"));
    renderLogin();
    await fill("john@example.com", "secret123");
    await userEvent.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent(/deactivated/);
  });

  it("reports a connection problem as such, not as bad credentials", async () => {
    api.post.mockRejectedValue(new Error("Network Error"));
    renderLogin();
    await fill("john@example.com", "secret123");
    await userEvent.click(submit());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/couldn't reach the server/);
    expect(alert).not.toHaveTextContent(/Invalid/);
  });

  it("reports a server error without internals", async () => {
    api.post.mockRejectedValue(httpError(500, "INTERNAL_ERROR"));
    renderLogin();
    await fill("john@example.com", "secret123");
    await userEvent.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent(/Something went wrong on our side/);
  });
});

describe("existing sessions", () => {
  it("does not flash the form while a session is being restored", () => {
    mayHaveSession.mockReturnValue(true);
    refreshAccessToken.mockReturnValue(new Promise(() => {}));
    renderLogin();
    expect(screen.getByRole("status")).toHaveTextContent("Checking your session…");
    expect(screen.queryByLabelText("Email address")).not.toBeInTheDocument();
  });

  it("sends an already signed-in user straight to the dashboard", async () => {
    mayHaveSession.mockReturnValue(true);
    refreshAccessToken.mockResolvedValue("token");
    renderLogin();
    expect(await screen.findByTestId("where")).toHaveTextContent("/dashboard");
    expect(api.post).not.toHaveBeenCalled();
  });

  it("shows the form when the stored session turns out to be expired", async () => {
    mayHaveSession.mockReturnValue(true);
    refreshAccessToken.mockRejectedValue(httpError(401, "INVALID_REFRESH_TOKEN"));
    renderLogin();
    await waitFor(() => expect(screen.getByLabelText("Email address")).toBeInTheDocument());
  });
});
