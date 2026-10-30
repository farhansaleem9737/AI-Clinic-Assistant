import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import {
  createDateException,
  deleteDateException,
  getWeeklySchedule,
  listDateExceptions,
  saveWeeklySchedule,
  updateDateException,
} from "../services/scheduleService";
import { authAs, PERMISSIONS } from "../test/fixtures";
import DoctorSchedule from "./DoctorSchedule";

vi.mock("../context/useAuth");
vi.mock("../services/scheduleService");
vi.mock("../services/doctorService");

const WORKDAY = { start_time: "08:00:00", end_time: "16:00:00" };
const SCHEDULE = {
  doctor_id: "doc-1",
  timezone: "Asia/Karachi",
  days: [0, 1, 2, 3, 4, 5, 6].map((weekday) => ({
    weekday,
    enabled: weekday < 5,
    intervals: weekday < 5 ? [WORKDAY] : [],
    slot_minutes: 30,
  })),
};
const LEAVE = {
  id: "ex-1",
  type: "unavailable",
  kind: "leave",
  date: "2027-04-09",
  end_date: "2027-04-09",
  start_time: null,
  end_time: null,
  reason: "Personal leave",
  editable: true,
};
const CONFERENCE = {
  id: "ex-2",
  type: "custom_hours",
  kind: "custom_hours",
  date: "2027-04-22",
  end_date: "2027-04-22",
  start_time: "10:00:00",
  end_time: "14:00:00",
  reason: "Conference",
  editable: true,
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <DoctorSchedule />
    </MemoryRouter>
  );
const row = (day) => screen.getByRole("rowheader", { name: day }).closest("tr");
const weekly = () => screen.getByRole("region", { name: "Weekly Working Hours" });
const exceptionsCard = () => screen.getByRole("region", { name: "Exceptions" });

beforeEach(() => {
  vi.resetAllMocks();
  useAuth.mockReturnValue(authAs("Sarah Khan", ["doctor"], PERMISSIONS.doctor));
  getWeeklySchedule.mockResolvedValue({ data: SCHEDULE });
  listDateExceptions.mockResolvedValue({ data: [LEAVE, CONFERENCE] });
});

describe("weekly working hours", () => {
  it("shows all seven days with their saved hours and status", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "My Schedule" })).toBeInTheDocument();
    await screen.findByRole("region", { name: "Weekly Working Hours" });
    for (const day of ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]) {
      expect(row(day)).toBeInTheDocument();
    }
    expect(within(row("Monday")).getByRole("switch", { name: "Monday available" })).toBeChecked();
    expect(row("Monday")).toHaveTextContent("Available");
    expect(row("Monday")).toHaveTextContent("08:00 AM");
    expect(row("Monday")).toHaveTextContent("04:00 PM");
    expect(within(row("Saturday")).getByRole("switch")).not.toBeChecked();
    expect(row("Saturday")).toHaveTextContent("Unavailable");
    expect(screen.getByText(/Times are in .*Pakistan|Times are in .*Asia\/Karachi|Times are in \(GMT\+05:00\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save Changes/ })).toBeDisabled(); // nothing to save yet
  });

  it("switching a day off and saving sends the whole week", async () => {
    const user = userEvent.setup();
    const saved = { ...SCHEDULE, days: SCHEDULE.days.map((d) => (d.weekday === 4 ? { ...d, enabled: false, intervals: [] } : d)) };
    saveWeeklySchedule.mockResolvedValue({ data: saved });
    renderPage();
    await screen.findByRole("region", { name: "Weekly Working Hours" });

    await user.click(within(row("Friday")).getByRole("switch"));
    expect(row("Friday")).toHaveTextContent("Unavailable");
    expect(row("Friday")).not.toHaveTextContent("08:00 AM");
    expect(screen.getByText(/You have unsaved changes/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Save Changes/ }));
    const [doctorId, days] = saveWeeklySchedule.mock.calls[0];
    expect(doctorId).toBe("doc-1");
    expect(days).toHaveLength(7);
    expect(days[4]).toEqual({ weekday: 4, enabled: false, slot_minutes: 30, intervals: [] });
    expect(days[0].intervals).toEqual([{ start_time: "08:00", end_time: "16:00" }]);
    expect(await screen.findByText("Your weekly hours were saved.")).toBeInTheDocument();
    expect(screen.queryByText(/You have unsaved changes/)).not.toBeInTheDocument();
  });

  it("switching on a day without hours asks for them first", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("region", { name: "Weekly Working Hours" });
    await user.click(within(row("Saturday")).getByRole("switch"));

    const editor = screen.getByRole("group", { name: "Saturday working hours" });
    expect(within(editor).getByLabelText("Saturday start time")).toHaveValue("09:00");
    expect(row("Saturday")).toHaveTextContent("Unavailable"); // not on until Done
    await user.click(within(editor).getByRole("button", { name: "Done" }));
    expect(row("Saturday")).toHaveTextContent("Available");
    expect(row("Saturday")).toHaveTextContent("09:00 AM");
  });

  it("edits a day's hours and refuses an end before the start", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("region", { name: "Weekly Working Hours" });
    await user.click(screen.getByRole("button", { name: "Edit Tuesday hours" }));
    const editor = screen.getByRole("group", { name: "Tuesday working hours" });
    const end = within(editor).getByLabelText("Tuesday end time");
    await user.clear(end);
    await user.type(end, "07:00");
    await user.click(within(editor).getByRole("button", { name: "Done" }));
    expect(within(editor).getByRole("alert")).toHaveTextContent("The end time must be after the start time.");

    await user.clear(end);
    await user.type(end, "12:30");
    await user.click(within(editor).getByRole("button", { name: "Done" }));
    expect(row("Tuesday")).toHaveTextContent("12:30 PM");
  });

  it("supports more than one time range per day", async () => {
    const user = userEvent.setup();
    saveWeeklySchedule.mockImplementation((_, days) =>
      Promise.resolve({
        data: {
          ...SCHEDULE,
          days: days.map((d) => ({ ...d, intervals: d.intervals.map((i) => ({ start_time: `${i.start_time}:00`, end_time: `${i.end_time}:00` })) })),
        },
      })
    );
    renderPage();
    await screen.findByRole("region", { name: "Weekly Working Hours" });
    await user.click(screen.getByRole("button", { name: "Edit Monday hours" }));
    const editor = screen.getByRole("group", { name: "Monday working hours" });
    await user.clear(within(editor).getByLabelText("Monday end time"));
    await user.type(within(editor).getByLabelText("Monday end time"), "12:00");
    await user.click(within(editor).getByRole("button", { name: /Add another time range/ }));
    await user.type(within(editor).getByLabelText("Monday start time 2"), "14:00");
    await user.type(within(editor).getByLabelText("Monday end time 2"), "17:00");
    await user.click(within(editor).getByRole("button", { name: "Done" }));
    await user.click(screen.getByRole("button", { name: /Save Changes/ }));
    expect(saveWeeklySchedule.mock.calls[0][1][0].intervals).toEqual([
      { start_time: "08:00", end_time: "12:00" },
      { start_time: "14:00", end_time: "17:00" },
    ]);
  });

  it("asks to finish an open editor before saving, and can discard changes", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("region", { name: "Weekly Working Hours" });
    await user.click(within(row("Friday")).getByRole("switch"));
    await user.click(screen.getByRole("button", { name: "Edit Monday hours" }));
    await user.click(screen.getByRole("button", { name: /Save Changes/ }));
    expect(screen.getByText(/Finish editing Monday first/)).toBeInTheDocument();
    expect(saveWeeklySchedule).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("group", { name: "Monday working hours" })).not.toBeInTheDocument();
    expect(screen.getByText(/You have unsaved changes/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(row("Friday")).toHaveTextContent("Available");
    expect(screen.getByRole("button", { name: /Save Changes/ })).toBeDisabled();
  });

  it("explains a conflict with booked appointments without claiming success", async () => {
    const user = userEvent.setup();
    saveWeeklySchedule.mockRejectedValue({
      response: {
        status: 409,
        data: {
          error: {
            code: "SCHEDULE_CONFLICT",
            message:
              "This schedule change conflicts with existing appointments. Please reschedule or cancel those appointments before continuing.",
            details: { dates: ["2027-04-16"] },
          },
        },
      },
    });
    renderPage();
    await screen.findByRole("region", { name: "Weekly Working Hours" });
    await user.click(within(row("Friday")).getByRole("switch"));
    await user.click(screen.getByRole("button", { name: /Save Changes/ }));
    expect(await within(weekly()).findByText(/conflicts with existing appointments.*Affected dates: April 16, 2027/)).toBeInTheDocument();
    expect(screen.queryByText("Your weekly hours were saved.")).not.toBeInTheDocument();
    expect(row("Friday")).toHaveTextContent("Unavailable"); // the draft is kept
  });

  it("explains a loading failure and can retry", async () => {
    const user = userEvent.setup();
    getWeeklySchedule.mockRejectedValueOnce({ response: { data: { error: { message: "Service unavailable" } } } });
    renderPage();
    expect(await screen.findByText("Service unavailable")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Try again" })[0]);
    expect(await screen.findByRole("region", { name: "Weekly Working Hours" })).toBeInTheDocument();
  });
});

describe("exceptions", () => {
  it("lists the saved exceptions with their type, hours and reason", async () => {
    renderPage();
    const card = await screen.findByRole("region", { name: "Exceptions" });
    const items = await within(card).findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("April 9, 2027");
    expect(items[0]).toHaveTextContent("Friday");
    expect(items[0]).toHaveTextContent("Unavailable");
    expect(items[0]).toHaveTextContent("Personal leave");
    expect(items[1]).toHaveTextContent("Custom Hours");
    expect(items[1]).toHaveTextContent("10:00 AM – 02:00 PM");
    expect(items[1]).toHaveTextContent("Conference");
  });

  it("says when there are none", async () => {
    listDateExceptions.mockResolvedValue({ data: [] });
    renderPage();
    expect(await within(await screen.findByRole("region", { name: "Exceptions" })).findByText(/No upcoming exceptions/)).toBeInTheDocument();
  });

  it("adds an unavailable day and refreshes the list", async () => {
    const user = userEvent.setup();
    createDateException.mockResolvedValue({ data: {} });
    renderPage();
    await screen.findAllByRole("listitem");
    await user.click(within(exceptionsCard()).getByRole("button", { name: /Add Exception/ }));
    const dialog = screen.getByRole("dialog", { name: "Add Exception" });
    expect(within(dialog).queryByLabelText("Start Time")).not.toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Date"), "2027-05-01");
    await user.type(within(dialog).getByLabelText(/Reason/), "Public holiday");
    listDateExceptions.mockResolvedValue({ data: [LEAVE] });
    await user.click(within(dialog).getByRole("button", { name: "Save Exception" }));

    expect(createDateException).toHaveBeenCalledWith("doc-1", {
      date: "2027-05-01",
      type: "unavailable",
      start_time: null,
      end_time: null,
      reason: "Public holiday",
    });
    expect(await screen.findByText("The exception was added.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(listDateExceptions).toHaveBeenCalledTimes(2);
  });

  it("custom hours need a valid time range", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findAllByRole("listitem");
    await user.click(within(exceptionsCard()).getByRole("button", { name: /Add Exception/ }));
    const dialog = screen.getByRole("dialog", { name: "Add Exception" });
    await user.type(within(dialog).getByLabelText("Date"), "2027-05-03");
    await user.click(within(dialog).getByRole("radio", { name: /Custom Hours/ }));
    await user.type(within(dialog).getByLabelText("Start Time"), "14:00");
    await user.type(within(dialog).getByLabelText("End Time"), "10:00");
    await user.click(within(dialog).getByRole("button", { name: "Save Exception" }));
    expect(within(dialog).getByText("The end time must be after the start time.")).toBeInTheDocument();
    expect(createDateException).not.toHaveBeenCalled();
  });

  it("shows a duplicate date as a date error", async () => {
    const user = userEvent.setup();
    createDateException.mockRejectedValue({ response: { status: 409, data: { error: { code: "EXCEPTION_EXISTS", message: "x" } } } });
    renderPage();
    await screen.findAllByRole("listitem");
    await user.click(within(exceptionsCard()).getByRole("button", { name: /Add Exception/ }));
    const dialog = screen.getByRole("dialog", { name: "Add Exception" });
    await user.type(within(dialog).getByLabelText("Date"), "2027-04-09");
    await user.click(within(dialog).getByRole("button", { name: "Save Exception" }));
    expect(await within(dialog).findByText(/already has an exception/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Date")).toHaveAttribute("aria-invalid", "true");
  });

  it("edits an exception from its menu with the saved values filled in", async () => {
    const user = userEvent.setup();
    updateDateException.mockResolvedValue({ data: {} });
    renderPage();
    const [, conference] = await screen.findAllByRole("listitem");
    await user.click(within(conference).getByRole("button", { name: /Actions for April 22, 2027/ }));
    await user.click(screen.getByRole("menuitem", { name: "Edit Exception" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Exception" });
    expect(within(dialog).getByLabelText("Date")).toHaveValue("2027-04-22");
    expect(within(dialog).getByRole("radio", { name: /Custom Hours/ })).toBeChecked();
    expect(within(dialog).getByLabelText("Start Time")).toHaveValue("10:00");
    const end = within(dialog).getByLabelText("End Time");
    await user.clear(end);
    await user.type(end, "13:00");
    await user.click(within(dialog).getByRole("button", { name: "Save Exception" }));
    expect(updateDateException).toHaveBeenCalledWith("doc-1", "ex-2", {
      date: "2027-04-22",
      type: "custom_hours",
      start_time: "10:00",
      end_time: "13:00",
      reason: "Conference",
    });
  });

  it("deletes only after confirmation", async () => {
    const user = userEvent.setup();
    deleteDateException.mockResolvedValue({});
    renderPage();
    const [leave] = await screen.findAllByRole("listitem");
    await user.click(within(leave).getByRole("button", { name: /Actions for April 9, 2027/ }));
    await user.click(screen.getByRole("menuitem", { name: "Delete Exception" }));
    expect(deleteDateException).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "Delete exception?" });
    expect(dialog).toHaveTextContent("April 9, 2027 will follow the regular weekly hours again");
    await user.click(within(dialog).getByRole("button", { name: "Delete Exception" }));
    expect(deleteDateException).toHaveBeenCalledWith("doc-1", "ex-1");
    expect(await screen.findByText(/The exception was deleted/)).toBeInTheDocument();
  });

  it("the section buttons move between the two cards", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("region", { name: "Weekly Working Hours" });
    const nav = screen.getByRole("navigation", { name: "Schedule sections" });
    expect(within(nav).getByRole("link", { name: "Weekly Hours" })).toHaveAttribute("aria-current", "true");
    await user.click(within(nav).getByRole("link", { name: "Exceptions" }));
    expect(within(nav).getByRole("link", { name: "Exceptions" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("heading", { name: "Exceptions" })).toHaveFocus();
    // Both cards stay visible.
    expect(weekly()).toBeVisible();
  });
});
