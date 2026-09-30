import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { getPublicDoctor } from "../services/doctorService";
import { getAvailability } from "../services/scheduleService";
import { anonymous, authAs, PERMISSIONS, publicDoctor } from "../test/fixtures";
import { formatTime } from "../utils/datetime";
import DoctorDetail from "./DoctorDetail";

vi.mock("../context/useAuth");
vi.mock("../services/doctorService");
vi.mock("../services/scheduleService");

const apiError = (message) => ({ response: { data: { error: { code: "X", message } } } });
// Tomorrow at 07:00 UTC: inside the week the slot picker shows.
const tomorrow = new Date(Date.now() + 24 * 3600 * 1000);
tomorrow.setUTCHours(7, 0, 0, 0);
const SLOT = tomorrow.toISOString();
const TIMEZONE = "Asia/Karachi";

function renderProfile(auth = anonymous, id = "doc-1") {
  useAuth.mockReturnValue(auth);
  return render(
    <MemoryRouter initialEntries={[`/doctors/${id}`]}>
      <Routes>
        <Route path="/doctors/:id" element={<DoctorDetail />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  getPublicDoctor.mockResolvedValue({ data: publicDoctor() });
  getAvailability.mockResolvedValue({ data: { timezone: TIMEZONE, slots: [{ starts_at: SLOT, ends_at: SLOT }] } });
});

describe("doctor profile", () => {
  it("loads the doctor named in the URL and shows the public details", async () => {
    renderProfile();
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Dr. Sarah Khan");
    expect(getPublicDoctor).toHaveBeenCalledWith("doc-1");
    expect(screen.getByRole("img", { name: /Verified/ })).toBeInTheDocument();
    expect(screen.getByText("Taking appointments")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "About" })).toHaveTextContent("Treats heart conditions.");

    const details = screen.getByRole("complementary", { name: "Details" });
    expect(details).toHaveTextContent("10 years");
    expect(details).toHaveTextContent("150.00");
    expect(details).toHaveTextContent("MBBS, FCPS (Cardiology)");
    expect(within(details).getByRole("link", { name: "Cardiology" })).toHaveAttribute("href", "/doctors?department=dep-1");
  });

  it("asks a visitor to sign in instead of loading appointment times", async () => {
    renderProfile();
    const times = await screen.findByRole("region", { name: "Appointment times" });
    expect(times).toHaveTextContent("Next free time from");
    expect(within(times).getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(within(times).getByRole("link", { name: "Create account" })).toHaveAttribute("href", "/register");
    expect(getAvailability).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Book appointment" })).toHaveAttribute("href", "/appointments/book?doctor=doc-1");
  });

  it("lets a signed-in patient pick a time and carry it to the booking page", async () => {
    const user = userEvent.setup();
    renderProfile(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    const times = await screen.findByRole("region", { name: "Appointment times" });
    expect(getAvailability).toHaveBeenCalledWith("doc-1", expect.any(String), expect.any(String));

    await user.click(await within(times).findByRole("button", { name: formatTime(SLOT, TIMEZONE) }));
    expect(times).toHaveTextContent("Selected:");
    expect(within(times).getByRole("link", { name: "Book appointment" })).toHaveAttribute(
      "href",
      `/appointments/book?${new URLSearchParams({ doctor: "doc-1", slot: SLOT })}`
    );
  });

  it("says so when the doctor is not taking appointments", async () => {
    getPublicDoctor.mockResolvedValue({ data: publicDoctor({ availability: { status: "unavailable", next_available: null } }) });
    renderProfile(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    expect(await screen.findByText("This doctor has no bookable times at the moment.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Book appointment" })).toBeDisabled();
    expect(getAvailability).not.toHaveBeenCalled();
  });

  it("does not offer booking to a role that cannot book", async () => {
    renderProfile(authAs("Sarah Khan", ["doctor"], PERMISSIONS.doctor));
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText("Book appointment")).not.toBeInTheDocument();
  });

  it("handles a missing biography and qualifications", async () => {
    getPublicDoctor.mockResolvedValue({ data: publicDoctor({ bio: null, qualifications: null, is_verified: false }) });
    renderProfile();
    expect(await screen.findByText("This doctor has not added a biography yet.")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Details" })).toHaveTextContent("Not listed");
    expect(screen.queryByRole("img", { name: /Verified/ })).not.toBeInTheDocument();
  });

  it("shows the API error for an unknown doctor with a way back", async () => {
    getPublicDoctor.mockRejectedValue(apiError("Doctor not found"));
    renderProfile(anonymous, "missing");
    expect(await screen.findByText("Doctor not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /All doctors/ })).toHaveAttribute("href", "/doctors");
  });
});
