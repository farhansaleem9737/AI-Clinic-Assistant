import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getPublicDepartments } from "../services/departmentService";
import {
  getMyApplication,
  removeApplicationDocument,
  updateMyApplication,
  uploadApplicationDocument,
} from "../services/doctorApplicationService";
import DoctorApplication from "./DoctorApplication";

vi.mock("../services/departmentService");
vi.mock("../services/doctorApplicationService", async (importOriginal) => ({
  ...(await importOriginal()),
  getMyApplication: vi.fn(),
  updateMyApplication: vi.fn(),
  uploadApplicationDocument: vi.fn(),
  removeApplicationDocument: vi.fn(),
}));

const APPLICATION = {
  id: "app-1",
  status: "pending_review",
  name: "Sara Malik",
  email: "sara@example.com",
  license_number: null,
  registration_authority: null,
  specialization: null,
  department_id: null,
  department_name: null,
  years_of_experience: null,
  qualifications: null,
  institution: null,
  bio: null,
  consultation_fee: null,
  languages: null,
  phone: null,
  submitted_at: "2026-10-27T09:00:00Z",
  reviewed_at: null,
  review_notes: null,
  doctor_id: null,
  documents: [],
  missing_for_approval: ["specialization", "department_id"],
};
const DOCUMENT = {
  id: "doc-1",
  document_type: "registration_certificate",
  filename: "pmdc.pdf",
  content_type: "application/pdf",
  size_bytes: 2048,
  uploaded_at: "2026-10-27T09:05:00Z",
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <DoctorApplication />
    </MemoryRouter>
  );

beforeEach(() => {
  vi.resetAllMocks();
  getMyApplication.mockResolvedValue({ data: APPLICATION });
  getPublicDepartments.mockResolvedValue({ data: { items: [{ id: "dep-1", name: "Cardiology" }] } });
});

describe("My Doctor Application", () => {
  it("shows the pending status and what approval still needs", async () => {
    renderPage();
    const status = await screen.findByRole("region", { name: /Verification status/ });
    expect(status).toHaveTextContent("Pending review");
    expect(status).toHaveTextContent(/cannot see patients or receive appointments/);
    expect(within(status).getByRole("list")).toHaveTextContent("SpecializationDepartment");
    expect(screen.getByText("No documents uploaded yet.")).toBeInTheDocument();
  });

  it("saves the professional details, clearing emptied fields", async () => {
    const user = userEvent.setup();
    updateMyApplication.mockResolvedValue({
      data: { ...APPLICATION, specialization: "Cardiologist", department_id: "dep-1", missing_for_approval: [] },
    });
    renderPage();
    await user.type(await screen.findByLabelText(/Specialization/), "Cardiologist");
    await screen.findByRole("option", { name: "Cardiology" });
    await user.selectOptions(screen.getByLabelText(/^Department/), "dep-1");
    await user.click(screen.getByRole("button", { name: "Save details" }));

    expect(updateMyApplication).toHaveBeenCalledWith(
      expect.objectContaining({ specialization: "Cardiologist", department_id: "dep-1", license_number: null })
    );
    expect(await screen.findByText("Your professional details were saved.")).toBeInTheDocument();
    expect(screen.getByText("Your application has the information needed for review.")).toBeInTheDocument();
  });

  it("uploads chosen documents and lists them", async () => {
    const user = userEvent.setup();
    uploadApplicationDocument.mockResolvedValue({ data: DOCUMENT });
    renderPage();
    await screen.findByRole("region", { name: /Verification status/ });
    const upload = screen.getByRole("button", { name: "Upload selected documents" });
    expect(upload).toBeDisabled();

    const file = new File([new Uint8Array(2048)], "pmdc.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Medical Registration Certificate file"), file);
    getMyApplication.mockResolvedValue({ data: { ...APPLICATION, documents: [DOCUMENT] } });
    await user.click(upload);

    expect(uploadApplicationDocument).toHaveBeenCalledWith(file, "registration_certificate", expect.any(Function));
    const documents = await screen.findByRole("region", { name: "Professional Verification Documents" });
    expect(await within(documents).findByText(/pmdc\.pdf · 2 KB/)).toBeInTheDocument();
    expect(within(documents).getByText(/^uploaded$/)).toBeInTheDocument();
  });

  it("asks before removing a document", async () => {
    const user = userEvent.setup();
    getMyApplication.mockResolvedValue({ data: { ...APPLICATION, documents: [DOCUMENT] } });
    removeApplicationDocument.mockResolvedValue({});
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Remove Medical Registration Certificate" }));
    const dialog = screen.getByRole("dialog", { name: "Remove document?" });
    getMyApplication.mockResolvedValue({ data: APPLICATION });
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(removeApplicationDocument).toHaveBeenCalledWith("doc-1");
    expect(await screen.findByText("No documents uploaded yet.")).toBeInTheDocument();
  });

  it("is read-only once reviewed, and shows the reviewer's note", async () => {
    getMyApplication.mockResolvedValue({
      data: { ...APPLICATION, status: "rejected", reviewed_at: "2026-10-28T09:00:00Z", review_notes: "Licence not found" },
    });
    renderPage();
    const status = await screen.findByRole("region", { name: /Verification status/ });
    expect(status).toHaveTextContent("Not approved");
    expect(status).toHaveTextContent("Licence not found");
    expect(screen.getByLabelText(/Specialization/)).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save details" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upload selected documents" })).not.toBeInTheDocument();
  });

  it("explains a loading failure and can retry", async () => {
    const user = userEvent.setup();
    getMyApplication.mockRejectedValueOnce({ response: { data: { error: { message: "Service unavailable" } } } });
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: /Verification status/ })).toBeInTheDocument();
  });
});
