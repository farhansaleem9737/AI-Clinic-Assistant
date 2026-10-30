import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import AppLayout from "../layouts/AppLayout";
import { getPublicDepartments } from "../services/departmentService";
import { getUnreadCount } from "../services/workspaceService";
import { authAs, PERMISSIONS } from "../test/fixtures";
import Departments from "./Departments";

vi.mock("../context/useAuth");
vi.mock("../services/departmentService");
vi.mock("../services/workspaceService");

const doc = (id, name) => ({ id, name, title: "Dr.", photo_url: null });
const card = (id, name, overrides = {}) => ({ id, name, description: null, icon: null, color: null, doctor_count: 0, doctors_preview: [], ...overrides });
const CARDIO = card("dep-1", "Cardiology", {
  description: "Heart care and cardiovascular health services.",
  doctor_count: 8,
  doctors_preview: [doc("d1", "Ali Raza"), doc("d2", "Sara Khan"), doc("d3", "Omar Shah")],
});
const NEURO = card("dep-2", "Neurology", { description: "Brain, spine and nervous system care.", doctor_count: 1, doctors_preview: [doc("d4", "Hina Malik")] });
const EMPTY = card("dep-3", "Radiology");
const page = (items, total = items.length) => ({ data: { items, total, page: 1, page_size: 12, total_pages: Math.max(1, Math.ceil(total / 12)) } });

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderPage({ inShell = false } = {}) {
  const auth = authAs("Moiz Rasheed", ["patient"], PERMISSIONS.patient);
  useAuth.mockReturnValue(auth);
  const pageEl = <Departments />;
  return render(
    <MemoryRouter initialEntries={["/departments"]}>
      <Routes>
        {inShell ? (
          <Route element={<AppLayout />}>
            <Route path="/departments" element={pageEl} />
          </Route>
        ) : (
          <Route path="/departments" element={pageEl} />
        )}
        <Route path="/doctors" element={<p>Doctors directory</p>} />
      </Routes>
      <Where />
    </MemoryRouter>
  );
}
const cardOf = async (name) => (await screen.findByRole("listitem", { name })).closest("li");
const lastParams = () => getPublicDepartments.mock.calls.at(-1)[0];

beforeEach(() => {
  vi.resetAllMocks();
  getPublicDepartments.mockResolvedValue(page([CARDIO, NEURO, EMPTY]));
  getUnreadCount.mockResolvedValue({ data: { unread: 0 } });
});

describe("Patient Departments", () => {
  it("renders the heading and a card per active department from the API", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Departments" })).toBeInTheDocument();
    expect(screen.getByText("Explore our clinic departments and find the right care for your needs.")).toBeInTheDocument();
    const cardio = await cardOf("Cardiology");
    expect(cardio).toHaveTextContent("Heart care and cardiovascular health services.");
    expect(cardio).toHaveTextContent("+5");
    expect(cardio).toHaveTextContent("8 doctors");
    expect(cardio.querySelectorAll(".avatar-stack-item")).toHaveLength(3);
    expect(cardio.querySelector("img")).toBeNull(); // illustrated avatars, never stock photos
    expect(await cardOf("Neurology")).toHaveTextContent("1 doctor");
    const empty = await cardOf("Radiology");
    expect(empty).toHaveTextContent("0 doctors");
    expect(empty).toHaveTextContent("No description available.");
    expect(lastParams()).toEqual({ page: 1, page_size: 12 });
  });

  it("is read-only: no add, edit, status or actions", async () => {
    renderPage();
    await cardOf("Cardiology");
    expect(screen.queryByRole("button", { name: /Add Department/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Actions for/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
  });

  it("View Doctors opens the directory filtered to that department", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(within(await cardOf("Cardiology")).getByRole("link", { name: "View doctors in Cardiology" }));
    expect(screen.getByText("Doctors directory")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/doctors?department=dep-1");
  });

  it("searches on the server after a pause and can clear", async () => {
    const user = userEvent.setup();
    renderPage();
    await cardOf("Cardiology");
    getPublicDepartments.mockResolvedValue(page([]));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search departments" }), { target: { value: "skin" } });
    await waitFor(() => expect(lastParams()).toEqual({ page: 1, page_size: 12, q: "skin" }));
    expect(await screen.findByText("No departments match “skin”.")).toBeInTheDocument();
    getPublicDepartments.mockResolvedValue(page([CARDIO]));
    await user.click(screen.getByRole("button", { name: "Clear search" }));
    await waitFor(() => expect(lastParams()).toEqual({ page: 1, page_size: 12 }));
    expect(screen.getByRole("searchbox", { name: "Search departments" })).toHaveValue("");
  });

  it("shows loading, then an empty clinic", async () => {
    let resolve;
    getPublicDepartments.mockReturnValue(new Promise((r) => (resolve = r)));
    renderPage();
    expect(screen.getByRole("status", { name: "Loading departments" })).toBeInTheDocument();
    resolve(page([]));
    expect(await screen.findByText("No departments are listed yet.")).toBeInTheDocument();
  });

  it("explains a failure and retries", async () => {
    getPublicDepartments.mockRejectedValueOnce({ response: { data: { error: { message: "Service unavailable" } } } });
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await cardOf("Cardiology")).toBeInTheDocument();
  });

  it("inside the patient's own shell, Departments is the active item", async () => {
    renderPage({ inShell: true });
    await cardOf("Cardiology");
    const nav = within(screen.getByRole("complementary", { name: "Main navigation" })).getByRole("navigation");
    const active = within(nav).getByRole("link", { name: "Departments" });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(within(nav).queryByRole("link", { name: "Users" })).not.toBeInTheDocument(); // not the admin sidebar
  });
});
