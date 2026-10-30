import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { getPublicDepartments } from "../services/departmentService";
import { getPublicDoctors, getPublicSpecializations } from "../services/doctorService";
import { getDaySchedule } from "../services/scheduleService";
import { authAs, PERMISSIONS, publicDoctor } from "../test/fixtures";
import DoctorSchedules from "./DoctorSchedules";

vi.mock("../context/useAuth");
vi.mock("../services/doctorService");
vi.mock("../services/departmentService");
vi.mock("../services/scheduleService");

const SARAH = publicDoctor({ id: "doc-1", years_of_experience: 10, consultation_fee: "150.00" });
const JAMES = publicDoctor({ id: "doc-2", name: "James Lee", department_id: "dep-2", department_name: "Neurology" });
const at = (hhmm) => `2027-04-22T${String(Number(hhmm.slice(0, 2)) - 5).padStart(2, "0")}:${hhmm.slice(3)}:00Z`; // Karachi = UTC+5
const slot = (hhmm, status) => ({ starts_at: at(hhmm), ends_at: at(hhmm), status });
const WEEK = ["18", "19", "20", "21", "22", "23", "24"].map((d, i) => ({
  date: `2027-04-${d}`,
  status: i === 0 || i === 6 ? "off" : "available",
  available_slots: i === 0 || i === 6 ? 0 : 5,
}));
const board = (date = "2027-04-22", overrides = {}) => ({
  doctor_id: "doc-1",
  timezone: "Asia/Karachi",
  date,
  today: "2027-04-20",
  slot_minutes: 30,
  working_hours: [
    { start_time: "09:00:00", end_time: "12:00:00" },
    { start_time: "13:00:00", end_time: "16:00:00" },
  ],
  breaks: [{ start_time: "12:00:00", end_time: "13:00:00" }],
  total_slots: 12,
  available_slots: 2,
  slots: [slot("09:00", "available"), slot("09:30", "available"), slot("10:00", "booked"), slot("12:00", "break"), slot("13:00", "past")],
  week: WEEK,
  ...overrides,
});

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}
function renderPage(query = "doctor=doc-1&date=2027-04-22", permissions = PERMISSIONS.receptionist) {
  useAuth.mockReturnValue(authAs("Ayesha Malik", ["receptionist"], [...permissions, "schedule:read"]));
  return render(
    <MemoryRouter initialEntries={[`/doctor-schedules?${query}`]}>
      <Routes>
        <Route path="/doctor-schedules" element={<DoctorSchedules />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}
const lastBoardCall = () => getDaySchedule.mock.calls.at(-1);

beforeEach(() => {
  vi.resetAllMocks();
  getPublicDoctors.mockResolvedValue({ data: { items: [SARAH, JAMES], total: 2 } });
  getPublicSpecializations.mockResolvedValue({ data: ["Cardiologist", "Neurologist"] });
  getPublicDepartments.mockResolvedValue({ data: { items: [{ id: "dep-1", name: "Cardiology" }, { id: "dep-2", name: "Neurology" }] } });
  getDaySchedule.mockImplementation((doctorId, day) => Promise.resolve({ data: board(day ?? "2027-04-20") }));
});

describe("Doctor Schedules", () => {
  it("shows the selected doctor's real summary", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Doctor Schedules" })).toBeInTheDocument();
    const summary = await screen.findByRole("region", { name: "Selected doctor" });
    expect(summary).toHaveTextContent("Dr. Sarah Khan");
    expect(summary).toHaveTextContent("10 years");
    expect(summary).toHaveTextContent("150.00");
    expect(summary).toHaveTextContent("Available on Selected Date"); // not today
    expect(summary).toHaveTextContent("09:00 AM – 12:00 PM, 01:00 PM – 04:00 PM");
    expect(getDaySchedule).toHaveBeenCalledWith("doc-1", "2027-04-22");
  });

  it("says Available Today only for today", async () => {
    renderPage("doctor=doc-1");
    const summary = await screen.findByRole("region", { name: "Selected doctor" });
    expect(lastBoardCall()).toEqual(["doc-1", undefined]); // the server decides what today is
    expect(summary).toHaveTextContent("Available Today");
  });

  it("asks for a doctor first", async () => {
    renderPage("");
    expect(await screen.findByText("Select a doctor to see their schedule.")).toBeInTheDocument();
    expect(getDaySchedule).not.toHaveBeenCalled();
  });

  it("the week strip uses real calendar dates and selects a day", async () => {
    const user = userEvent.setup();
    renderPage();
    const week = await screen.findByRole("group", { name: "Week" });
    const days = within(week).getAllByRole("button");
    expect(days).toHaveLength(7);
    expect(days[0]).toHaveTextContent("SunApr 18Off");
    expect(days[4]).toHaveTextContent("ThuApr 22Available"); // April 22, 2027 is a Thursday
    expect(days[4]).toHaveAttribute("aria-pressed", "true");
    await user.click(days[5]);
    await waitFor(() => expect(lastBoardCall()).toEqual(["doc-1", "2027-04-23"]));
  });

  it("Previous, Today and Next move the date", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("region", { name: "Selected doctor" });
    await user.click(screen.getByRole("button", { name: "Next day" }));
    await waitFor(() => expect(lastBoardCall()).toEqual(["doc-1", "2027-04-23"]));
    await user.click(await screen.findByRole("button", { name: "Previous day" }));
    await waitFor(() => expect(lastBoardCall()).toEqual(["doc-1", "2027-04-22"]));
    await user.click(await screen.findByRole("button", { name: "Today" }));
    await waitFor(() => expect(lastBoardCall()).toEqual(["doc-1", "2027-04-20"]));
  });

  it("the working hours card shows hours, duration, breaks and totals", async () => {
    renderPage();
    const card = await screen.findByRole("region", { name: "Doctor's Working Hours" });
    expect(card).toHaveTextContent("Thursday, April 22, 2027");
    expect(card).toHaveTextContent("30 minutes");
    expect(card).toHaveTextContent("12:00 PM – 01:00 PM");
    expect(card).toHaveTextContent("12 slots");
    expect(card).toHaveTextContent("2 still available");
  });

  it("says when there are no hours or breaks", async () => {
    getDaySchedule.mockResolvedValue({
      data: board("2027-04-18", { working_hours: [], breaks: [], slots: [], total_slots: 0, available_slots: 0 }),
    });
    renderPage("doctor=doc-1&date=2027-04-18");
    const card = await screen.findByRole("region", { name: "Doctor's Working Hours" });
    expect(card).toHaveTextContent("No working hours scheduled.");
    expect(card).toHaveTextContent("No scheduled breaks.");
    expect(screen.getByRole("region", { name: "Selected doctor" })).toHaveTextContent("Off");
    expect(screen.getByText("No time slots on this date.")).toBeInTheDocument();
  });

  it("only free slots can be chosen; booked, break and past ones say why", async () => {
    renderPage();
    const grid = await screen.findByRole("group", { name: "Time slots" });
    expect(within(grid).getAllByRole("button")).toHaveLength(2);
    expect(within(grid).getByText("Booked").parentElement).toHaveTextContent("10:00 AM");
    expect(within(grid).getByText("Break").parentElement).toHaveTextContent("12:00 PM");
    expect(within(grid).getByText("Past").parentElement).toHaveTextContent("01:00 PM");
    expect(screen.getByRole("button", { name: /Book Appointment/ })).toBeDisabled();
  });

  it("hands the chosen doctor and time to the booking wizard", async () => {
    const user = userEvent.setup();
    renderPage("doctor=doc-1&date=2027-04-22&patient=p-1");
    await user.click(await screen.findByRole("button", { name: "09:30 AM, available" }));
    expect(screen.getByRole("button", { name: "09:30 AM, available" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Showing availability for Dr. Sarah Khan on Thursday, April 22, 2027/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Book Appointment/ }));
    const where = new URL(`http://x${screen.getByTestId("where").textContent}`);
    expect(where.pathname).toBe("/appointments/book");
    expect(Object.fromEntries(where.searchParams)).toEqual({ doctor: "doc-1", slot: at("09:30"), patient: "p-1" });
  });

  it("a new date drops the chosen time", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "09:00 AM, available" }));
    expect(screen.getByRole("button", { name: /Book Appointment/ })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Next day" }));
    await waitFor(() => expect(lastBoardCall()).toEqual(["doc-1", "2027-04-23"]));
    expect(await screen.findByRole("button", { name: /Book Appointment/ })).toBeDisabled();
  });

  it("filters doctors and flags a selection the filters exclude", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("region", { name: "Selected doctor" });
    getPublicDoctors.mockResolvedValue({ data: { items: [JAMES], total: 1 } });
    await user.selectOptions(screen.getByRole("combobox", { name: "Department" }), "dep-2");
    await waitFor(() => expect(getPublicDoctors).toHaveBeenLastCalledWith(expect.objectContaining({ department_id: "dep-2" })));
    expect(await screen.findByText(/does not match these filters/)).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Doctor" }), "doc-2");
    await waitFor(() => expect(lastBoardCall()[0]).toBe("doc-2"));
  });

  it("explains a schedule that cannot be loaded", async () => {
    const user = userEvent.setup();
    getDaySchedule.mockRejectedValueOnce({ response: { data: { error: { message: "That date is outside the schedule that can be shown" } } } });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("outside the schedule");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Selected doctor" })).toBeInTheDocument();
  });

  it("people who cannot book see the schedule without the Book button", async () => {
    renderPage("doctor=doc-1&date=2027-04-22", ["schedule:read"]);
    await screen.findByRole("group", { name: "Time slots" });
    expect(screen.queryByRole("button", { name: /Book Appointment/ })).not.toBeInTheDocument();
  });
});
