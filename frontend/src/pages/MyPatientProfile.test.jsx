import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { getDashboardSummary } from "../services/dashboardService";
import {
  completeMyPatientProfile,
  getMyPatientProfile,
  updateMyDetails,
  uploadMyPatientPhoto,
} from "../services/patientService";
import { authAs, patientProfile, PERMISSIONS, summaries } from "../test/fixtures";
import { changePassword, getPasswordStatus } from "../services/authService";
import MyPatientProfile from "./MyPatientProfile";

vi.mock("../context/useAuth");
vi.mock("../services/patientService");
vi.mock("../services/dashboardService");
vi.mock("../services/authService");
vi.mock("../services/api", async (original) => ({ ...(await original()), setAccessToken: vi.fn() }));

const PROFILE = {
  ...patientProfile,
  first_name: "Farhan",
  last_name: "Saleem",
  date_of_birth: "1999-08-04",
  sex_at_birth: "male",
  phone: "+92 3001234567",
  email: "farhan@example.com",
  address: "House 5, Johar Town",
  city: "Lahore",
  province: "Punjab",
  country: "PK",
  blood_group: null,
  marital_status: null,
  national_id_masked: null,
  photo_url: null,
  updated_at: "2026-11-05T09:00:00Z",
};
const apiError = (message, code = "X", status = 400) => ({ response: { status, data: { error: { code, message } } } });

let fetchCurrentUser;
function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}
function renderPage(path = "/profile", profile = PROFILE) {
  fetchCurrentUser = vi.fn().mockResolvedValue();
  const auth = authAs("Farhan Saleem", ["patient"], PERMISSIONS.patient);
  useAuth.mockReturnValue({
    ...auth,
    user: { ...auth.user, email: "signin@example.com", created_at: "2026-10-29T08:00:00Z" },
    fetchCurrentUser,
  });
  if (profile) getMyPatientProfile.mockResolvedValue({ data: profile });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/profile" element={<MyPatientProfile />} />
        <Route path="/profile/contact" element={<MyPatientProfile />} />
        <Route path="/dashboard" element={<p>Dashboard page</p>} />
      </Routes>
      <Link to="/dashboard">Go to dashboard</Link>
      <Where />
    </MemoryRouter>
  );
}
const saveButton = () => screen.getByRole("button", { name: /Save Changes/ });

beforeEach(() => {
  vi.clearAllMocks();
  getDashboardSummary.mockResolvedValue({ data: summaries.patient });
});
afterEach(() => vi.restoreAllMocks());

describe("Personal Information", () => {
  it("shows the real record: overview, MRN, member since, and the form filled in", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Personal Information" })).toBeInTheDocument();
    const overview = await screen.findByRole("region", { name: "Profile overview" });
    expect(within(overview).getByRole("heading", { name: "Farhan Saleem" })).toBeInTheDocument();
    expect(overview).toHaveTextContent("Patient");
    expect(await within(overview).findByText("Active")).toBeInTheDocument();
    expect(overview).toHaveTextContent("MRN00000001");
    expect(overview).toHaveTextContent("29 Oct 2026"); // the account's creation date
    expect(screen.getByLabelText("Full Name *")).toHaveValue("Farhan Saleem");
    expect(screen.getByLabelText("Date of Birth *")).toHaveValue("1999-08-04");
    expect(screen.getByRole("radio", { name: "Male" })).toBeChecked();
    expect(screen.getByLabelText("Blood Group")).toHaveValue("");
    expect(screen.getByLabelText("Marital Status")).toHaveValue("");
    expect(screen.getByText("Not provided")).toBeInTheDocument();
    expect(saveButton()).toBeDisabled(); // nothing changed yet
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });

  it("shows Inactive for a deactivated record, and no badge when the status is unknown", async () => {
    getDashboardSummary.mockResolvedValue({ data: { ...summaries.patient, patient: { ...summaries.patient.patient, profile_active: false } } });
    const { unmount } = renderPage();
    expect(await screen.findByText("Inactive")).toBeInTheDocument();
    unmount();
    getDashboardSummary.mockRejectedValue(apiError("down"));
    renderPage();
    await screen.findByRole("region", { name: "Profile overview" });
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
  });

  it("checks the name and date of birth before sending anything", async () => {
    const user = userEvent.setup();
    renderPage();
    const name = await screen.findByLabelText("Full Name *");
    await user.clear(name);
    await user.type(name, "Farhan");
    await user.clear(screen.getByLabelText("Date of Birth *"));
    await user.type(screen.getByLabelText("Date of Birth *"), "2999-01-01");
    await user.click(saveButton());
    expect(screen.getByText("Enter your first and last name.")).toBeInTheDocument();
    expect(screen.getByText("Date of birth cannot be in the future.")).toBeInTheDocument();
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(updateMyDetails).not.toHaveBeenCalled();
  });

  it("sends only what changed, shows it once saved, and refreshes the top bar", async () => {
    const user = userEvent.setup();
    const saved = { ...PROFILE, first_name: "Farhan Ali", blood_group: "O+", marital_status: "single", updated_at: "2026-11-05T10:00:00Z" };
    updateMyDetails.mockResolvedValue({ data: saved });
    renderPage();
    const name = await screen.findByLabelText("Full Name *");
    await user.clear(name);
    await user.type(name, "Farhan Ali Saleem");
    await user.selectOptions(screen.getByLabelText("Blood Group"), "O+");
    await user.selectOptions(screen.getByLabelText("Marital Status"), "single");
    await user.click(saveButton());
    expect(updateMyDetails).toHaveBeenCalledTimes(1);
    expect(updateMyDetails).toHaveBeenCalledWith({ first_name: "Farhan Ali", last_name: "Saleem", blood_group: "O+", marital_status: "single" });
    expect(await screen.findByText("Your personal details were saved.")).toBeInTheDocument();
    expect(fetchCurrentUser).toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Farhan Ali Saleem" })).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });

  it("adds a CNIC only when it is valid, and shows it masked afterwards", async () => {
    const user = userEvent.setup();
    updateMyDetails.mockResolvedValue({ data: { ...PROFILE, national_id_masked: "•••••-•••••67-1" } });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Add" }));
    const field = screen.getByLabelText("CNIC / National ID (Optional)");
    await user.type(field, "12345");
    await user.click(saveButton());
    expect(screen.getByText("Enter the 13-digit CNIC as 12345-1234567-1.")).toBeInTheDocument();
    expect(updateMyDetails).not.toHaveBeenCalled();
    await user.clear(field);
    await user.type(field, "3410112345671");
    await user.click(saveButton());
    expect(updateMyDetails).toHaveBeenCalledWith({ national_id: "3410112345671" });
    expect(await screen.findByText("•••••-•••••67-1")).toBeInTheDocument();
  });

  it("a failed save keeps the edits and explains; Cancel restores the saved values", async () => {
    const user = userEvent.setup();
    updateMyDetails.mockRejectedValue(apiError("The server is busy", "X", 503));
    renderPage();
    const name = await screen.findByLabelText("Full Name *");
    await user.clear(name);
    await user.type(name, "Someone Else");
    await user.click(saveButton());
    expect(await screen.findByRole("alert")).toHaveTextContent("The server is busy");
    expect(name).toHaveValue("Someone Else");
    expect(screen.queryByText(/were saved/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(name).toHaveValue("Farhan Saleem");
    expect(saveButton()).toBeDisabled();
  });

  it("the camera button checks the picture, previews it, then saves it", async () => {
    const user = userEvent.setup({ applyAccept: false });
    uploadMyPatientPhoto.mockResolvedValue({ data: { ...PROFILE, photo_url: "https://r2.test/p.webp" } });
    renderPage();
    await screen.findByRole("region", { name: "Profile overview" });
    expect(screen.getByRole("button", { name: "Change profile picture" })).toBeInTheDocument();
    const input = screen.getByLabelText("Profile picture file");
    await user.upload(input, new File(["%PDF"], "doc.pdf", { type: "application/pdf" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a JPEG, PNG or WebP picture.");
    await user.upload(input, new File([new Uint8Array(6 * 1024 * 1024)], "big.png", { type: "image/png" }));
    expect(screen.getByRole("alert")).toHaveTextContent("5 MB or smaller");
    const png = new File([new Uint8Array([137, 80, 78, 71])], "me.png", { type: "image/png" });
    await user.upload(input, png);
    const dialog = screen.getByRole("dialog", { name: "New profile picture" });
    expect(within(dialog).getByRole("img", { name: "Preview of the new profile picture" })).toBeInTheDocument();
    expect(uploadMyPatientPhoto).not.toHaveBeenCalled(); // nothing sent before Save
    await user.click(within(dialog).getByRole("button", { name: "Save picture" }));
    expect(uploadMyPatientPhoto).toHaveBeenCalledWith(png);
    expect(await screen.findByText("Your profile picture was updated.")).toBeInTheDocument();
    expect(fetchCurrentUser).toHaveBeenCalled();
    await waitFor(() => expect(document.querySelector('.pp-overview img[src="https://r2.test/p.webp"]')).not.toBeNull());
  });

  it("asks before leaving with unsaved changes", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();
    const name = await screen.findByLabelText("Full Name *");
    await user.type(name, " Junior");
    await user.click(screen.getByRole("link", { name: "Go to dashboard" }));
    expect(confirm).toHaveBeenCalled();
    expect(screen.getByTestId("where")).toHaveTextContent("/profile");
    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    confirm.mockReturnValue(true);
    await user.click(screen.getByRole("link", { name: "Go to dashboard" }));
    expect(await screen.findByText("Dashboard page")).toBeInTheDocument();
  });
});

describe("Contact Information", () => {
  it("shows the saved contact details and fills the form, without touching the sign-in email", async () => {
    renderPage("/profile/contact");
    expect(screen.getByRole("heading", { level: 1, name: "Contact Information" })).toBeInTheDocument();
    const overview = await screen.findByRole("region", { name: "Contact Overview" });
    expect(overview).toHaveTextContent("+92 3001234567");
    expect(overview).toHaveTextContent("farhan@example.com");
    expect(overview).toHaveTextContent("House 5, Johar Town, Lahore, Punjab, Pakistan");
    expect(overview).toHaveTextContent("Why we need this?");
    expect(overview).toHaveTextContent("signin@example.com");
    expect(screen.getByLabelText("Country calling code")).toHaveValue("92");
    expect(screen.getByLabelText("Phone Number *")).toHaveValue("3001234567");
    expect(screen.getByLabelText("Email Address *")).toHaveValue("farhan@example.com");
    expect(screen.getByLabelText("Province / State *")).toHaveValue("Punjab");
    expect(screen.getByLabelText("Country *")).toHaveValue("PK");
    expect(saveButton()).toBeDisabled();
  });

  it("checks the phone and email", async () => {
    const user = userEvent.setup();
    renderPage("/profile/contact");
    const phone = await screen.findByLabelText("Phone Number *");
    await user.clear(phone);
    await user.type(phone, "300123");
    const email = screen.getByLabelText("Email Address *");
    await user.clear(email);
    await user.type(email, "not-an-email");
    await user.click(saveButton());
    expect(screen.getByText(/A Pakistani number has 10 digits/)).toBeInTheDocument();
    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument();
    expect(updateMyDetails).not.toHaveBeenCalled();
  });

  it("offers Pakistan's provinces and city suggestions, and free text elsewhere", async () => {
    const user = userEvent.setup();
    renderPage("/profile/contact", { ...PROFILE, city: null, province: null, country: null });
    const country = await screen.findByLabelText("Country *");
    await user.selectOptions(country, "PK");
    const province = screen.getByLabelText("Province / State *");
    expect(within(province).getByRole("option", { name: "Sindh" })).toBeInTheDocument();
    expect(within(province).getByRole("option", { name: "Gilgit-Baltistan" })).toBeInTheDocument();
    expect(document.querySelector('#pp-city-options option[value="Karachi"]')).not.toBeNull();
    await user.selectOptions(country, "GB");
    expect(screen.getByLabelText("Province / State *").tagName).toBe("INPUT");
  });

  it("saves only what changed; a new number gets its calling code, an untouched one is never rewritten", async () => {
    const user = userEvent.setup();
    updateMyDetails.mockResolvedValue({ data: { ...PROFILE, city: "Karachi", province: "Sindh", updated_at: "2026-11-05T11:00:00Z" } });
    renderPage("/profile/contact", { ...PROFILE, phone: "00001111111" });
    const city = await screen.findByLabelText("City *");
    await user.clear(city);
    await user.type(city, "Karachi");
    await user.selectOptions(screen.getByLabelText("Province / State *"), "Sindh");
    await user.click(saveButton());
    expect(updateMyDetails).toHaveBeenLastCalledWith({ city: "Karachi", province: "Sindh" }); // the legacy phone is left alone
    expect(await screen.findByText("Your contact details were saved.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Contact Overview" })).toHaveTextContent("Karachi, Sindh");

    updateMyDetails.mockResolvedValue({ data: { ...PROFILE, phone: "+92 3211234567" } });
    const phone = screen.getByLabelText("Phone Number *");
    await user.clear(phone);
    await user.type(phone, "03211234567");
    await user.click(saveButton());
    expect(updateMyDetails).toHaveBeenLastCalledWith({ phone: "+92 3211234567" });
  });

  it("a failed save explains and keeps the edits", async () => {
    const user = userEvent.setup();
    updateMyDetails.mockRejectedValue(new Error("Network Error"));
    renderPage("/profile/contact");
    const address = await screen.findByLabelText("Address *");
    await user.clear(address);
    await user.type(address, "New Street 1");
    await user.click(saveButton());
    expect(await screen.findByRole("alert")).toHaveTextContent("Your changes could not be saved");
    expect(address).toHaveValue("New Street 1");
  });
});

describe("loading", () => {
  it("explains a loading failure and can try again", async () => {
    const user = userEvent.setup();
    getMyPatientProfile.mockRejectedValueOnce(apiError("Service unavailable"));
    renderPage("/profile", null);
    getMyPatientProfile.mockResolvedValue({ data: PROFILE });
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Profile overview" })).toBeInTheDocument();
  });

  it("asks a new patient to complete their profile first", async () => {
    const user = userEvent.setup();
    getMyPatientProfile.mockRejectedValueOnce(apiError("No profile", "NO_PATIENT_PROFILE"));
    completeMyPatientProfile.mockResolvedValue({ data: PROFILE });
    renderPage("/profile", null);
    await screen.findByRole("heading", { name: "Complete your patient profile" });
    await user.type(screen.getByLabelText("First name"), "Farhan");
    await user.type(screen.getByLabelText("Last name"), "Saleem");
    await user.type(screen.getByLabelText("Date of birth"), "1999-08-04");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(completeMyPatientProfile).toHaveBeenCalledWith(expect.objectContaining({ first_name: "Farhan", last_name: "Saleem" }));
    expect(fetchCurrentUser).toHaveBeenCalled();
    expect(await screen.findByRole("region", { name: "Profile overview" })).toBeInTheDocument();
  });
});

describe("Change Password on Personal Information (D116)", () => {
  it("sits with the form's actions, opens the shared dialog and reports success on the page", async () => {
    getPasswordStatus.mockResolvedValue({ data: { current_password_required: false } });
    changePassword.mockResolvedValue({ data: { access_token: "fresh", token_type: "bearer", expires_in: 900 } });
    const user = userEvent.setup();
    renderPage();
    const button = await screen.findByRole("button", { name: "Change Password" });
    expect(button.closest(".pp-actions")).toContainElement(saveButton());
    expect(button).toBeEnabled(); // independent of unsaved form changes

    await user.click(button);
    const dialog = await screen.findByRole("dialog", { name: "Change Password" });
    await user.type(await within(dialog).findByLabelText("New password"), "a fresh passphrase");
    await user.type(within(dialog).getByLabelText("Confirm new password"), "a fresh passphrase");
    await user.click(within(dialog).getByRole("button", { name: "Update Password" }));

    expect(await screen.findByText("Your password has been updated successfully.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(changePassword).toHaveBeenCalledWith({ new_password: "a fresh passphrase" });
  });

  it("Cancel leaves the password and the form untouched", async () => {
    getPasswordStatus.mockResolvedValue({ data: { current_password_required: true } });
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Change Password" }));
    const dialog = await screen.findByRole("dialog", { name: "Change Password" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(changePassword).not.toHaveBeenCalled();
    expect(saveButton()).toBeDisabled();
  });
});
