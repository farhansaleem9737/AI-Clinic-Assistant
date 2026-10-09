import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import {
  changeAppointmentStatus,
  getAppointment,
  getAppointmentHistory,
  rescheduleAppointment,
  updateAppointment,
} from "../services/appointmentService";
import { getAvailability } from "../services/scheduleService";
import { appointmentDetail, authAs, PERMISSIONS } from "../test/fixtures";
import { formatLongDate, formatTime } from "../utils/datetime";
import { downloadAppointmentIcs } from "../utils/ics";
import AppointmentDetail from "./AppointmentDetail";

vi.mock("../context/useAuth");
vi.mock("../services/appointmentService");
vi.mock("../services/scheduleService");
vi.mock("../utils/ics", async (importOriginal) => ({ ...(await importOriginal()), downloadAppointmentIcs: vi.fn() }));

const apiError = (message, status = 400) => ({ response: { status, data: { error: { code: "X", message } } } });

// Far enough ahead to be upcoming whenever the tests run.
const FUTURE = new Date(Date.now() + 5 * 86400000);
FUTURE.setUTCHours(5, 0, 0, 0);
const future = (minutes = 0) => new Date(FUTURE.getTime() + minutes * 60000).toISOString();

const confirmed = appointmentDetail({
  starts_at: future(),
  ends_at: future(30),
  reason: "Regular heart checkup",
  allowed_transitions: ["cancelled"],
  can_reschedule: true,
});

const HISTORY = [
  { from_status: null, to_status: "requested", changed_by_user_id: "u-1", reason: null, changed_at: "2026-09-28T10:00:00Z" },
  { from_status: "requested", to_status: "scheduled", changed_by_user_id: null, reason: "Slot available; scheduled automatically", changed_at: "2026-09-28T10:00:01Z" },
  { from_status: "scheduled", to_status: "confirmed", changed_by_user_id: "u-1", reason: null, changed_at: "2026-09-29T09:00:00Z" },
];

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search + location.hash}</p>;
}

const patient = () => authAs("John Doe", ["patient"], PERMISSIONS.patient);
const receptionist = () => authAs("Rita", ["receptionist"], [...PERMISSIONS.receptionist, "appointment:manage"]);

function renderPage(url = "/appointments/appt-1", auth = patient()) {
  useAuth.mockReturnValue(auth);
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/appointments/:id" element={<AppointmentDetail />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}

const summary = () => screen.findByRole("region", { name: "Appointment summary" });
const quickActions = () => screen.getByRole("region", { name: "Quick Actions" });

beforeEach(() => {
  vi.resetAllMocks();
  getAppointment.mockResolvedValue({ data: confirmed });
  getAppointmentHistory.mockResolvedValue({ data: HISTORY });
});

describe("appointment data", () => {
  it("shows the doctor, time, place and status from the API", async () => {
    renderPage();
    const card = await summary();
    expect(screen.getByRole("heading", { level: 1, name: "Appointment Details" })).toBeInTheDocument();
    expect(screen.getByText("View your appointment information and manage your visit.")).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByText("Appointment Details")).toHaveAttribute("aria-current", "page");
    expect(within(card).getByRole("heading", { name: /Dr\. Sarah Khan/ })).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: /Verified/ })).toBeInTheDocument();
    expect(card).toHaveTextContent("Cardiologist");
    expect(card).toHaveTextContent("10 years experience");
    expect(card).toHaveTextContent("Cardiology Department");
    expect(card).toHaveTextContent(formatLongDate(confirmed.starts_at, "Asia/Karachi"));
    expect(card).toHaveTextContent(`${formatTime(confirmed.starts_at, "Asia/Karachi")} – ${formatTime(confirmed.ends_at, "Asia/Karachi")}`);
    expect(card).toHaveTextContent("Room B-12");
    expect(card).toHaveTextContent("Confirmed");
    expect(getAppointment).toHaveBeenCalledWith("appt-1");
  });

  it("shows the patient's details and the appointment information", async () => {
    renderPage();
    const patientCard = await screen.findByRole("region", { name: "Patient Information" });
    expect(patientCard).toHaveTextContent("John Doe");
    expect(patientCard).toHaveTextContent(/Jan 1, 1990|1 Jan 1990/);
    expect(patientCard).toHaveTextContent("Male");
    expect(within(patientCard).getByRole("link", { name: "+1 234 567 890" })).toHaveAttribute("href", "tel:+1234567890");
    expect(within(patientCard).getByRole("link", { name: "john@example.com" })).toHaveAttribute("href", "mailto:john@example.com");
    expect(patientCard).toHaveTextContent("123 Main St, City");
    const info = screen.getByRole("region", { name: "Appointment Information" });
    expect(info).toHaveTextContent("Regular heart checkup");
    expect(info).toHaveTextContent("Room B-12, Cardiology");
    expect(info).not.toHaveTextContent(/Appointment Type/); // not part of the domain
  });

  it("uses the illustrated doctor avatar, never a photo", async () => {
    renderPage();
    const card = await summary();
    expect(card.querySelector('[data-avatar="doctor"]')).not.toBeNull();
    expect(document.querySelector("img")).toBeNull();
  });

  it("says what is missing instead of inventing it", async () => {
    getAppointment.mockResolvedValue({
      data: appointmentDetail({
        doctor: { ...confirmed.doctor, room_number: null, years_of_experience: 0, is_verified: false },
        patient_profile: { sex_at_birth: "unknown", gender_identity: null, phone: null, email: null, address: null },
      }),
    });
    renderPage();
    const card = await summary();
    expect(within(card).queryByRole("img", { name: /Verified/ })).not.toBeInTheDocument();
    expect(card).not.toHaveTextContent(/years experience|Room|null|undefined/);
    const patientCard = screen.getByRole("region", { name: "Patient Information" });
    expect(within(patientCard).getAllByText("Not provided")).toHaveLength(3);
    expect(screen.getByRole("region", { name: "Appointment Information" })).toHaveTextContent("Not provided"); // reason
  });

  it("explains when the account may not see the patient's contact details", async () => {
    getAppointment.mockResolvedValue({ data: appointmentDetail({ patient_profile: null }) });
    renderPage();
    const patientCard = await screen.findByRole("region", { name: "Patient Information" });
    expect(patientCard).toHaveTextContent("not available to your account");
    expect(patientCard).not.toHaveTextContent("Phone");
  });
});

describe("loading and errors", () => {
  it("shows a placeholder, not fake data, while loading", () => {
    getAppointment.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status", { name: "Loading appointment" })).toBeInTheDocument();
    expect(screen.queryByText("Dr. Sarah Khan")).not.toBeInTheDocument();
  });

  it.each([404, 422])("treats %s as not found", async (status) => {
    getAppointment.mockRejectedValue(apiError("Appointment not found", status));
    renderPage();
    expect(await screen.findByText(/does not exist, or it is not one you can view/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All appointments" })).toHaveAttribute("href", "/appointments");
  });

  it("says when the account is not allowed", async () => {
    getAppointment.mockRejectedValue(apiError("Forbidden", 403));
    renderPage();
    expect(await screen.findByText("You do not have permission to view this appointment.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("shows the API's message and retries", async () => {
    const user = userEvent.setup();
    getAppointment.mockRejectedValueOnce(apiError("Something went wrong. Please try again.", 500));
    renderPage();
    expect(await screen.findByText("Something went wrong. Please try again.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await summary()).toBeInTheDocument();
  });
});

describe("tabs", () => {
  it("opens on Details and moves with the arrow keys", async () => {
    const user = userEvent.setup();
    renderPage();
    await summary();
    const details = screen.getByRole("tab", { name: "Details" });
    expect(details).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", details.id);
    details.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Notes" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Notes" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute("aria-selected", "true");
  });

  it("Notes shows the patient's own words and no staff notes", async () => {
    const user = userEvent.setup();
    renderPage();
    await summary();
    await user.click(screen.getByRole("tab", { name: "Notes" }));
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent("Regular heart checkup");
    expect(panel).toHaveTextContent("Notes from your consultation are not available online yet.");
    expect(panel).not.toHaveTextContent("Staff notes");
  });

  it("History lists the recorded status changes", async () => {
    const user = userEvent.setup();
    renderPage();
    await summary();
    await user.click(screen.getByRole("tab", { name: "History" }));
    const entries = within(screen.getByRole("tabpanel")).getAllByRole("listitem");
    expect(entries.map((e) => within(e).getByRole("heading").textContent)).toEqual(["Requested", "Scheduled", "Confirmed"]);
    expect(entries[0]).toHaveTextContent("By you");
    expect(entries[1]).toHaveTextContent("Automatically");
    expect(entries[1]).toHaveTextContent("Slot available; scheduled automatically");
  });

  it("staff see and save internal notes", async () => {
    const user = userEvent.setup();
    getAppointment.mockResolvedValue({ data: { ...confirmed, staff_notes: "Wheelchair access", booked_by_user_id: "u-9" } });
    updateAppointment.mockResolvedValue({ data: {} });
    renderPage("/appointments/appt-1", receptionist());
    await summary();
    expect(screen.getByText("View the appointment and manage the visit.")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Notes" }));
    const notes = screen.getByLabelText("Staff notes");
    expect(notes).toHaveValue("Wheelchair access");
    await user.clear(notes);
    await user.type(notes, "Needs an interpreter");
    await user.click(screen.getByRole("button", { name: "Save notes" }));
    expect(updateAppointment).toHaveBeenCalledWith("appt-1", { staff_notes: "Needs an interpreter" });
    expect(await screen.findByText("Notes saved.")).toBeInTheDocument();
  });
});

describe("cancelling", () => {
  it("cancels only after confirmation, then shows the new status", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockResolvedValue({ data: {} });
    renderPage();
    const card = await summary();

    await user.click(within(card).getByRole("button", { name: "Cancel Appointment" }));
    await user.click(within(screen.getByRole("dialog", { name: "Cancel this appointment?" })).getByRole("button", { name: "Keep appointment" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(changeAppointmentStatus).not.toHaveBeenCalled();

    getAppointment.mockResolvedValue({
      data: { ...confirmed, status: "cancelled", cancellation_reason: "patient_request", allowed_transitions: [], can_reschedule: false },
    });
    await user.click(within(card).getByRole("button", { name: "Cancel Appointment" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByLabelText("Reason")).not.toBeInTheDocument(); // patients do not pick a reason
    await user.type(within(dialog).getByLabelText(/Note for the clinic/), "Travelling");
    await user.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));

    expect(changeAppointmentStatus).toHaveBeenCalledWith("appt-1", { status: "cancelled", cancellation_reason: "patient_request", note: "Travelling" });
    expect(await screen.findByText("Your appointment has been cancelled.")).toBeInTheDocument();
    await waitFor(() => expect(within(card).getByText("Cancelled")).toBeInTheDocument());
    expect(within(card).queryByRole("button", { name: "Cancel Appointment" })).not.toBeInTheDocument();
  });

  it("keeps the dialog open with the API's reason when refused", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockRejectedValue(apiError("It is too late to change this appointment online", 400));
    renderPage();
    await user.click(within(await summary()).getByRole("button", { name: "Cancel Appointment" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel appointment" }));
    expect(await within(screen.getByRole("dialog")).findByText("It is too late to change this appointment online")).toBeInTheDocument();
  });

  it("staff choose a reason", async () => {
    const user = userEvent.setup();
    getAppointment.mockResolvedValue({ data: { ...confirmed, staff_notes: null, booked_by_user_id: "u-9" } });
    changeAppointmentStatus.mockResolvedValue({ data: {} });
    renderPage("/appointments/appt-1", receptionist());
    await user.click(within(await summary()).getByRole("button", { name: "Cancel Appointment" }));
    const dialog = screen.getByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("Reason"), "doctor_unavailable");
    await user.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));
    expect(changeAppointmentStatus).toHaveBeenCalledWith("appt-1", { status: "cancelled", cancellation_reason: "doctor_unavailable", note: null });
  });
});

describe("other actions", () => {
  it("offers only what the API allows, and says why the rest is unavailable", async () => {
    getAppointment.mockResolvedValue({
      data: appointmentDetail({ status: "completed", starts_at: future(), ends_at: future(30), allowed_transitions: [], can_reschedule: false }),
    });
    renderPage();
    const card = await summary();
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
    const quick = quickActions();
    expect(within(quick).getByRole("button", { name: /Reschedule Appointment/ })).toBeDisabled();
    expect(within(quick).getByRole("button", { name: /Cancel Appointment/ })).toBeDisabled();
    expect(within(quick).getAllByText("This appointment is completed and can no longer be changed.")).toHaveLength(2);
    expect(within(quick).getByRole("button", { name: /Add to Calendar/ })).toBeDisabled();
  });

  it("explains a closed online window on an appointment that is still open", async () => {
    getAppointment.mockResolvedValue({ data: { ...confirmed, allowed_transitions: [], can_reschedule: false } });
    renderPage();
    await summary();
    expect(within(quickActions()).getAllByText("Changes are no longer possible online. Please contact the clinic.")).toHaveLength(2);
  });

  it("patients confirm attendance; staff get their own transitions", async () => {
    const user = userEvent.setup();
    changeAppointmentStatus.mockResolvedValue({ data: {} });
    getAppointment.mockResolvedValue({ data: { ...confirmed, status: "scheduled", allowed_transitions: ["confirmed", "cancelled"] } });
    const { unmount } = renderPage();
    await user.click(within(await summary()).getByRole("button", { name: "Confirm attendance" }));
    expect(changeAppointmentStatus).toHaveBeenCalledWith("appt-1", { status: "confirmed" });
    expect(await screen.findByText("Thank you, your attendance is confirmed.")).toBeInTheDocument();
    unmount();

    getAppointment.mockResolvedValue({
      data: { ...confirmed, staff_notes: null, booked_by_user_id: "u-9", allowed_transitions: ["checked_in", "no_show", "cancelled"] },
    });
    renderPage("/appointments/appt-1", receptionist());
    await user.click(within(await summary()).getByRole("button", { name: "Check in" }));
    expect(changeAppointmentStatus).toHaveBeenLastCalledWith("appt-1", { status: "checked_in" });
  });

  it("adds an upcoming appointment to the calendar", async () => {
    const user = userEvent.setup();
    renderPage();
    await summary();
    await user.click(within(quickActions()).getByRole("button", { name: /Add to Calendar/ }));
    expect(downloadAppointmentIcs).toHaveBeenCalledWith(confirmed);
  });

  it("Contact Clinic points to the clinic's contact details", async () => {
    renderPage();
    await summary();
    expect(within(quickActions()).getByRole("link", { name: /Contact Clinic/ })).toHaveAttribute("href", "/help#contact");
  });

  it("View Doctor Profile opens this doctor's profile", async () => {
    const user = userEvent.setup();
    renderPage();
    await summary();
    const doctorCard = screen.getByRole("region", { name: "Doctor Information" });
    expect(doctorCard).toHaveTextContent("Cardiologist");
    await user.click(within(doctorCard).getByRole("link", { name: /View Doctor Profile/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/doctors/doc-1");
  });
});

describe("rescheduling", () => {
  const slot = { starts_at: future(24 * 60 + 60), ends_at: future(24 * 60 + 90) };

  beforeEach(() => {
    getAvailability.mockResolvedValue({ data: { timezone: "UTC", slots: [slot] } });
  });

  it("moves the appointment to a free time the patient confirms", async () => {
    const user = userEvent.setup();
    const moved = appointmentDetail({ id: "appt-2", starts_at: slot.starts_at, ends_at: slot.ends_at, status: "scheduled", rescheduled_from_id: "appt-1" });
    rescheduleAppointment.mockResolvedValue({ data: moved });
    renderPage();
    await user.click(within(await summary()).getByRole("button", { name: "Reschedule" }));
    expect(screen.getByRole("heading", { name: "Choose a new time" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Select a new time" })).toBeDisabled();

    await user.click(await screen.findByRole("button", { name: formatTime(slot.starts_at, "UTC") }));
    getAppointment.mockResolvedValue({ data: moved });
    await user.click(screen.getByRole("button", { name: /Confirm new time/ }));

    expect(rescheduleAppointment).toHaveBeenCalledWith("appt-1", { starts_at: slot.starts_at });
    expect(await screen.findByText(/The appointment has been moved to/)).toBeInTheDocument();
    await waitFor(() => expect(getAppointment).toHaveBeenLastCalledWith("appt-2"));
    expect(screen.queryByRole("heading", { name: "Choose a new time" })).not.toBeInTheDocument();
  });

  it("stays put and reloads free times when the slot was just taken", async () => {
    const user = userEvent.setup();
    rescheduleAppointment.mockRejectedValue(apiError("That time is not available", 409));
    renderPage("/appointments/appt-1?reschedule=1");
    await user.click(await screen.findByRole("button", { name: formatTime(slot.starts_at, "UTC") }));
    await user.click(screen.getByRole("button", { name: /Confirm new time/ }));
    expect(await screen.findByText("That time is not available")).toBeInTheDocument();
    expect(getAvailability.mock.calls.length).toBeGreaterThan(1);
    expect(screen.getByRole("button", { name: "Select a new time" })).toBeDisabled();
    expect(getAppointment).not.toHaveBeenCalledWith("appt-2");
  });

  it("does not open the picker when the API does not allow rescheduling", async () => {
    getAppointment.mockResolvedValue({ data: { ...confirmed, can_reschedule: false } });
    renderPage("/appointments/appt-1?reschedule=1");
    await summary();
    expect(screen.queryByRole("heading", { name: "Choose a new time" })).not.toBeInTheDocument();
    expect(getAvailability).not.toHaveBeenCalled();
  });
});
