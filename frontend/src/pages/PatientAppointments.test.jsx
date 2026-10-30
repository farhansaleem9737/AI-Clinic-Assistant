import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { changeAppointmentStatus, countAppointments, listAppointments } from "../services/appointmentService";
import { getPublicDepartments } from "../services/departmentService";
import { listDoctors } from "../services/doctorService";
import { appointment, authAs, PERMISSIONS } from "../test/fixtures";
import { formatTime } from "../utils/datetime";
import Appointments from "./Appointments";

vi.mock("../context/useAuth");
vi.mock("../services/appointmentService");
vi.mock("../services/departmentService");
vi.mock("../services/doctorService");

const apiError = (message, status = 400) => ({ response: { status, data: { error: { code: "X", message } } } });
const UPCOMING = { scope: "upcoming", newest_first: false, page: 1, page_size: 10 };

const sarah = appointment({
  reason: "Follow-up consultation",
  status: "confirmed",
  allowed_transitions: ["cancelled"],
  can_reschedule: true,
});
const james = appointment({
  id: "appt-2",
  status: "requested",
  starts_at: "2026-10-07T09:30:00Z",
  doctor: { ...appointment().doctor, id: "doc-2", name: "James Lee", specialization: "General Physician", department_name: "General Medicine", room_number: null },
  allowed_transitions: ["confirmed", "cancelled"],
  can_reschedule: false,
});
const finished = appointment({
  id: "appt-3",
  status: "completed",
  doctor: { ...appointment().doctor, name: "Michael Brown" },
  allowed_transitions: [],
  can_reschedule: false,
});

const pageOf = (items, extra = {}) => ({
  data: { items, total: items.length, page: 1, page_size: 10, total_pages: items.length ? 1 : 0, ...extra },
});

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderPage(initial = "/appointments", auth = authAs("John Doe", ["patient"], PERMISSIONS.patient)) {
  useAuth.mockReturnValue(auth);
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route
          path="/appointments"
          element={
            <>
              <Appointments />
              <Where />
            </>
          }
        />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}

const lastList = () => listAppointments.mock.calls.at(-1)[0];
const lastCounts = () => countAppointments.mock.calls.at(-1)[0];
const where = () => screen.getByTestId("where").textContent;
const row = (name) => screen.findByRole("article", { name: new RegExp(name) });

beforeEach(() => {
  vi.resetAllMocks();
  listAppointments.mockResolvedValue(pageOf([sarah, james]));
  countAppointments.mockResolvedValue({ data: { upcoming: 2, past: 3, all: 5 } });
});

describe("tabs and counts", () => {
  it("opens on Upcoming with counts from the API", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Appointments" })).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: "Upcoming (2)" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Past (3)" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: "All (5)" })).toBeInTheDocument();
    expect(listAppointments).toHaveBeenCalledWith(UPCOMING);
    expect(countAppointments).toHaveBeenCalledWith({});
  });

  it("asks the API for each tab, most recent first for past and all", async () => {
    const user = userEvent.setup();
    renderPage();
    await row("Sarah Khan");
    await user.click(screen.getByRole("tab", { name: /Past/ }));
    await waitFor(() => expect(lastList()).toEqual({ ...UPCOMING, scope: "past", newest_first: true }));
    expect(where()).toBe("/appointments?tab=past");
    expect(screen.getByRole("tab", { name: /Past/ })).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{ArrowRight}");
    await waitFor(() => expect(lastList()).toEqual({ ...UPCOMING, scope: "all", newest_first: true }));
    expect(screen.getByRole("tab", { name: /All/ })).toHaveFocus();
    // Counts do not depend on the tab, so they are not fetched again.
    expect(countAppointments).toHaveBeenCalledTimes(1);
  });
});

describe("appointment cards", () => {
  it("shows the doctor, reason, time, room and status from the API", async () => {
    renderPage();
    const card = await row("Sarah Khan");
    expect(card).toHaveTextContent("Cardiologist");
    expect(card).toHaveTextContent("Cardiology");
    expect(card).toHaveTextContent("Follow-up consultation");
    expect(card).toHaveTextContent(formatTime(sarah.starts_at, sarah.timezone));
    expect(card).toHaveTextContent("Room B-12");
    expect(card).toHaveTextContent("Confirmed");
    expect(card).toHaveTextContent("Oct5Mon"); // date block, in the clinic's timezone
    expect(within(card).getByRole("link", { name: /View details/ })).toHaveAttribute("href", "/appointments/appt-1");
    expect(card.querySelector('[data-avatar="doctor"]')).not.toBeNull();
    expect(card.querySelector("img")).toBeNull();
  });

  it("leaves out what the appointment does not have", async () => {
    renderPage();
    const card = await row("James Lee");
    expect(card).not.toHaveTextContent(/Room|null|undefined/);
    expect(card).toHaveTextContent("Requested");
  });

  it("is the patient page, not the staff table", async () => {
    renderPage();
    await row("Sarah Khan");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("MRN00000001")).not.toBeInTheDocument();
  });

  it("staff get the clinic-wide appointments page, not the patient view", async () => {
    listAppointments.mockResolvedValue(pageOf([sarah]));
    countAppointments.mockResolvedValue({ data: { upcoming: 1, past: 0, all: 1, today: 0, today_date: "2026-10-05" } });
    getPublicDepartments.mockResolvedValue({ data: { items: [] } });
    listDoctors.mockResolvedValue({ data: { items: [] } });
    renderPage("/appointments", authAs("Rita", ["receptionist"], PERMISSIONS.receptionist));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Today (0)" })).toBeInTheDocument();
    expect(countAppointments).toHaveBeenCalledWith(expect.objectContaining({ include_today: true }));
  });
});

describe("search and filters", () => {
  it("searches after typing stops, and starts again from page 1", async () => {
    const user = userEvent.setup();
    renderPage("/appointments?page=2");
    await row("Sarah Khan");
    await user.type(screen.getByRole("searchbox", { name: /Search by doctor/ }), "lee");
    expect(lastList().q).toBeUndefined(); // not on every keystroke
    await waitFor(() => expect(lastList()).toEqual({ ...UPCOMING, q: "lee" }));
    expect(lastCounts()).toEqual({ q: "lee" });
    expect(where()).toBe("/appointments?q=lee");
    expect(listAppointments.mock.calls.filter(([p]) => p.q && p.q !== "lee")).toEqual([]);
  });

  it("filters by status and date range on the server", async () => {
    const user = userEvent.setup();
    renderPage();
    await row("Sarah Khan");
    await user.selectOptions(screen.getByLabelText("Status"), "cancelled");
    await waitFor(() => expect(lastList()).toEqual({ ...UPCOMING, status: "cancelled" }));
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText("To date"), { target: { value: "2026-10-31" } });
    await waitFor(() =>
      expect(lastList()).toEqual({ ...UPCOMING, status: "cancelled", date_from: "2026-10-01", date_to: "2026-10-31" })
    );
    expect(lastCounts()).toEqual({ status: "cancelled", date_from: "2026-10-01", date_to: "2026-10-31" });
  });

  it("refuses a backwards date range without asking the API", async () => {
    renderPage("/appointments?from=2026-10-20&to=2026-10-01");
    expect(await screen.findByText("The start date must be on or before the end date.")).toBeInTheDocument();
    expect(listAppointments).not.toHaveBeenCalled();
    expect(countAppointments).not.toHaveBeenCalled();
  });

  it("clears every filter but keeps the tab", async () => {
    const user = userEvent.setup();
    renderPage("/appointments?tab=past&q=lee&status=completed&from=2026-01-01&to=2026-02-01&page=2");
    await waitFor(() =>
      expect(lastList()).toEqual({
        scope: "past", newest_first: true, page: 2, page_size: 10,
        q: "lee", status: "completed", date_from: "2026-01-01", date_to: "2026-02-01",
      })
    );
    expect(screen.getByRole("searchbox", { name: /Search by doctor/ })).toHaveValue("lee");
    await user.click(screen.getByRole("button", { name: /Clear filters/ }));
    await waitFor(() => expect(lastList()).toEqual({ ...UPCOMING, scope: "past", newest_first: true }));
    expect(where()).toBe("/appointments?tab=past");
    expect(screen.getByRole("searchbox", { name: /Search by doctor/ })).toHaveValue("");
    expect(screen.getByLabelText("Status")).toHaveValue("");
  });

  it("a pending search does not undo Clear filters", async () => {
    const user = userEvent.setup();
    renderPage("/appointments?status=completed");
    await row("Sarah Khan");
    await user.type(screen.getByRole("searchbox", { name: /Search by doctor/ }), "x");
    await user.click(screen.getByRole("button", { name: /Clear filters/ }));
    await new Promise((r) => setTimeout(r, 500));
    expect(where()).toBe("/appointments");
  });
});

describe("pagination", () => {
  it("shows the range and moves between pages", async () => {
    const user = userEvent.setup();
    listAppointments.mockResolvedValue(pageOf([sarah, james], { total: 25, total_pages: 3 }));
    renderPage();
    expect(await screen.findByText("Showing 1 to 10 of 25 appointments")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Page 3" }));
    await waitFor(() => expect(lastList()).toEqual({ ...UPCOMING, page: 3 }));
    expect(await screen.findByText("Showing 21 to 25 of 25 appointments")).toBeInTheDocument();
  });
});

describe("empty, loading and error states", () => {
  it.each([
    ["/appointments", "No upcoming appointments.", true],
    ["/appointments?tab=past", "No past appointments yet.", false],
  ])("%s with nothing to show", async (url, text, offersBooking) => {
    listAppointments.mockResolvedValue(pageOf([]));
    renderPage(url);
    expect(await screen.findByText(text)).toBeInTheDocument();
    const results = document.getElementById("appointment-results");
    expect(within(results).queryAllByRole("link", { name: /Book Appointment/ }).length > 0).toBe(offersBooking);
  });

  it("says when filters match nothing and offers to clear them", async () => {
    const user = userEvent.setup();
    listAppointments.mockResolvedValue(pageOf([]));
    renderPage("/appointments?status=no_show");
    expect(await screen.findByText("No appointments match your filters.")).toBeInTheDocument();
    const results = document.getElementById("appointment-results");
    await user.click(within(results).getByRole("button", { name: "Clear filters" }));
    expect(where()).toBe("/appointments");
  });

  it("shows placeholders, not zero, while loading", () => {
    listAppointments.mockReturnValue(new Promise(() => {}));
    countAppointments.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status", { name: "Loading appointments" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Upcoming" })).toBeInTheDocument();
    expect(screen.queryByText(/Showing/)).not.toBeInTheDocument();
  });

  it("shows the API's message and retries", async () => {
    const user = userEvent.setup();
    listAppointments.mockRejectedValueOnce(apiError("Something went wrong. Please try again.", 500));
    renderPage();
    expect(await screen.findByText("Something went wrong. Please try again.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await row("Sarah Khan")).toBeInTheDocument();
  });
});

describe("actions", () => {
  it("offers only what the API allows for each appointment", async () => {
    const user = userEvent.setup();
    listAppointments.mockResolvedValue(pageOf([sarah, james, finished]));
    renderPage();
    const sarahCard = await row("Sarah Khan");
    await user.click(within(sarahCard).getByRole("button", { name: /Actions for/ }));
    expect(screen.getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Reschedule", "Cancel appointment"]);
    expect(screen.getByRole("menuitem", { name: "Reschedule" })).toHaveAttribute("href", "/appointments/appt-1?reschedule=1");
    expect(screen.getByRole("menuitem", { name: "Reschedule" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(within(sarahCard).getByRole("button", { name: /Actions for/ })).toHaveFocus();

    await user.click(within(await row("James Lee")).getByRole("button", { name: /Actions for/ }));
    expect(screen.getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Confirm attendance", "Cancel appointment"]);
    await user.keyboard("{Escape}");

    // Nothing to do on a finished appointment: no menu at all.
    const done = await row("Michael Brown");
    expect(within(done).queryByRole("button", { name: /Actions for/ })).not.toBeInTheDocument();
  });

  it("cancels only after confirmation, then refreshes the list and counts", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockResolvedValue({ data: {} });
    renderPage();
    const card = await row("Sarah Khan");

    await user.click(within(card).getByRole("button", { name: /Actions for/ }));
    await user.click(screen.getByRole("menuitem", { name: "Cancel appointment" }));
    const dialog = screen.getByRole("dialog", { name: "Cancel this appointment?" });
    await user.click(within(dialog).getByRole("button", { name: "Keep appointment" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(changeAppointmentStatus).not.toHaveBeenCalled();

    const listCalls = listAppointments.mock.calls.length;
    const countCalls = countAppointments.mock.calls.length;
    await user.click(within(card).getByRole("button", { name: /Actions for/ }));
    await user.click(screen.getByRole("menuitem", { name: "Cancel appointment" }));
    await user.type(within(screen.getByRole("dialog")).getByLabelText(/Note/), "Feeling better");
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel appointment" }));

    expect(changeAppointmentStatus).toHaveBeenCalledWith("appt-1", {
      status: "cancelled",
      cancellation_reason: "patient_request",
      note: "Feeling better",
    });
    expect(await screen.findByText("Your appointment has been cancelled.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(listAppointments.mock.calls.length).toBe(listCalls + 1));
    expect(countAppointments.mock.calls.length).toBe(countCalls + 1);
  });

  it("keeps the dialog open with the API's reason when cancelling is refused", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockRejectedValue(apiError("Too close to the appointment to cancel online", 409));
    renderPage();
    const card = await row("Sarah Khan");
    await user.click(within(card).getByRole("button", { name: /Actions for/ }));
    await user.click(screen.getByRole("menuitem", { name: "Cancel appointment" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel appointment" }));
    expect(await within(screen.getByRole("dialog")).findByText("Too close to the appointment to cancel online")).toBeInTheDocument();
  });

  it("confirms attendance through the API", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockResolvedValue({ data: {} });
    renderPage();
    await user.click(within(await row("James Lee")).getByRole("button", { name: /Actions for/ }));
    await user.click(screen.getByRole("menuitem", { name: "Confirm attendance" }));
    expect(changeAppointmentStatus).toHaveBeenCalledWith("appt-2", { status: "confirmed" });
    expect(await screen.findByText(/attendance is confirmed/)).toBeInTheDocument();
  });

  it("Book Appointment starts from choosing a doctor", async () => {
    renderPage();
    await row("Sarah Khan");
    const header = screen.getByRole("heading", { level: 1 }).closest(".page-head");
    expect(within(header).getByRole("link", { name: /Book Appointment/ })).toHaveAttribute("href", "/doctors");
  });
});
