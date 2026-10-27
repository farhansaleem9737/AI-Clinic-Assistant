import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import {
  getMyCareer,
  getMyDoctorProfile,
  updateMyDoctorProfile,
  uploadMyDoctorPhoto,
} from "../services/doctorService";
import { authAs, doctorProfile, PERMISSIONS } from "../test/fixtures";
import MyDoctorProfile from "./MyDoctorProfile";

vi.mock("../context/useAuth");
vi.mock("../services/doctorService");

const PROFILE = {
  ...doctorProfile,
  department_id: "dep-1",
  qualifications: "MBBS, FCPS (Cardiology)",
  languages: "English, Urdu",
  bio: "Treats heart conditions.\n\nFocuses on prevention.",
  phone: "555-0100",
  is_verified: true,
  is_active: true,
  photo_url: null,
};
const apiError = (message, details) => ({
  response: { status: 422, data: { error: { code: details ? "VALIDATION_ERROR" : "X", message, details } } },
});

let fetchCurrentUser;
function renderPage(permissions = PERMISSIONS.doctor) {
  fetchCurrentUser = vi.fn().mockResolvedValue();
  useAuth.mockReturnValue({ ...authAs("Sarah Khan", ["doctor"], permissions), fetchCurrentUser });
  return render(
    <MemoryRouter>
      <MyDoctorProfile />
    </MemoryRouter>
  );
}

beforeAll(() => {
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});
afterAll(() => {
  delete URL.createObjectURL;
  delete URL.revokeObjectURL;
});

beforeEach(() => {
  vi.resetAllMocks();
  getMyDoctorProfile.mockResolvedValue({ data: PROFILE });
  getMyCareer.mockResolvedValue({ data: { experience: [], education: [] } });
});

describe("My Professional Profile", () => {
  it("shows the signed-in doctor's real details in the summary", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "My Professional Profile" })).toBeInTheDocument();
    const summary = await screen.findByRole("region", { name: "Profile summary" });
    expect(within(summary).getByRole("heading", { name: /Dr\. Sarah Khan/ })).toBeInTheDocument();
    expect(within(summary).getByRole("img", { name: /Verified/ })).toBeInTheDocument();
    expect(summary).toHaveTextContent("Cardiologist");
    expect(summary).toHaveTextContent("Active");
    expect(summary).toHaveTextContent("10 years experience");
    expect(summary).toHaveTextContent("Room B-12");
    expect(summary).toHaveTextContent("150.00");
    expect(summary.querySelector('[data-avatar="doctor"]')).not.toBeNull(); // illustrated fallback
  });

  it("does not claim verification without a license on file", async () => {
    getMyDoctorProfile.mockResolvedValue({ data: { ...PROFILE, is_verified: false, license_number: null, languages: null } });
    renderPage();
    const summary = await screen.findByRole("region", { name: "Profile summary" });
    expect(within(summary).queryByRole("img", { name: /Verified/ })).not.toBeInTheDocument();
    const info = screen.getByRole("region", { name: "Professional Information" });
    expect(within(info).getAllByText("Not provided").length).toBeGreaterThanOrEqual(2); // license, languages
  });

  it("links the tabs to the real pages, marking Profile as current", async () => {
    renderPage();
    const nav = await screen.findByRole("navigation", { name: "Doctor pages" });
    expect(within(nav).getByRole("link", { name: "Profile" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Schedule" })).toHaveAttribute("href", "/schedule");
    expect(within(nav).getByRole("link", { name: "Appointments" })).toHaveAttribute("href", "/appointments");
  });

  it("hides tabs for pages the doctor cannot use", async () => {
    renderPage(["doctor:update_own"]);
    const nav = await screen.findByRole("navigation", { name: "Doctor pages" });
    expect(within(nav).queryByRole("link", { name: "Schedule" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Appointments" })).not.toBeInTheDocument();
  });

  it("lists the professional information, keeping the bio's paragraphs", async () => {
    renderPage();
    const info = await screen.findByRole("region", { name: "Professional Information" });
    for (const text of ["Cardiologist", "Cardiology", "10 years", "PMC-1", "English, Urdu", "MBBS, FCPS (Cardiology)"]) {
      expect(info).toHaveTextContent(text);
    }
    expect(within(info).getByText("Treats heart conditions.").tagName).toBe("P");
    expect(within(info).getByText("Focuses on prevention.").tagName).toBe("P");
  });

  it("shows clinic information from the record and says what is not set up", async () => {
    renderPage();
    const clinic = await screen.findByRole("region", { name: "Clinic Information" });
    expect(clinic).toHaveTextContent("Cardiology");
    expect(clinic).toHaveTextContent("B-12");
    expect(clinic).toHaveTextContent("150.00");
    expect(clinic).toHaveTextContent("Active");
    expect(clinic).toHaveTextContent(/name and address are not set up/);
  });

  it("edits only the doctor's own fields and shows the saved values", async () => {
    const user = userEvent.setup();
    updateMyDoctorProfile.mockResolvedValue({ data: { ...PROFILE, languages: "English, Urdu, Punjabi", years_of_experience: 12 } });
    renderPage();
    await user.click(await screen.findByRole("button", { name: /Edit Profile/ }));
    const dialog = screen.getByRole("dialog", { name: "Edit profile" });
    expect(within(dialog).getByLabelText("Languages")).toHaveValue("English, Urdu");
    // Administration-managed values are shown, not editable.
    expect(within(dialog).queryByLabelText("Specialization")).not.toBeInTheDocument();
    expect(dialog).toHaveTextContent("Managed by the clinic administration");

    const languages = within(dialog).getByLabelText("Languages");
    await user.clear(languages);
    await user.type(languages, "English, Urdu, Punjabi");
    const years = within(dialog).getByLabelText("Years of experience");
    await user.clear(years);
    await user.type(years, "12");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    expect(updateMyDoctorProfile).toHaveBeenCalledWith({
      years_of_experience: 12,
      languages: "English, Urdu, Punjabi",
      qualifications: "MBBS, FCPS (Cardiology)",
      phone: "555-0100",
      bio: "Treats heart conditions.\n\nFocuses on prevention.",
    });
    expect(await screen.findByText("Your profile was saved")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Professional Information" })).toHaveTextContent("English, Urdu, Punjabi");
  });

  it("checks the experience value before sending", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: /Edit Profile/ }));
    const years = screen.getByLabelText("Years of experience");
    await user.clear(years);
    await user.type(years, "-3");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByText("Enter a whole number of years from 0 to 80.")).toBeInTheDocument();
    expect(years).toHaveAttribute("aria-invalid", "true");
    expect(updateMyDoctorProfile).not.toHaveBeenCalled();
  });

  it("puts the server's validation message under the field", async () => {
    const user = userEvent.setup();
    updateMyDoctorProfile.mockRejectedValue(
      apiError("Request validation failed", { errors: [{ loc: ["body", "languages"], msg: "String should have at most 200 characters" }] })
    );
    renderPage();
    await user.click(await screen.findByRole("button", { name: /Edit Profile/ }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("String should have at most 200 characters")).toBeInTheDocument();
    expect(screen.getByLabelText("Languages")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("Cancel closes the editor without saving", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: /Edit Profile/ }));
    await user.type(screen.getByLabelText("Languages"), ", French");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(updateMyDoctorProfile).not.toHaveBeenCalled();
    expect(screen.getByRole("region", { name: "Professional Information" })).not.toHaveTextContent("French");
  });

  it("previews a new photo, uploads it on confirmation and refreshes the header", async () => {
    const user = userEvent.setup();
    uploadMyDoctorPhoto.mockResolvedValue({ data: { ...PROFILE, photo_url: "https://r2.test/doc.webp" } });
    const { container } = renderPage();
    const card = await screen.findByRole("region", { name: "Profile Picture" });
    const png = new File([new Uint8Array([137, 80, 78, 71])], "me.png", { type: "image/png" });

    await user.upload(container.querySelector('input[type="file"]'), png);
    expect(within(card).getByRole("img", { name: /Preview of the new photo/ })).toHaveAttribute("src", "blob:preview");
    expect(uploadMyDoctorPhoto).not.toHaveBeenCalled(); // nothing sent before confirming

    await user.click(within(card).getByRole("button", { name: "Cancel" }));
    expect(within(card).queryByRole("img", { name: /Preview/ })).not.toBeInTheDocument();

    await user.upload(container.querySelector('input[type="file"]'), png);
    await user.click(within(card).getByRole("button", { name: "Upload photo" }));
    expect(uploadMyDoctorPhoto).toHaveBeenCalledWith(png);
    expect(fetchCurrentUser).toHaveBeenCalled();
    const photos = await screen.findAllByRole("img", { name: "Photo of Dr. Sarah Khan" });
    expect(photos.every((img) => img.getAttribute("src") === "https://r2.test/doc.webp")).toBe(true);
  });

  it("rejects an oversized photo before uploading", async () => {
    const user = userEvent.setup();
    const { container } = renderPage();
    await screen.findByRole("region", { name: "Profile Picture" });
    const huge = new File([new Uint8Array(5 * 1024 * 1024 + 1)], "big.png", { type: "image/png" });
    await user.upload(container.querySelector('input[type="file"]'), huge);
    expect(screen.getByText("The photo must be 5 MB or smaller.")).toBeInTheDocument();
    expect(uploadMyDoctorPhoto).not.toHaveBeenCalled();
  });

  it("explains a loading failure and can retry", async () => {
    const user = userEvent.setup();
    getMyDoctorProfile.mockRejectedValueOnce(apiError("Service unavailable"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Profile summary" })).toBeInTheDocument();
  });

  it("explains when the login has no doctor profile", async () => {
    getMyDoctorProfile.mockRejectedValue({
      response: { status: 404, data: { error: { code: "NO_DOCTOR_PROFILE", message: "You do not have a doctor profile" } } },
    });
    renderPage();
    expect(await screen.findByText(/does not have a doctor profile yet/)).toBeInTheDocument();
  });
});
