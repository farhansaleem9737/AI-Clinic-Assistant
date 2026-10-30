import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import {
  changeAppointmentStatus,
  countAppointments,
  countAppointmentsByDay,
  listAppointments,
} from "../services/appointmentService";
import { authAs, PERMISSIONS } from "../test/fixtures";
import Appointments from "./Appointments";

vi.mock("../context/useAuth");
vi.mock("../services/appointmentService");

const COUNTS = { timezone: "Asia/Karachi", today: "2027-04-23", day: "2027-04-23", on_day: 2, upcoming: 5, past: 7 };
const appointment = (id, overrides = {}) => ({
  id,
  status: "scheduled",
  starts_at: "2027-04-23T05:00:00Z", // 10:00 in Karachi
  ends_at: "2027-04-23T05:30:00Z",
  timezone: "Asia/Karachi",
  reason: "Follow-up",
  rescheduled_from_id: null,
  allowed_transitions: ["cancelled"],
  can_reschedule: false,
  patient: { id: `p-${id}`, name: "John Doe", mrn: "MRN00000001", date_of_birth: "1990-01-01", photo_url: null },
  ...overrides,
});
const A1 = appointment("a-1");
const A2 = appointment("a-2", {
  status: "in_progress",
  starts_at: "2027-04-23T05:30:00Z",
  ends_at: "2027-04-23T06:00:00Z",
  reason: null,
  allowed_transitions: ["completed"],
  patient: { id: "p-2", name: "Emily Carter", mrn: "MRN00000002", date_of_birth: "1998-06-01", photo_url: null },
});
const page = (items, total = items.length) => ({ data: { items, total, page: 1, page_size: 10, total_pages: 1 } });

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}
const renderPage = (entry = "/appointments") =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/appointments" element={<Appointments />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
const lastListParams = () => listAppointments.mock.calls.at(-1)[0];
const lastCountParams = () => countAppointmentsByDay.mock.calls.at(-1)[0];

beforeEach(() => {
  vi.resetAllMocks();
  useAuth.mockReturnValue(authAs("Sarah Khan", ["doctor"], PERMISSIONS.doctor));
  countAppointmentsByDay.mockImplementation((params) =>
    Promise.resolve({ data: { ...COUNTS, day: params.day ?? COUNTS.today } })
  );
  listAppointments.mockResolvedValue(page([A1, A2]));
});

describe("My Appointments", () => {
  it("shows today's schedule with real counts, times and patients", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "My Appointments" })).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: "Today (2)" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Upcoming (5)" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: "Past (7)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Today's Schedule" })).toBeInTheDocument();
    expect(screen.getByText("You have 2 appointments today.")).toBeInTheDocument();
    expect(screen.getByText("Friday")).toBeInTheDocument();

    const [, first, second] = screen.getAllByRole("row");
    expect(first).toHaveTextContent("10:00 AM");
    expect(first).toHaveTextContent("John Doe");
    expect(first).toHaveTextContent(/\d+ years · #MRN00000001/);
    expect(first).toHaveTextContent("Follow-up");
    expect(first).toHaveTextContent("Scheduled");
    expect(first).toHaveTextContent("Next"); // the next appointment still to come today
    expect(second).toHaveTextContent("No reason given");
    expect(second).toHaveTextContent("In consultation");

    expect(lastCountParams()).toEqual({});
    expect(lastListParams()).toEqual({ page: 1, page_size: 10, date_from: "2027-04-23", date_to: "2027-04-23" });
  });

  it("Upcoming and Past are measured from today", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("tab", { name: "Upcoming (5)" }));
    await waitFor(() => expect(lastListParams()).toMatchObject({ date_from: "2027-04-24" }));
    expect(lastListParams()).not.toHaveProperty("date_to");
    expect(screen.getByRole("heading", { name: "Upcoming Appointments" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Past (7)" }));
    await waitFor(() => expect(lastListParams()).toMatchObject({ date_to: "2027-04-22", newest_first: true }));
  });

  it("the arrows and the date picker change the selected day", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("tab", { name: "Today (2)" });
    await user.click(screen.getByRole("button", { name: "Next day" }));
    await waitFor(() => expect(lastCountParams()).toEqual({ day: "2027-04-24" }));
    expect(lastListParams()).toMatchObject({ date_from: "2027-04-24", date_to: "2027-04-24" });
    expect(await screen.findByRole("heading", { name: "Schedule for Selected Date" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Apr 24, 2027 (2)" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Previous day" }));
    await user.click(screen.getByRole("button", { name: "Previous day" }));
    await waitFor(() => expect(lastCountParams()).toEqual({ day: "2027-04-22" }));

    // jsdom cannot type into a date field key by key: set the picked value.
    fireEvent.change(screen.getByLabelText("Selected date"), { target: { value: "2027-05-02" } });
    await waitFor(() => expect(lastCountParams()).toEqual({ day: "2027-05-02" }));
  });

  it("filters by status, on the list and the counts", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("tab", { name: "Today (2)" });
    await user.selectOptions(screen.getByLabelText("Status"), "confirmed");
    await waitFor(() => expect(lastListParams()).toMatchObject({ status: ["confirmed"], page: 1 }));
    expect(lastCountParams()).toEqual({ status: ["confirmed"] });
    expect(screen.getByText("You have 2 appointments today matching your filters.")).toBeInTheDocument();
  });

  it("searches patients after a pause, not on every keystroke", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("tab", { name: "Today (2)" });
    await user.type(screen.getByLabelText("Search patients"), "john");
    await waitFor(() => expect(lastListParams()).toMatchObject({ q: "john" }));
    const searched = listAppointments.mock.calls.map(([p]) => p.q).filter(Boolean);
    expect(searched).toEqual(["john"]);
    expect(lastCountParams()).toEqual({ q: "john" });
  });

  it("offers a clear way out when nothing matches", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("tab", { name: "Today (2)" });
    listAppointments.mockResolvedValue(page([]));
    await user.selectOptions(screen.getByLabelText("Status"), "no_show");
    expect(await screen.findByText("No appointments match your search or status filter.")).toBeInTheDocument();
    listAppointments.mockResolvedValue(page([A1, A2]));
    await user.click(screen.getByRole("button", { name: "Clear search and filters" }));
    await waitFor(() => expect(lastListParams()).not.toHaveProperty("status"));
  });

  it("says when a day has no appointments", async () => {
    listAppointments.mockResolvedValue(page([]));
    renderPage();
    expect(await screen.findByText("No appointments on this date.")).toBeInTheDocument();
  });

  it("links View to the appointment and View Schedule to the schedule", async () => {
    const user = userEvent.setup();
    renderPage();
    const [, first] = await screen.findAllByRole("row");
    expect(within(first).getByRole("link", { name: /View/ })).toHaveAttribute("href", "/appointments/a-1");
    await user.click(screen.getByRole("button", { name: /View Schedule/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/schedule");
  });

  it("menus offer only what the API allows, and cancelling asks first", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockResolvedValue({ data: {} });
    renderPage();
    const [, first] = await screen.findAllByRole("row");
    await user.click(within(first).getByRole("button", { name: /Actions for John Doe/ }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["View Details", "Cancel appointment"]);
    await user.click(within(menu).getByRole("menuitem", { name: "Cancel appointment" }));
    expect(changeAppointmentStatus).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog", { name: "Cancel appointment?" });
    await user.selectOptions(within(dialog).getByLabelText("Reason"), "clinic_decision");
    const before = countAppointmentsByDay.mock.calls.length;
    await user.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));
    expect(changeAppointmentStatus).toHaveBeenCalledWith("a-1", { status: "cancelled", cancellation_reason: "clinic_decision" });
    expect(await screen.findByText("John Doe: cancelled.")).toBeInTheDocument();
    await waitFor(() => expect(countAppointmentsByDay.mock.calls.length).toBeGreaterThan(before)); // counts refreshed
  });

  it("completes a consultation in progress after confirming, and shows a refusal", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockRejectedValue({ response: { status: 409, data: { error: { message: "Cannot change an appointment from completed to completed" } } } });
    renderPage();
    const [, , second] = await screen.findAllByRole("row");
    await user.click(within(second).getByRole("button", { name: /Actions for Emily Carter/ }));
    await user.click(screen.getByRole("menuitem", { name: "Mark completed" }));
    const dialog = screen.getByRole("dialog", { name: "Mark as completed?" });
    await user.click(within(dialog).getByRole("button", { name: "Mark completed" }));
    expect(changeAppointmentStatus).toHaveBeenCalledWith("a-2", { status: "completed" });
    expect(await within(dialog).findByText(/Cannot change an appointment/)).toBeInTheDocument();
  });

  it("pages through the results", async () => {
    const user = userEvent.setup();
    listAppointments.mockResolvedValue(page([A1, A2], 25));
    renderPage();
    expect(await screen.findByText("Showing 1 to 10 of 25 appointments")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(lastListParams()).toMatchObject({ page: 2 }));
    expect(await screen.findByText("Showing 11 to 20 of 25 appointments")).toBeInTheDocument();
  });

  it("explains a loading failure and can retry", async () => {
    const user = userEvent.setup();
    countAppointmentsByDay.mockRejectedValueOnce({ response: { data: { error: { message: "Service unavailable" } } } });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("tab", { name: "Today (2)" })).toBeInTheDocument();
  });

  it("opens on the date a dashboard link asks for", async () => {
    renderPage("/appointments?date=2027-04-25");
    await waitFor(() => expect(lastCountParams()).toEqual({ day: "2027-04-25" }));
    expect(await screen.findByRole("heading", { name: "Schedule for Selected Date" })).toBeInTheDocument();
  });

  it("staff keep the clinic-wide table", async () => {
    useAuth.mockReturnValue(authAs("Rita Reception", ["receptionist"], ["appointment:read_any"]));
    listAppointments.mockResolvedValue(page([]));
    countAppointments.mockResolvedValue({ data: { upcoming: 0, past: 0, all: 0, today: 0, today_date: "2027-04-23" } });
    renderPage();
    await waitFor(() => expect(listAppointments).toHaveBeenCalled());
    expect(screen.queryByRole("heading", { name: "My Appointments" })).not.toBeInTheDocument();
    expect(countAppointmentsByDay).not.toHaveBeenCalled();
  });
});
