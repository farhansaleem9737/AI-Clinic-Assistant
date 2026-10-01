import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { getPublicAvailability, getPublicDoctor } from "../services/doctorService";
import { anonymous, authAs, PERMISSIONS, publicDoctor } from "../test/fixtures";
import { addMonths, longDate, monthLabel } from "../utils/calendar";
import { formatTime, isoDateIn } from "../utils/datetime";
import DoctorDetail from "./DoctorDetail";

vi.mock("../context/useAuth");
vi.mock("../services/doctorService");

const TZ = "Asia/Karachi";
const apiError = (message, status) => ({ response: { status, data: { error: { code: "X", message } } } });
const THIS_MONTH = isoDateIn(new Date()).slice(0, 7);

// Free times on the 10th (two) and 20th (one) of whichever month is asked for.
function availability(dateFrom, { empty = false, until = "2099-12-31" } = {}) {
  const month = dateFrom.slice(0, 7);
  const days = empty
    ? []
    : [
        { date: `${month}-10`, slots: [`${month}-10T04:00:00Z`, `${month}-10T04:30:00Z`] },
        { date: `${month}-20`, slots: [`${month}-20T09:00:00Z`] },
      ].map((d) => ({ ...d, slots: d.slots.map((s) => ({ starts_at: s, ends_at: s })) }));
  return { data: { doctor_id: "doc-1", timezone: TZ, bookable_until: until, days } };
}

const withHistory = publicDoctor({
  experience: [
    { title: "Senior Cardiologist", organization: "City General Hospital", location: "Lahore", start_year: 2020, end_year: null, description: "Leads the heart clinic." },
    { title: "Consultant Cardiologist", organization: "HealthCare Medical Center", location: null, start_year: 2016, end_year: 2020, description: null },
  ],
  education: [
    { qualification: "FCPS", field_of_study: "Cardiology", institution: "College of Physicians and Surgeons", start_year: 2012, end_year: 2014 },
    { qualification: "MBBS", field_of_study: null, institution: "King Edward Medical University", start_year: null, end_year: 2011 },
  ],
});

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderProfile(auth = anonymous, id = "doc-1") {
  useAuth.mockReturnValue(auth);
  return render(
    <MemoryRouter initialEntries={[`/doctors/${id}`]}>
      <Routes>
        <Route path="/doctors/:id" element={<DoctorDetail />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}

const panel = () => screen.findByRole("region", { name: "Book an Appointment" });
const day = (n, month = THIS_MONTH) => new RegExp(`^${longDate(`${month}-${String(n).padStart(2, "0")}`)}`);

beforeEach(() => {
  vi.resetAllMocks();
  getPublicDoctor.mockResolvedValue({ data: withHistory });
  getPublicAvailability.mockImplementation((id, from) => Promise.resolve(availability(from)));
});

describe("profile", () => {
  it("shows the doctor from the API with a breadcrumb", async () => {
    renderProfile();
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Dr. Sarah Khan");
    expect(getPublicDoctor).toHaveBeenCalledWith("doc-1");

    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(within(crumbs).getByRole("link", { name: "Doctors" })).toHaveAttribute("href", "/doctors");
    expect(within(crumbs).getByText("Dr. Sarah Khan")).toHaveAttribute("aria-current", "page");

    const summary = screen.getByRole("region", { name: "Summary" });
    expect(summary).toHaveTextContent("Cardiologist");
    expect(summary).toHaveTextContent("10 yearsexperience");
    expect(summary).toHaveTextContent("150.00Consultation fee");
    expect(within(summary).getByRole("link", { name: "Cardiology" })).toHaveAttribute("href", "/doctors?department=dep-1");
    expect(within(summary).getByRole("img", { name: /Verified/ })).toBeInTheDocument();
    expect(summary).toHaveTextContent("Available for appointments");
  });

  it("leaves out what the doctor has not provided instead of showing blanks", async () => {
    getPublicDoctor.mockResolvedValue({
      data: publicDoctor({
        years_of_experience: 0, consultation_fee: null, is_verified: false, bio: null, qualifications: null,
        experience: [], education: [], availability: { status: "unavailable", next_available: null },
      }),
    });
    const user = userEvent.setup();
    renderProfile();
    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(summary).not.toHaveTextContent(/experience|Consultation fee|null|undefined|NaN/);
    expect(within(summary).queryByRole("img", { name: /Verified/ })).not.toBeInTheDocument();
    expect(summary).toHaveTextContent("No appointments this week");
    expect(screen.getByText("Dr. Sarah Khan has not added a biography yet.")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Experience" }));
    expect(screen.getByText("No work history has been added yet.")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Education" }));
    expect(screen.getByText("No education has been added yet.")).toBeInTheDocument();
  });

  it("uses initials when there is no photo", async () => {
    const { container } = renderProfile();
    await screen.findByRole("heading", { level: 1 });
    expect(container.querySelector(".doctor-summary .avatar")).toHaveTextContent("SK");
    expect(container.querySelector(".doctor-summary img")).toBeNull();
  });

  it("shows the not-found page for an unknown doctor", async () => {
    getPublicDoctor.mockRejectedValue(apiError("Doctor not found", 404));
    renderProfile(anonymous, "missing");
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All doctors" })).toHaveAttribute("href", "/doctors");
    expect(getPublicAvailability).not.toHaveBeenCalled();
  });

  it("offers a retry when the profile fails to load", async () => {
    const user = userEvent.setup();
    getPublicDoctor.mockRejectedValueOnce(apiError("Service unavailable", 503));
    renderProfile();
    expect(await screen.findByText("Service unavailable")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Dr. Sarah Khan");
  });
});

describe("about, experience and education tabs", () => {
  it("switches sections with the mouse and the keyboard", async () => {
    const user = userEvent.setup();
    renderProfile();
    const about = await screen.findByRole("tab", { name: "About" });
    expect(about).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("About Dr. Sarah Khan");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Treats heart conditions.");

    await user.click(screen.getByRole("tab", { name: "Experience" }));
    const experience = screen.getByRole("tabpanel");
    expect(experience).toHaveTextContent("Senior Cardiologist");
    expect(experience).toHaveTextContent("City General Hospital, Lahore");
    expect(experience).toHaveTextContent("2020 – Present");
    expect(experience).toHaveTextContent("2016 – 2020");
    expect(experience).toHaveTextContent("Leads the heart clinic.");

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Education" })).toHaveFocus();
    const education = screen.getByRole("tabpanel");
    expect(education).toHaveTextContent("FCPS (Cardiology)");
    expect(education).toHaveTextContent("2012 – 2014");
    expect(education).toHaveTextContent("MBBS");
    expect(education).toHaveTextContent("2011");

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "About" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Education" })).toHaveAttribute("aria-selected", "true");
  });

  it("falls back to the qualifications summary when no education is listed", async () => {
    const user = userEvent.setup();
    getPublicDoctor.mockResolvedValue({ data: publicDoctor({ experience: [], education: [] }) });
    renderProfile();
    await user.click(await screen.findByRole("tab", { name: "Education" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("MBBS, FCPS (Cardiology)");
  });
});

describe("booking panel", () => {
  it("loads this month's free dates and only lets those be chosen", async () => {
    renderProfile();
    const booking = await panel();
    expect(getPublicAvailability).toHaveBeenCalledWith("doc-1", `${THIS_MONTH}-01`, expect.stringMatching(new RegExp(`^${THIS_MONTH}-(28|29|30|31)$`)));
    expect(within(booking).getByText(monthLabel(THIS_MONTH))).toBeInTheDocument();

    const tenth = await within(booking).findByRole("button", { name: day(10) });
    expect(tenth).toBeEnabled();
    expect(tenth).toHaveAccessibleName(/2 times available/);
    expect(within(booking).getByRole("button", { name: day(11) })).toBeDisabled();
    expect(within(booking).getByRole("button", { name: day(11) })).toHaveAccessibleName(/no available times/);
    expect(within(booking).getByRole("button", { name: "Previous month" })).toBeDisabled();
  });

  it("selects the first free date and shows its times from the API", async () => {
    renderProfile();
    const booking = await panel();
    expect(await within(booking).findByRole("button", { name: day(10) })).toHaveAttribute("aria-pressed", "true");
    const times = within(booking).getByRole("group", { name: /Available times on/ });
    expect(within(times).getAllByRole("button").map((b) => b.textContent)).toEqual([
      formatTime(`${THIS_MONTH}-10T04:00:00Z`, TZ),
      formatTime(`${THIS_MONTH}-10T04:30:00Z`, TZ),
    ]);
  });

  it("keeps Book appointment disabled until a time is chosen, then goes to the confirmation step", async () => {
    const user = userEvent.setup();
    renderProfile(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    const booking = await panel();
    const book = within(booking).getByRole("button", { name: "Book appointment" });
    expect(book).toBeDisabled();

    await user.click(await within(booking).findByRole("button", { name: day(20) }));
    expect(within(booking).getByRole("button", { name: day(20) })).toHaveAttribute("aria-pressed", "true");
    const time = within(booking).getByRole("button", { name: formatTime(`${THIS_MONTH}-20T09:00:00Z`, TZ) });
    expect(time).toHaveAttribute("aria-pressed", "false");
    await user.click(time);
    expect(time).toHaveAttribute("aria-pressed", "true");
    expect(booking).toHaveTextContent("Selected:");
    expect(booking).toHaveTextContent("You will be able to confirm your appointment details on the next step.");

    await user.click(book);
    expect(screen.getByTestId("where")).toHaveTextContent(
      `/appointments/book?${new URLSearchParams({ doctor: "doc-1", slot: `${THIS_MONTH}-20T09:00:00Z` })}`
    );
  });

  it("tells visitors they will be asked to sign in", async () => {
    renderProfile();
    expect(await panel()).toHaveTextContent("You will be asked to sign in or create an account first.");
  });

  it("moves between months, asking the API for each", async () => {
    const user = userEvent.setup();
    renderProfile();
    const booking = await panel();
    await within(booking).findByRole("button", { name: day(10) });

    const next = addMonths(THIS_MONTH, 1);
    await user.click(within(booking).getByRole("button", { name: "Next month" }));
    expect(await within(booking).findByText(monthLabel(next))).toBeInTheDocument();
    await waitFor(() => expect(getPublicAvailability).toHaveBeenLastCalledWith("doc-1", `${next}-01`, expect.any(String)));
    expect(await within(booking).findByRole("button", { name: day(10, next) })).toHaveAttribute("aria-pressed", "true");

    await user.click(within(booking).getByRole("button", { name: "Previous month" }));
    expect(await within(booking).findByText(monthLabel(THIS_MONTH))).toBeInTheDocument();
  });

  it("does not go past the last bookable month", async () => {
    getPublicAvailability.mockImplementation((id, from) => Promise.resolve(availability(from, { until: `${THIS_MONTH}-28` })));
    renderProfile();
    const booking = await panel();
    await within(booking).findByRole("button", { name: day(10) });
    expect(within(booking).getByRole("button", { name: "Next month" })).toBeDisabled();
  });

  it("says when a month has no free times and offers the next one", async () => {
    const user = userEvent.setup();
    getPublicAvailability.mockImplementation((id, from) =>
      Promise.resolve(availability(from, { empty: from.startsWith(THIS_MONTH) }))
    );
    renderProfile(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    const booking = await panel();
    expect(await within(booking).findByText(`No appointment times are available in ${monthLabel(THIS_MONTH)}.`)).toBeInTheDocument();
    expect(within(booking).getByRole("button", { name: "Book appointment" })).toBeDisabled();

    await user.click(within(booking).getByRole("button", { name: `Show ${monthLabel(addMonths(THIS_MONTH, 1))}` }));
    expect(await within(booking).findByRole("button", { name: day(10, addMonths(THIS_MONTH, 1)) })).toBeEnabled();
  });

  it("keeps the profile visible and retries when availability fails", async () => {
    const user = userEvent.setup();
    getPublicAvailability.mockRejectedValueOnce(apiError("Could not reach the server", 503));
    renderProfile();
    const booking = await panel();
    expect(await within(booking).findByText("Could not reach the server")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Dr. Sarah Khan");

    await user.click(within(booking).getByRole("button", { name: "Try again" }));
    expect(await within(booking).findByRole("button", { name: day(10) })).toBeEnabled();
  });

  it("does not offer booking to a role that cannot book", async () => {
    renderProfile(authAs("Sarah Khan", ["doctor"], PERMISSIONS.doctor));
    const booking = await panel();
    expect(booking).toHaveTextContent("Online booking is available to patients.");
    expect(screen.queryByRole("button", { name: "Book appointment" })).not.toBeInTheDocument();
  });

  it("the top Book appointment button only moves focus to the booking panel", async () => {
    const user = userEvent.setup();
    renderProfile(authAs("John Doe", ["patient"], PERMISSIONS.patient));
    const summary = await screen.findByRole("region", { name: "Summary" });
    await user.click(within(summary).getByRole("button", { name: "Book appointment" }));
    expect(screen.getByRole("heading", { name: "Book an Appointment" })).toHaveFocus();
    expect(screen.queryByTestId("where")).not.toBeInTheDocument(); // still on the profile
  });
});
