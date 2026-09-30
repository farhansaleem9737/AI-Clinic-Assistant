import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { getPublicDepartments } from "../services/departmentService";
import { getPublicDoctors, getPublicSpecializations } from "../services/doctorService";
import { anonymous, authAs, doctorsPage, PERMISSIONS, publicDoctor } from "../test/fixtures";
import Doctors from "./Doctors";

vi.mock("../context/useAuth");
vi.mock("../services/doctorService");
vi.mock("../services/departmentService");

const sarah = publicDoctor();
const robert = publicDoctor({
  id: "doc-2",
  name: "Robert Wilson",
  specialization: "Orthopedic Surgeon",
  department_id: "dep-2",
  department_name: "Orthopedics",
  years_of_experience: 15,
  consultation_fee: "170.00",
  is_verified: false,
  availability: { status: "unavailable", next_available: null },
});
const emily = publicDoctor({
  id: "doc-3",
  name: "Emily Carter",
  specialization: "Dermatologist",
  availability: { status: "busy", next_available: null },
});
const DEFAULTS = { page: 1, page_size: 6, sort: "name_asc" };
const apiError = (message) => ({ response: { data: { error: { code: "X", message } } } });

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderDirectory(initial = "/doctors", auth = anonymous) {
  useAuth.mockReturnValue(auth);
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route
          path="/doctors"
          element={
            <>
              <Doctors />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

const card = (name) => screen.findByRole("article", { name });
const lastRequest = () => getPublicDoctors.mock.calls.at(-1)[0];
const where = () => screen.getByTestId("where").textContent;

beforeEach(() => {
  vi.resetAllMocks();
  getPublicDoctors.mockResolvedValue(doctorsPage([sarah, robert, emily]));
  getPublicDepartments.mockResolvedValue({
    data: {
      items: [
        { id: "dep-1", name: "Cardiology" },
        { id: "dep-2", name: "Orthopedics" },
      ],
    },
  });
  getPublicSpecializations.mockResolvedValue({ data: ["Cardiologist", "Orthopedic Surgeon"] });
});

describe("doctor cards", () => {
  it("shows the doctors returned by the API", async () => {
    renderDirectory();
    const sarahCard = await card("Dr. Sarah Khan");
    expect(sarahCard).toHaveTextContent("Cardiologist");
    expect(sarahCard).toHaveTextContent("Cardiology");
    expect(sarahCard).toHaveTextContent("10 years experience");
    expect(sarahCard).toHaveTextContent("150.00");
    expect(sarahCard).toHaveTextContent("Available");
    expect(within(sarahCard).getByRole("img", { name: /Verified/ })).toBeInTheDocument();
    expect(within(sarahCard).getByRole("link", { name: "View profile" })).toHaveAttribute("href", "/doctors/doc-1");

    expect(screen.getByRole("heading", { name: "3 doctors found" })).toBeInTheDocument();
    expect(getPublicDoctors).toHaveBeenCalledWith(DEFAULTS);
  });

  it("shows each availability status and marks only verified doctors", async () => {
    renderDirectory();
    expect(await card("Dr. Robert Wilson")).toHaveTextContent("Unavailable");
    expect(await card("Dr. Emily Carter")).toHaveTextContent("Busy");
    expect(within(await card("Dr. Robert Wilson")).queryByRole("img", { name: /Verified/ })).not.toBeInTheDocument();
  });

  it("links Book appointment to the booking page, and disables it for an unavailable doctor", async () => {
    renderDirectory();
    expect(within(await card("Dr. Sarah Khan")).getByRole("link", { name: "Book appointment" })).toHaveAttribute(
      "href",
      "/appointments/book?doctor=doc-1"
    );
    const robertCard = await card("Dr. Robert Wilson");
    expect(within(robertCard).getByRole("button", { name: "Book appointment" })).toBeDisabled();
    expect(within(robertCard).queryByRole("link", { name: "Book appointment" })).not.toBeInTheDocument();
  });

  it("offers booking to a signed-in patient but not to a role that cannot book", async () => {
    const view = renderDirectory("/doctors", authAs("John Doe", ["patient"], PERMISSIONS.patient));
    expect(within(await card("Dr. Sarah Khan")).getByRole("link", { name: "Book appointment" })).toBeInTheDocument();
    view.unmount();

    renderDirectory("/doctors", authAs("Sarah Khan", ["doctor"], PERMISSIONS.doctor));
    const sarahCard = await card("Dr. Sarah Khan");
    expect(within(sarahCard).queryByText("Book appointment")).not.toBeInTheDocument();
    expect(within(sarahCard).getByRole("link", { name: "View profile" })).toBeInTheDocument();
  });
});

describe("search and filters", () => {
  it("restores the whole state from the URL", async () => {
    renderDirectory(
      "/doctors?q=cardio&department=dep-1&specialization=Cardiologist&min_experience=10&fee=150-200&sort=fee_desc&page=2&view=list"
    );
    await card("Dr. Sarah Khan");
    expect(lastRequest()).toEqual({
      page: 2,
      page_size: 6,
      sort: "fee_desc",
      q: "cardio",
      department_id: "dep-1",
      specialization: "Cardiologist",
      min_experience: "10",
      fee_min: "150",
      fee_max: "199.99",
    });
    expect(screen.getByRole("searchbox")).toHaveValue("cardio");
    await waitFor(() => expect(screen.getByLabelText("Department")).toHaveValue("dep-1"));
    expect(screen.getByLabelText("Min. experience")).toHaveValue("10");
    expect(screen.getByLabelText(/Fee range/)).toHaveValue("150-200");
    expect(screen.getByLabelText("Sort by")).toHaveValue("fee_desc");
    expect(screen.getByRole("button", { name: "List view" })).toHaveAttribute("aria-pressed", "true");
  });

  it("fills the department and specialization options from the API", async () => {
    renderDirectory();
    expect(await screen.findByRole("option", { name: "Orthopedics" })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Orthopedic Surgeon" })).toBeInTheDocument();
  });

  it("asks the API only when filters are applied, and goes back to page 1", async () => {
    const user = userEvent.setup();
    renderDirectory("/doctors?page=2");
    await card("Dr. Sarah Khan");
    await screen.findByRole("option", { name: "Orthopedics" });

    await user.type(screen.getByRole("searchbox"), "wilson");
    await user.selectOptions(screen.getByLabelText("Department"), "dep-2");
    await user.selectOptions(screen.getByLabelText("Min. experience"), "15");
    await user.selectOptions(screen.getByLabelText(/Fee range/), "150-200");
    expect(getPublicDoctors).toHaveBeenCalledTimes(1); // still a draft

    await user.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() =>
      expect(lastRequest()).toEqual({
        ...DEFAULTS,
        q: "wilson",
        department_id: "dep-2",
        min_experience: "15",
        fee_min: "150",
        fee_max: "199.99",
      })
    );
    expect(where()).toBe("/doctors?q=wilson&department=dep-2&min_experience=15&fee=150-200");
  });

  it("searches on Enter", async () => {
    const user = userEvent.setup();
    renderDirectory();
    await card("Dr. Sarah Khan");
    await user.type(screen.getByRole("searchbox"), "derma{Enter}");
    await waitFor(() => expect(lastRequest()).toEqual({ ...DEFAULTS, q: "derma" }));
  });

  it("clears every filter but keeps the sort order", async () => {
    const user = userEvent.setup();
    renderDirectory("/doctors?q=cardio&department=dep-1&sort=fee_asc&page=3");
    await card("Dr. Sarah Khan");
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(lastRequest()).toEqual({ ...DEFAULTS, sort: "fee_asc" }));
    expect(where()).toBe("/doctors?sort=fee_asc");
    expect(screen.getByRole("searchbox")).toHaveValue("");
  });

  it("sorts through the API and returns to page 1", async () => {
    const user = userEvent.setup();
    renderDirectory("/doctors?q=cardio&page=2");
    await card("Dr. Sarah Khan");
    await user.selectOptions(screen.getByLabelText("Sort by"), "experience_desc");
    await waitFor(() => expect(lastRequest()).toEqual({ ...DEFAULTS, q: "cardio", sort: "experience_desc" }));
    expect(where()).toBe("/doctors?q=cardio&sort=experience_desc");
  });
});

describe("pagination", () => {
  beforeEach(() => getPublicDoctors.mockResolvedValue(doctorsPage([sarah], { total: 14, total_pages: 3 })));

  it("requests the chosen page and keeps the filters", async () => {
    const user = userEvent.setup();
    renderDirectory("/doctors?q=cardio");
    const nav = await screen.findByRole("navigation", { name: "Pagination" });
    expect(within(nav).getByRole("button", { name: "Page 1" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("button", { name: /Previous/ })).toBeDisabled();
    expect(screen.getByRole("heading", { name: "14 doctors found" })).toBeInTheDocument();

    await user.click(within(nav).getByRole("button", { name: "Page 3" }));
    await waitFor(() => expect(lastRequest()).toEqual({ ...DEFAULTS, q: "cardio", page: 3 }));
    expect(where()).toBe("/doctors?q=cardio&page=3");
    await waitFor(() => expect(screen.getByRole("button", { name: /Next/ })).toBeDisabled());

    await user.click(screen.getByRole("button", { name: /Previous/ }));
    await waitFor(() => expect(lastRequest()).toEqual({ ...DEFAULTS, q: "cardio", page: 2 }));
  });

  it("is hidden when everything fits on one page", async () => {
    getPublicDoctors.mockResolvedValue(doctorsPage([sarah]));
    renderDirectory();
    await card("Dr. Sarah Khan");
    expect(screen.queryByRole("navigation", { name: "Pagination" })).not.toBeInTheDocument();
  });
});

describe("grid and list view", () => {
  it("switches layout without asking the API again", async () => {
    const user = userEvent.setup();
    const { container } = renderDirectory();
    await card("Dr. Sarah Khan");
    expect(container.querySelector(".doctor-results")).toHaveClass("grid");

    await user.click(screen.getByRole("button", { name: "List view" }));
    expect(container.querySelector(".doctor-results")).toHaveClass("list");
    expect(screen.getByRole("button", { name: "List view" })).toHaveAttribute("aria-pressed", "true");
    expect(where()).toBe("/doctors?view=list");
    expect(getPublicDoctors).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Grid view" }));
    expect(container.querySelector(".doctor-results")).toHaveClass("grid");
    expect(where()).toBe("/doctors");
  });
});

describe("loading, empty and error states", () => {
  it("shows placeholders while the first page loads", () => {
    getPublicDoctors.mockReturnValue(new Promise(() => {}));
    renderDirectory();
    expect(screen.getByRole("status", { name: "Loading doctors" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Searching…" })).toBeInTheDocument();
  });

  it("explains an empty result and offers to clear the filters", async () => {
    const user = userEvent.setup();
    getPublicDoctors.mockResolvedValue(doctorsPage([]));
    renderDirectory("/doctors?q=zzz");
    expect(await screen.findByText(/No doctors found/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "0 doctors found" })).toBeInTheDocument();

    getPublicDoctors.mockResolvedValue(doctorsPage([sarah]));
    const empty = screen.getByText(/No doctors found/).closest(".card");
    await user.click(within(empty).getByRole("button", { name: "Clear filters" }));
    expect(await card("Dr. Sarah Khan")).toBeInTheDocument();
    expect(where()).toBe("/doctors");
  });

  it("shows the API error and retries on request", async () => {
    const user = userEvent.setup();
    getPublicDoctors.mockRejectedValueOnce(apiError("Service unavailable"));
    renderDirectory();
    expect(await screen.findByText("Service unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await card("Dr. Sarah Khan")).toBeInTheDocument();
    expect(screen.queryByText("Service unavailable")).not.toBeInTheDocument();
  });
});

describe("search shortcut", () => {
  it("focuses the search box when opened with #search", async () => {
    renderDirectory("/doctors#search");
    await card("Dr. Sarah Khan");
    expect(screen.getByRole("searchbox")).toHaveFocus();
  });
});
