import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { bookAppointment } from "../services/appointmentService";
import { getPublicDepartments } from "../services/departmentService";
import { getPublicAvailability, getPublicDoctor, getPublicDoctors, getPublicSpecializations } from "../services/doctorService";
import { getAvailability } from "../services/scheduleService";
import { appointment, authAs, PERMISSIONS, publicDoctor } from "../test/fixtures";
import { longDate } from "../utils/calendar";
import { formatLongDate, formatSlotTime, isoDateIn } from "../utils/datetime";
import BookAppointment from "./BookAppointment";

vi.mock("../context/useAuth");
vi.mock("../services/appointmentService");
vi.mock("../services/departmentService");
vi.mock("../services/doctorService");
vi.mock("../services/patientService");
vi.mock("../services/scheduleService");

const TZ = "Asia/Karachi";
// Today in the clinic's timezone, so the date-and-time step opens on it.
const DAY = isoDateIn(new Date(), TZ);
const SLOT = `${DAY}T10:00:00Z`;
const LATER = `${DAY}T10:30:00Z`;
const apiError = (message, status, code = "X") => ({ response: { status, data: { error: { code, message } } } });
const free = (slots, unavailable = []) => ({
  data: { doctor_id: "doc-1", timezone: TZ, bookable_until: "2099-12-31", days: [{ date: DAY, slots, unavailable }] },
});
// Another date in the same month as DAY, so both show on the opening calendar.
const OTHER_DAY = DAY.endsWith("-01") ? `${DAY.slice(0, 8)}02` : `${DAY.slice(0, 8)}01`;
const slot = (startsAt) => ({ starts_at: startsAt, ends_at: startsAt.replace(/T(\d\d):(\d\d)/, (_, h, m) => `T${h}:${Number(m) + 30}`) });
const doctorsPage = (items) => ({ data: { items, total: items.length, page: 1, page_size: 9 } });

const SARAH = publicDoctor({ photo_url: null });
const JAMES = publicDoctor({
  id: "doc-2",
  name: "James Lee",
  specialization: "Neurologist",
  department_id: "dep-2",
  department_name: "Neurology",
  consultation_fee: null,
  availability: { status: "available", next_available: SLOT, available_today: true, limited: false },
});

function renderBooking(auth, query = "") {
  useAuth.mockReturnValue(auth);
  return render(
    <MemoryRouter initialEntries={[`/appointments/book${query ? `?${query}` : ""}`]}>
      <Routes>
        <Route path="/appointments/book" element={<BookAppointment />} />
      </Routes>
    </MemoryRouter>
  );
}

const patient = () => authAs("John Doe", ["patient"], PERMISSIONS.patient);
const lastDoctorQuery = () => getPublicDoctors.mock.calls.at(-1)[0];

beforeEach(() => {
  vi.resetAllMocks();
  getPublicDoctors.mockResolvedValue(doctorsPage([SARAH, JAMES]));
  getPublicDoctor.mockResolvedValue({ data: SARAH });
  getPublicSpecializations.mockResolvedValue({ data: ["Cardiologist", "Neurologist"] });
  getPublicDepartments.mockResolvedValue({
    data: { items: [{ id: "dep-1", name: "Cardiology" }, { id: "dep-2", name: "Neurology" }] },
  });
  getPublicAvailability.mockResolvedValue(free([slot(SLOT), slot(LATER)]));
  getAvailability.mockResolvedValue({ data: { timezone: TZ, slots: [] } });
});

describe("step 1: select a doctor", () => {
  it("lists real doctors with their facts and availability, nothing selected yet", async () => {
    renderBooking(patient());
    expect(screen.getByRole("heading", { level: 1, name: "Book Appointment" })).toBeInTheDocument();
    expect(screen.getByText("Select Doctor").closest("li")).toHaveAttribute("aria-current", "step");

    const sarah = await screen.findByRole("radio", { name: /Dr\. Sarah Khan/ });
    expect(sarah).not.toBeChecked();
    const sarahCard = sarah.closest("label");
    expect(sarahCard).toHaveTextContent("Cardiologist");
    expect(sarahCard).toHaveTextContent("10 years experience");
    expect(sarahCard).toHaveTextContent("150.00");
    expect(sarahCard).toHaveTextContent("Available this week");

    const jamesCard = screen.getByRole("radio", { name: /Dr\. James Lee/ }).closest("label");
    expect(jamesCard).toHaveTextContent("Fee not available");
    expect(jamesCard).toHaveTextContent("Available today");
    expect(screen.getByRole("button", { name: /Continue/ })).toBeDisabled();
  });

  it("searches on the server once the user stops typing", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await screen.findByRole("radio", { name: /Sarah Khan/ });
    await user.type(screen.getByRole("searchbox", { name: /Search by doctor name/ }), "sarah");
    await waitFor(() => expect(lastDoctorQuery()).toMatchObject({ q: "sarah", page: 1 }));
  });

  it("filters by department and specialization together, with options from the API", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await screen.findByRole("radio", { name: /Sarah Khan/ });

    await user.selectOptions(screen.getByLabelText("Department"), "dep-2");
    await waitFor(() => expect(getPublicSpecializations).toHaveBeenLastCalledWith("dep-2"));
    await user.selectOptions(screen.getByLabelText("Specialization"), "Neurologist");
    await waitFor(() => expect(lastDoctorQuery()).toMatchObject({ department_id: "dep-2", specialization: "Neurologist" }));
  });

  it("says when nothing matches and can clear the filters", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await screen.findByRole("radio", { name: /Sarah Khan/ });
    getPublicDoctors.mockResolvedValue(doctorsPage([]));
    await user.type(screen.getByRole("searchbox"), "zzz");
    expect(await screen.findByText("No doctors match your search.")).toBeInTheDocument();

    getPublicDoctors.mockResolvedValue(doctorsPage([SARAH]));
    await user.click(screen.getByRole("button", { name: /Clear filters/ }));
    expect(await screen.findByRole("radio", { name: /Sarah Khan/ })).toBeInTheDocument();
    expect(screen.getByRole("searchbox")).toHaveValue("");
  });

  it("clears a selection that the new filters exclude", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await user.click(await screen.findByRole("radio", { name: /Sarah Khan/ }));
    expect(screen.getByRole("button", { name: /Continue/ })).toBeEnabled();

    getPublicDoctors.mockResolvedValue(doctorsPage([JAMES]));
    await user.selectOptions(screen.getByLabelText("Department"), "dep-2");
    await waitFor(() => expect(screen.getByRole("button", { name: /Continue/ })).toBeDisabled());
  });

  it("selects with the keyboard like a radio group", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    const sarah = await screen.findByRole("radio", { name: /Sarah Khan/ });
    sarah.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: /James Lee/ })).toBeChecked();
    expect(screen.getByRole("button", { name: /Continue/ })).toBeEnabled();
  });
});

describe("steps 2 and 3", () => {
  async function chooseSarahAndTime(user) {
    await user.click(await screen.findByRole("radio", { name: /Sarah Khan/ }));
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    expect(await screen.findByRole("heading", { name: "Select Date & Time" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: formatSlotTime(SLOT, TZ) }));
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    expect(await screen.findByRole("heading", { name: "Confirm your appointment" })).toBeInTheDocument();
    // The details appear once the time has been re-checked against live availability.
    return screen.findByRole("region", { name: "Appointment Details" });
  }

  it("marks steps 1 and 2 complete and step 3 current", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await chooseSarahAndTime(user);
    expect(screen.getByText("Select Doctor").closest("li")).toHaveClass("done");
    expect(screen.getByText("Date & Time").closest("li")).toHaveClass("done");
    expect(screen.getByText("Confirm").closest("li")).toHaveAttribute("aria-current", "step");
  });

  it("shows the real doctor, date, time, location and fee before anything is booked", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    const details = await chooseSarahAndTime(user);
    expect(details).toHaveTextContent("Dr. Sarah Khan");
    expect(details).toHaveTextContent("Cardiologist");
    expect(details).toHaveTextContent(formatLongDate(SLOT, TZ));
    expect(details).toHaveTextContent(formatSlotTime(SLOT, TZ));
    expect(details).toHaveTextContent("Cardiology");
    expect(details).toHaveTextContent("150.00");
    expect(details.querySelector('[data-avatar="doctor"]')).not.toBeNull(); // illustrated fallback
    expect(screen.getByText("Please verify your details")).toBeInTheDocument();
    expect(bookAppointment).not.toHaveBeenCalled();
  });

  it("books through all three steps and shows the saved appointment", async () => {
    const user = userEvent.setup();
    bookAppointment.mockResolvedValue({
      data: appointment({ id: "appt-9", starts_at: SLOT, timezone: TZ, status: "scheduled" }),
    });
    renderBooking(patient());
    await chooseSarahAndTime(user);

    await user.type(screen.getByRole("textbox", { name: "Reason for Appointment" }), "Chest pain");
    await user.click(screen.getByRole("button", { name: /Confirm Appointment/ }));
    expect(bookAppointment).toHaveBeenCalledWith(
      { doctor_id: "doc-1", starts_at: SLOT, reason: "Chest pain" },
      expect.any(String) // idempotency key
    );
    expect(bookAppointment.mock.calls[0][0]).not.toHaveProperty("patient_id");
    expect(bookAppointment.mock.calls[0][0]).not.toHaveProperty("status");

    expect(await screen.findByRole("heading", { name: "Your appointment is booked" })).toBeInTheDocument();
    expect(screen.getByText("Scheduled")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View Appointment Details" })).toHaveAttribute("href", "/appointments/appt-9");
    expect(screen.getByRole("link", { name: "My Appointments" })).toHaveAttribute("href", "/appointments");
    expect(screen.queryByRole("button", { name: /Confirm Appointment/ })).not.toBeInTheDocument();
  });

  it("counts the reason's characters and stops at 500", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await chooseSarahAndTime(user);
    const reason = screen.getByRole("textbox", { name: "Reason for Appointment" });
    expect(screen.getByText("0/500")).toBeInTheDocument();
    await user.type(reason, "Headache");
    expect(screen.getByText("8/500")).toBeInTheDocument();
    await user.clear(reason);
    await user.click(reason);
    await user.paste("x".repeat(600));
    expect(reason).toHaveValue("x".repeat(500));
    expect(screen.getByText("500/500")).toBeInTheDocument();
  });

  it("keeps the reason when going back to step 2 and returning", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await chooseSarahAndTime(user);
    await user.type(screen.getByRole("textbox", { name: "Reason for Appointment" }), "Follow-up");
    await user.click(screen.getByRole("button", { name: /Back/ }));
    expect(await screen.findByRole("heading", { name: "Select Date & Time" })).toBeInTheDocument();
    // The chosen time is still selected, so the patient can go straight on.
    await waitFor(() => expect(screen.getByRole("button", { name: /Continue/ })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    expect(await screen.findByRole("textbox", { name: "Reason for Appointment" })).toHaveValue("Follow-up");
  });

  it("sends one request however many times Confirm is pressed", async () => {
    const user = userEvent.setup();
    let finish;
    bookAppointment.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    renderBooking(patient());
    await chooseSarahAndTime(user);
    await user.click(screen.getByRole("button", { name: /Confirm Appointment/ }));
    const busy = screen.getByRole("button", { name: /Booking/ });
    expect(busy).toBeDisabled();
    await user.click(busy);
    expect(bookAppointment).toHaveBeenCalledTimes(1);
    finish({ data: appointment({ id: "appt-9", starts_at: SLOT, timezone: TZ }) });
    expect(await screen.findByRole("heading", { name: "Your appointment is booked" })).toBeInTheDocument();
  });

  it("keeps the chosen doctor when going back to step 1", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await user.click(await screen.findByRole("radio", { name: /Sarah Khan/ }));
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await user.click(await screen.findByRole("button", { name: /Back/ }));
    expect(await screen.findByRole("radio", { name: /Sarah Khan/ })).toBeChecked();
  });

  it("cannot continue from step 2 without a time", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await user.click(await screen.findByRole("radio", { name: /Sarah Khan/ }));
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await screen.findByRole("button", { name: formatSlotTime(SLOT, TZ) });
    expect(screen.getByRole("button", { name: /Continue/ })).toBeDisabled();
  });

  it("sends the patient back to fresh times when the slot was taken, keeping the reason", async () => {
    const user = userEvent.setup();
    bookAppointment.mockRejectedValue(apiError("That time is not available", 409, "SLOT_UNAVAILABLE"));
    renderBooking(patient());
    await chooseSarahAndTime(user);
    await user.type(screen.getByRole("textbox", { name: "Reason for Appointment" }), "Chest pain");
    const callsBefore = getPublicAvailability.mock.calls.length;

    await user.click(screen.getByRole("button", { name: /Confirm Appointment/ }));
    expect(await screen.findByText(/this time was just booked by someone else/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Select Date & Time" })).toBeInTheDocument();
    await waitFor(() => expect(getPublicAvailability.mock.calls.length).toBeGreaterThan(callsBefore));
    expect(screen.getByRole("button", { name: /Continue/ })).toBeDisabled();

    await user.click(await screen.findByRole("button", { name: formatSlotTime(LATER, TZ) }));
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    expect(await screen.findByRole("textbox", { name: "Reason for Appointment" })).toHaveValue("Chest pain");
  });

  it("returns to choosing a doctor when the doctor stopped taking bookings", async () => {
    const user = userEvent.setup();
    bookAppointment.mockRejectedValue(
      apiError("Doctor not found or not accepting appointments", 404, "DOCTOR_UNAVAILABLE")
    );
    renderBooking(patient());
    await chooseSarahAndTime(user);
    await user.click(screen.getByRole("button", { name: /Confirm Appointment/ }));
    expect(await screen.findByText(/no longer taking appointments/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Select a doctor" })).toBeInTheDocument();
  });

  it("shows other booking errors and lets the patient retry", async () => {
    const user = userEvent.setup();
    bookAppointment.mockRejectedValue(apiError("Complete your patient profile before booking", 400));
    renderBooking(patient());
    await chooseSarahAndTime(user);
    await user.click(screen.getByRole("button", { name: /Confirm Appointment/ }));
    expect(await screen.findByText("Complete your patient profile before booking")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Confirm Appointment/ })).toBeEnabled();
  });
});

describe("step 2: date and time", () => {
  async function openStep2(user) {
    await user.click(await screen.findByRole("radio", { name: /Sarah Khan/ }));
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await screen.findByRole("heading", { name: "Select Date & Time" });
  }

  it("marks step 1 complete, step 2 current and step 3 upcoming", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await openStep2(user);
    expect(screen.getByText("Select Doctor").closest("li")).toHaveClass("done");
    expect(screen.getByText("(completed)")).toBeInTheDocument();
    expect(screen.getByText("Date & Time").closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("Confirm").closest("li")).toHaveClass("upcoming");
  });

  it("summarises the doctor chosen in step 1 from API data", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await openStep2(user);
    const summary = screen.getByRole("region", { name: "Selected doctor" });
    expect(within(summary).getByRole("heading", { name: "Dr. Sarah Khan" })).toBeInTheDocument();
    expect(summary).toHaveTextContent("Cardiologist · Cardiology");
    expect(summary).toHaveTextContent("10 years experience");
    expect(summary).toHaveTextContent("150.00");
    expect(summary).toHaveTextContent("Available this week");
    expect(summary.querySelector('[data-avatar="doctor"]')).not.toBeNull(); // illustrated fallback, no stock photo
  });

  it("shows free times, greys out unavailable ones, and states the clinic time zone", async () => {
    const user = userEvent.setup();
    getPublicAvailability.mockResolvedValue(free([slot(SLOT), slot(LATER)], [slot(`${DAY}T11:00:00Z`)]));
    renderBooking(patient());
    await openStep2(user);

    const times = await screen.findByRole("group", { name: `Times on ${longDate(DAY)}` });
    const taken = within(times).getByRole("button", { name: `${formatSlotTime(`${DAY}T11:00:00Z`, TZ)}, unavailable` });
    expect(taken).toBeDisabled();
    expect(screen.getByText(longDate(DAY))).toHaveClass("accent-text");
    expect(screen.getByText(/Selected time zone: \(GMT\+05:00\)/)).toBeInTheDocument();
    for (const key of ["Selected date", "Available", "Unavailable"]) {
      expect(within(screen.getByRole("list", { name: "Calendar key" })).getByText(key)).toBeInTheDocument();
    }

    const ten = within(times).getByRole("button", { name: formatSlotTime(SLOT, TZ) });
    await user.click(ten);
    expect(ten).toHaveAttribute("aria-pressed", "true");
    expect(ten).toHaveClass("selected");
    expect(screen.getByRole("button", { name: /Continue/ })).toBeEnabled();
  });

  it("only dates with free times can be chosen, and choosing another date clears the time", async () => {
    const user = userEvent.setup();
    getPublicAvailability.mockResolvedValue({
      data: {
        doctor_id: "doc-1",
        timezone: TZ,
        bookable_until: "2099-12-31",
        days: [
          { date: DAY, slots: [slot(SLOT)], unavailable: [] },
          { date: OTHER_DAY, slots: [slot(`${OTHER_DAY}T09:00:00Z`)], unavailable: [] },
        ],
      },
    });
    renderBooking(patient());
    await openStep2(user);
    const calendar = screen.getByRole("group", { name: /^Dates in / });
    const dayButtons = within(calendar).getAllByRole("button");
    // Dates without free times are disabled.
    expect(dayButtons.filter((b) => !b.disabled)).toHaveLength(2);

    await user.click(await screen.findByRole("button", { name: formatSlotTime(SLOT, TZ) }));
    expect(screen.getByRole("button", { name: /Continue/ })).toBeEnabled();
    await user.click(within(calendar).getByRole("button", { name: new RegExp(`^${longDate(OTHER_DAY)}`) }));
    expect(screen.getByRole("button", { name: /Continue/ })).toBeDisabled();
    expect(await screen.findByRole("button", { name: formatSlotTime(`${OTHER_DAY}T09:00:00Z`, TZ) })).toBeInTheDocument();
  });

  it("loads the next month's availability when moving forward", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await openStep2(user);
    await screen.findByRole("button", { name: formatSlotTime(SLOT, TZ) });
    await user.click(screen.getByRole("button", { name: "Next month" }));
    const [year, month] = DAY.split("-").map(Number);
    const next = month === 12 ? `${year + 1}-01-01` : `${year}-${String(month + 1).padStart(2, "0")}-01`;
    await waitFor(() => expect(getPublicAvailability).toHaveBeenLastCalledWith("doc-1", next, expect.any(String)));
  });

  it("explains a failed availability request and can retry", async () => {
    const user = userEvent.setup();
    getPublicAvailability.mockRejectedValueOnce(apiError("Availability is temporarily unavailable", 503));
    renderBooking(patient());
    await openStep2(user);
    expect(await screen.findByText("Availability is temporarily unavailable")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("button", { name: formatSlotTime(SLOT, TZ) })).toBeInTheDocument();
  });

  it("back to step 1 and a different doctor starts the time choice afresh", async () => {
    const user = userEvent.setup();
    renderBooking(patient());
    await openStep2(user);
    await user.click(await screen.findByRole("button", { name: formatSlotTime(SLOT, TZ) }));
    await user.click(screen.getByRole("button", { name: /Back/ }));
    await user.click(await screen.findByRole("radio", { name: /James Lee/ }));
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await screen.findByRole("heading", { name: "Select Date & Time" });
    expect(screen.getByRole("button", { name: /Continue/ })).toBeDisabled();
    expect(getPublicAvailability).toHaveBeenLastCalledWith("doc-2", expect.any(String), expect.any(String));
  });
});

describe("arriving from the directory or a doctor's profile", () => {
  it("a doctor link starts at step 2 with that doctor", async () => {
    renderBooking(patient(), "doctor=doc-1");
    expect(await screen.findByRole("heading", { name: "Select Date & Time" })).toBeInTheDocument();
    expect(screen.getByText("Dr. Sarah Khan")).toBeInTheDocument();
    expect(getPublicDoctor).toHaveBeenCalledWith("doc-1");
  });

  it("a doctor and time from the profile open the confirm step, and nothing is booked yet", async () => {
    renderBooking(patient(), `doctor=doc-1&slot=${encodeURIComponent(SLOT)}`);
    expect(await screen.findByRole("heading", { name: "Confirm your appointment" })).toBeInTheDocument();
    // The details appear once the time has been re-checked against live availability.
    expect(await screen.findByRole("region", { name: "Appointment Details" })).toHaveTextContent(formatSlotTime(SLOT, TZ));
    expect(bookAppointment).not.toHaveBeenCalled();
  });

  it("does not offer a linked time that is no longer free", async () => {
    const user = userEvent.setup();
    getPublicAvailability.mockResolvedValue(free([slot(LATER)]));
    renderBooking(patient(), `doctor=doc-1&slot=${encodeURIComponent(SLOT)}`);
    expect(await screen.findByText("This time is no longer available. Please choose another time.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Confirm Appointment/ })).toBeDisabled(); // nothing to confirm
    await user.click(screen.getByRole("button", { name: "Choose another time" }));
    expect(await screen.findByRole("heading", { name: "Select Date & Time" })).toBeInTheDocument();
  });

  it("an unknown doctor id falls back to choosing a doctor", async () => {
    getPublicDoctor.mockRejectedValue(apiError("Doctor not found", 404));
    renderBooking(patient(), "doctor=nope");
    expect(await screen.findByText(/That doctor is not available for booking/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Select a doctor" })).toBeInTheDocument();
  });

  it("a malformed time in the link asks for a new time", async () => {
    renderBooking(patient(), "doctor=doc-1&slot=not-a-time");
    expect(await screen.findByText("That appointment link is not valid. Please choose a time.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Select Date & Time" })).toBeInTheDocument();
  });
});

describe("staff", () => {
  it("get the full form, where they pick the patient", async () => {
    renderBooking(authAs("Rita Front", ["receptionist"], PERMISSIONS.receptionist), `doctor=doc-1&slot=${encodeURIComponent(SLOT)}`);
    expect(await screen.findByRole("heading", { name: "Book an appointment" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "1. Patient" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Book Appointment" })).not.toBeInTheDocument();
  });
});

describe("booking card markup", () => {
  it("uses the illustrated doctor avatar when there is no photo", async () => {
    renderBooking(patient());
    const card = (await screen.findByRole("radio", { name: /Sarah Khan/ })).closest("label");
    expect(within(card).queryByRole("img")).not.toBeInTheDocument(); // decorative illustration, no stock photo
    expect(card.querySelector('[data-avatar="doctor"]')).not.toBeNull();
  });
});
