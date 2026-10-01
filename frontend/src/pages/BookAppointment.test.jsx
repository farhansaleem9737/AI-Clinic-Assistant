import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { bookAppointment } from "../services/appointmentService";
import { getPublicDepartments } from "../services/departmentService";
import { getPublicAvailability, getPublicDoctor, getPublicDoctors } from "../services/doctorService";
import { getAvailability } from "../services/scheduleService";
import { authAs, PERMISSIONS, publicDoctor } from "../test/fixtures";
import { formatDateTime } from "../utils/datetime";
import BookAppointment from "./BookAppointment";

vi.mock("../context/useAuth");
vi.mock("../services/appointmentService");
vi.mock("../services/departmentService");
vi.mock("../services/doctorService");
vi.mock("../services/patientService");
vi.mock("../services/scheduleService");

const TZ = "Asia/Karachi";
const SLOT = "2026-10-05T05:00:00Z";
const apiError = (message, status, code = "X") => ({ response: { status, data: { error: { code, message } } } });
const free = (slots) => ({
  data: { doctor_id: "doc-1", timezone: TZ, bookable_until: "2099-12-31", days: [{ date: "2026-10-05", slots }] },
});

function Where() {
  const location = useLocation();
  return (
    <p data-testid="where">
      {location.pathname}
      {location.state?.notice}
    </p>
  );
}

function renderBooking(auth, query = `doctor=doc-1&slot=${encodeURIComponent(SLOT)}`) {
  useAuth.mockReturnValue(auth);
  return render(
    <MemoryRouter initialEntries={[`/appointments/book?${query}`]}>
      <Routes>
        <Route path="/appointments/book" element={<BookAppointment />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}

const patient = () => authAs("John Doe", ["patient"], PERMISSIONS.patient);

beforeEach(() => {
  vi.resetAllMocks();
  getPublicDoctor.mockResolvedValue({ data: publicDoctor() });
  getPublicAvailability.mockResolvedValue(free([{ starts_at: SLOT, ends_at: "2026-10-05T05:30:00Z" }]));
  getPublicDepartments.mockResolvedValue({ data: { items: [] } });
  getPublicDoctors.mockResolvedValue({ data: { items: [] } });
  getAvailability.mockResolvedValue({ data: { timezone: TZ, slots: [] } });
});

describe("confirmation step after choosing a time on the profile", () => {
  it("shows what will be booked, in the clinic's timezone", async () => {
    renderBooking(patient());
    expect(await screen.findByRole("heading", { name: "Review your appointment" })).toBeInTheDocument();
    expect(screen.getByText("Dr. Sarah Khan")).toBeInTheDocument();
    expect(screen.getByText(formatDateTime(SLOT, TZ))).toBeInTheDocument();
    expect(screen.getByText("150.00")).toBeInTheDocument();
    expect(screen.getByText("John Doe")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Change time" })).toHaveAttribute("href", "/doctors/doc-1#book");
    // Nothing is booked just by arriving here.
    expect(bookAppointment).not.toHaveBeenCalled();
  });

  it("books on confirmation and opens the appointment", async () => {
    const user = userEvent.setup();
    bookAppointment.mockResolvedValue({ data: { id: "appt-9" } });
    renderBooking(patient());
    await user.type(await screen.findByLabelText(/Reason for visit/), "Chest pain");
    await user.click(screen.getByRole("button", { name: "Confirm appointment" }));

    expect(bookAppointment).toHaveBeenCalledWith(
      { doctor_id: "doc-1", starts_at: SLOT, reason: "Chest pain" },
      expect.any(String) // idempotency key
    );
    expect(bookAppointment.mock.calls[0][0]).not.toHaveProperty("patient_id");
    expect(await screen.findByTestId("where")).toHaveTextContent("/appointments/appt-9Your appointment is booked.");
  });

  it("explains when the time was taken by someone else in the meantime", async () => {
    const user = userEvent.setup();
    bookAppointment.mockRejectedValue(apiError("That time is not available", 409, "SLOT_UNAVAILABLE"));
    renderBooking(patient());
    await user.click(await screen.findByRole("button", { name: "Confirm appointment" }));
    expect(await screen.findByText(/this time was just booked by someone else/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Choose another time" })).toHaveAttribute("href", "/doctors/doc-1#book");
  });

  it("does not offer a time that is no longer free", async () => {
    getPublicAvailability.mockResolvedValue(free([{ starts_at: "2026-10-05T06:00:00Z", ends_at: "2026-10-05T06:30:00Z" }]));
    renderBooking(patient());
    expect(await screen.findByText("This time is no longer available. Please choose another time.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm appointment" })).not.toBeInTheDocument();
  });

  it("rejects a malformed link without calling the API", async () => {
    renderBooking(patient(), "doctor=doc-1&slot=not-a-time");
    expect(await screen.findByText("That appointment link is not valid.")).toBeInTheDocument();
    expect(getPublicAvailability).not.toHaveBeenCalled();
  });

  it("shows other booking errors without leaving the page", async () => {
    const user = userEvent.setup();
    bookAppointment.mockRejectedValue(apiError("Complete your patient profile before booking", 400));
    renderBooking(patient());
    await user.click(await screen.findByRole("button", { name: "Confirm appointment" }));
    expect(await screen.findByText("Complete your patient profile before booking")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm appointment" })).toBeEnabled();
  });

  it("staff get the full form, where they pick the patient", async () => {
    renderBooking(authAs("Rita Front", ["receptionist"], PERMISSIONS.receptionist));
    expect(await screen.findByRole("heading", { name: "Book an appointment" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "1. Patient" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Review your appointment" })).not.toBeInTheDocument();
  });
});
