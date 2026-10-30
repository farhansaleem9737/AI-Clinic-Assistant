import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { getDashboardSummary } from "../services/dashboardService";
import { listDocuments } from "../services/documentService";
import {
  completeMyPatientProfile,
  getMyPatientProfile,
  updateMyDetails,
  uploadMyPatientPhoto,
} from "../services/patientService";
import { authAs, patientProfile, PERMISSIONS, summaries } from "../test/fixtures";
import { ageFromDateOfBirth } from "../utils/patient";
import MyPatientProfile from "./MyPatientProfile";

vi.mock("../context/useAuth");
vi.mock("../services/patientService");
vi.mock("../services/dashboardService");
vi.mock("../services/documentService", async (importOriginal) => ({
  ...(await importOriginal()),
  listDocuments: vi.fn(),
}));

const DOCUMENT_PERMISSIONS = ["document:read_own", "document:upload_own", "document:retract_own"];
const apiError = (message, code = "X") => ({ response: { data: { error: { code, message } } } });

let fetchCurrentUser;

function renderPage() {
  fetchCurrentUser = vi.fn().mockResolvedValue();
  useAuth.mockReturnValue({
    ...authAs("John Doe", ["patient"], [...PERMISSIONS.patient, ...DOCUMENT_PERMISSIONS]),
    fetchCurrentUser,
  });
  return render(
    <MemoryRouter>
      <MyPatientProfile />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  getMyPatientProfile.mockResolvedValue({ data: { ...patientProfile, preferred_language: null, photo_url: null } });
  getDashboardSummary.mockResolvedValue({ data: summaries.patient });
  listDocuments.mockResolvedValue({ data: [] });
});

describe("My Profile", () => {
  it("shows the patient's real details in the summary", async () => {
    renderPage();
    const summary = await screen.findByRole("region", { name: "Profile summary" });
    expect(within(summary).getByRole("heading", { name: "John Doe" })).toBeInTheDocument();
    expect(summary).toHaveTextContent("Patient · MRN00000001");
    expect(await within(summary).findByText("Active")).toBeInTheDocument();
    expect(summary).toHaveTextContent(`${ageFromDateOfBirth("1990-01-01")} years`);
    expect(summary).toHaveTextContent("Male");
    expect(screen.getByRole("heading", { level: 1, name: "My Profile" })).toBeInTheDocument();
  });

  it("says Inactive when reception has deactivated the record", async () => {
    getDashboardSummary.mockResolvedValue({
      data: { ...summaries.patient, patient: { ...summaries.patient.patient, profile_active: false } },
    });
    renderPage();
    expect(await screen.findByText("Inactive")).toBeInTheDocument();
  });

  it("shows no status at all when it cannot be loaded, rather than guessing", async () => {
    getDashboardSummary.mockRejectedValue(apiError("down"));
    renderPage();
    await screen.findByRole("region", { name: "Profile summary" });
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
    expect(screen.queryByText("Inactive")).not.toBeInTheDocument();
  });

  it("starts on Personal Information with the personal and contact cards", async () => {
    renderPage();
    const personal = await screen.findByRole("region", { name: "Personal Information" });
    expect(within(personal).getByText("John Doe")).toBeInTheDocument();
    const contact = screen.getByRole("region", { name: "Contact Information" });
    expect(contact).toHaveTextContent("+1 234 567 890");
    expect(contact).toHaveTextContent("john@example.com");
    // Missing optional data reads "Not provided", not a blank.
    expect(within(contact).getByText("Not provided")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Personal Information" })).toHaveAttribute("aria-selected", "true");
  });

  it("switches sections with clicks and with the arrow keys", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("region", { name: "Personal Information" });

    await user.click(screen.getByRole("tab", { name: "Contact Information" }));
    expect(screen.queryByRole("region", { name: "Personal Information" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Contact Information" })).toBeInTheDocument();

    await user.keyboard("{ArrowRight}");
    const medicalTab = screen.getByRole("tab", { name: "Medical Information" });
    expect(medicalTab).toHaveAttribute("aria-selected", "true");
    expect(medicalTab).toHaveFocus();
    expect(screen.getByText(/not available in the app yet/)).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Documents" })).toBeInTheDocument();
    expect(listDocuments).toHaveBeenCalledWith("pat-1");
  });

  it("edits only the contact details and shows the saved values", async () => {
    const user = userEvent.setup();
    updateMyDetails.mockResolvedValue({ data: { ...patientProfile, phone: "555-0199", photo_url: null } });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Edit contact details" }));

    const dialog = screen.getByRole("dialog", { name: "Edit contact details" });
    expect(within(dialog).queryByLabelText("First name")).not.toBeInTheDocument();
    const phone = within(dialog).getByLabelText("Phone");
    await user.clear(phone);
    await user.type(phone, "555-0199");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    expect(updateMyDetails).toHaveBeenCalledWith({
      phone: "555-0199",
      email: "john@example.com",
      address: "123 Main St",
      preferred_language: null,
    });
    expect(await screen.findByText("Your contact details were saved")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Contact Information" })).toHaveTextContent("555-0199");
  });

  it("keeps the dialog open and shows the error when saving fails", async () => {
    const user = userEvent.setup();
    updateMyDetails.mockRejectedValue(apiError("Phone number is too long"));
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Edit Profile" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(await within(dialog).findByText("Phone number is too long")).toBeInTheDocument();
  });

  it("edits the personal details from the Personal Information card", async () => {
    const user = userEvent.setup();
    updateMyDetails.mockResolvedValue({
      data: { ...patientProfile, first_name: "Jonathan", sex_at_birth: "male", photo_url: null },
    });
    renderPage();
    const personal = await screen.findByRole("region", { name: "Personal Information" });
    await user.click(within(personal).getByRole("button", { name: "Edit personal details" }));

    const dialog = screen.getByRole("dialog", { name: "Edit personal details" });
    expect(within(dialog).queryByLabelText("Phone")).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/MRN|record number/i)).not.toBeInTheDocument();
    expect(within(dialog).getByRole("option", { name: "Male" })).toBeInTheDocument();
    const first = within(dialog).getByLabelText("First name");
    await user.clear(first);
    await user.type(first, "Jonathan");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    expect(updateMyDetails).toHaveBeenCalledWith({
      first_name: "Jonathan",
      last_name: "Doe",
      date_of_birth: "1990-01-01",
      sex_at_birth: "male",
    });
    expect(await screen.findByText("Your personal details were saved")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Personal Information" })).toHaveTextContent("Jonathan Doe");
  });

  it("does not send personal details with a blank name", async () => {
    const user = userEvent.setup();
    renderPage();
    const personal = await screen.findByRole("region", { name: "Personal Information" });
    await user.click(within(personal).getByRole("button", { name: "Edit personal details" }));
    const dialog = screen.getByRole("dialog", { name: "Edit personal details" });
    await user.clear(within(dialog).getByLabelText("Last name"));
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(await within(dialog).findByText("First name, last name and date of birth are required.")).toBeInTheDocument();
    expect(updateMyDetails).not.toHaveBeenCalled();
  });

  it("Edit Profile opens personal and contact details together", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Edit Profile" }));
    const dialog = screen.getByRole("dialog", { name: "Edit profile" });
    expect(within(dialog).getByLabelText("First name")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Phone")).toBeInTheDocument();
  });

  it("explains a loading failure and can try again", async () => {
    const user = userEvent.setup();
    getMyPatientProfile.mockRejectedValueOnce(apiError("Service unavailable"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Profile summary" })).toBeInTheDocument();
  });

  it("asks a new patient to complete their profile first", async () => {
    const user = userEvent.setup();
    getMyPatientProfile.mockRejectedValueOnce(apiError("No profile", "NO_PATIENT_PROFILE"));
    completeMyPatientProfile.mockResolvedValue({ data: { ...patientProfile, photo_url: null } });
    renderPage();

    await screen.findByRole("heading", { name: "Complete your patient profile" });
    await user.type(screen.getByLabelText("First name"), "John");
    await user.type(screen.getByLabelText("Last name"), "Doe");
    await user.type(screen.getByLabelText("Date of birth"), "1990-01-01");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(completeMyPatientProfile).toHaveBeenCalledWith(
      expect.objectContaining({ first_name: "John", last_name: "Doe", date_of_birth: "1990-01-01" })
    );
    expect(fetchCurrentUser).toHaveBeenCalled();
    expect(await screen.findByRole("region", { name: "Profile summary" })).toBeInTheDocument();
  });

  it("uploads a new photo and shows it", async () => {
    const user = userEvent.setup();
    uploadMyPatientPhoto.mockResolvedValue({ data: { ...patientProfile, photo_url: "https://r2.test/p.webp" } });
    const { container } = renderPage();
    const card = await screen.findByRole("region", { name: "Profile Picture" });
    const png = new File([new Uint8Array([137, 80, 78, 71])], "me.png", { type: "image/png" });
    await user.upload(container.querySelector('input[type="file"]'), png);

    expect(uploadMyPatientPhoto).toHaveBeenCalledWith(png);
    const photos = await screen.findAllByRole("img", { name: "Photo of John Doe" });
    expect(photos.some((img) => img.getAttribute("src") === "https://r2.test/p.webp")).toBe(true);
    expect(within(card).getByRole("button", { name: /Change photo/ })).toBeInTheDocument();
  });
});
