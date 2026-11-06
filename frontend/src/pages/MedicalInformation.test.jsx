import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { getDocumentDownload, listDocuments, retractDocument, uploadDocument } from "../services/documentService";
import { addHealthRecord, getHealthRecords } from "../services/healthRecordService";
import { PERMISSIONS, authAs } from "../test/fixtures";
import MedicalInformation from "./MedicalInformation";

vi.mock("../context/useAuth");
vi.mock("../services/documentService", async (importOriginal) => ({
  ...(await importOriginal()),
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  getDocumentDownload: vi.fn(),
  retractDocument: vi.fn(),
}));
vi.mock("../services/healthRecordService", () => ({
  getHealthRecords: vi.fn(),
  addHealthRecord: vi.fn(),
  updateHealthRecord: vi.fn(),
  removeHealthRecord: vi.fn(),
}));

const DOC_PERMS = ["document:read_own", "document:upload_own", "document:retract_own", "health_record:read_own", "health_record:report_own"];
const entry = (id, extra = {}) => ({
  id, source: "patient", recorded_by: null, recorded_by_me: true, can_edit: true,
  created_at: "2026-10-30T09:00:00Z", updated_at: "2026-10-30T09:00:00Z", ...extra,
});
const NO_RECORDS = { allergies: [], diagnoses: [], medications: [], can_add_allergies: true, can_add_diagnoses: false, can_add_medications: true };
const doc = (id, extra = {}) => ({
  id, patient_id: "pat-1", appointment_id: null, document_type: "lab_report", title: `Report ${id}`,
  document_date: "2026-10-30", filename: `${id}.pdf`, content_type: "application/pdf", size_bytes: 1_200_000,
  uploaded_by_me: true, created_at: "2026-10-30T09:00:00Z", ...extra,
});
const THREE = [
  doc("d1", { title: "Diabetes Assessment Report" }),
  doc("d2", { title: "Complete Blood Count (CBC)", content_type: "image/png", filename: "cbc.png", size_bytes: 785_000, document_date: "2026-10-29" }),
  doc("d3", { title: "Clinical Case", document_type: "discharge_summary", uploaded_by_me: false, size_bytes: 2_400_000 }),
];
const pdfFile = (name = "lab.pdf", size = 1000) => new File([new Uint8Array(size)], name, { type: "application/pdf" });

function Where() {
  const { pathname, search } = useLocation();
  return <p data-testid="where">{pathname + search}</p>;
}
function renderPage({ docs = [], records = NO_RECORDS, path = "/profile/medical-information", permissions = DOC_PERMS, patientId = "pat-1", fail } = {}) {
  const auth = authAs("Farhan Saleem", ["patient"], [...PERMISSIONS.patient, ...permissions]);
  useAuth.mockReturnValue({ ...auth, user: { ...auth.user, patient_id: patientId } });
  listDocuments.mockResolvedValue({ data: docs });
  getHealthRecords.mockResolvedValue({ data: records });
  if (fail) listDocuments.mockRejectedValueOnce(fail);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/profile/medical-information" element={<MedicalInformation />} />
      </Routes>
      <Where />
    </MemoryRouter>
  );
}
const overviewCount = (label) => within(screen.getByRole("region", { name: "Health Overview" })).getByText(label).closest("li");

let assign;
beforeEach(() => {
  vi.clearAllMocks();
  assign = vi.fn();
  Object.defineProperty(window, "location", { configurable: true, value: { ...window.location, assign } });
});
afterEach(() => vi.restoreAllMocks());

describe("documents: empty (layout A) and populated (layout B)", () => {
  it("with no documents: the illustration, Upload, the limits and the tip card", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Medical Information" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "No medical documents yet" })).toBeInTheDocument();
    expect(screen.getByText("Supported: PDF, JPG, PNG • Up to 20 MB")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload Document" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Keep your health information up to date" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Quick Actions/ })).not.toBeInTheDocument();
    expect(overviewCount("Documents")).toHaveTextContent("0");
    expect(listDocuments).toHaveBeenCalledWith("pat-1");
  });

  it("with documents: the count, each row's facts and actions, and Quick Actions", async () => {
    renderPage({ docs: THREE });
    expect(await screen.findByRole("heading", { name: "My Medical Documents (3)" })).toBeInTheDocument();
    const rows = screen.getAllByRole("listitem").filter((li) => li.classList.contains("med-doc-row"));
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Diabetes Assessment Report");
    expect(rows[0]).toHaveTextContent("30 Oct 2026");
    expect(rows[0]).toHaveTextContent("1.1 MB");
    expect(rows[0]).toHaveTextContent("Lab report");
    expect(rows[1]).toHaveTextContent("29 Oct 2026");
    expect(rows[2]).toHaveTextContent("Discharge summary");
    expect(within(rows[0]).getByRole("button", { name: "View Diabetes Assessment Report" })).toBeInTheDocument();
    expect(within(rows[0]).getByRole("button", { name: "Download Diabetes Assessment Report" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Quick Actions/ })).toBeInTheDocument();
    expect(overviewCount("Documents")).toHaveTextContent("3");
  });

  it("explains a loading failure and can try again", async () => {
    const user = userEvent.setup();
    renderPage({ fail: { response: { status: 503, data: { error: { message: "Storage is down" } } } } });
    expect(await screen.findByText("Storage is down")).toBeInTheDocument();
    expect(overviewCount("Documents")).not.toHaveTextContent("0"); // unknown, not "none"
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "No medical documents yet" })).toBeInTheDocument();
  });
});

describe("upload", () => {
  it("Upload opens the dialog; a valid PDF is uploaded and the list and overview refresh", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Upload Document" }));
    const dialog = screen.getByRole("dialog", { name: "Upload a medical document" });
    let finish;
    uploadDocument.mockImplementation((id, file, fields, onProgress) => {
      onProgress(40);
      return new Promise((r) => (finish = () => r({ data: doc("new", { title: fields.title }) })));
    });
    await user.upload(within(dialog).getByLabelText("File"), pdfFile("blood-test.pdf"));
    expect(within(dialog).getByLabelText("Title")).toHaveValue("blood-test");
    listDocuments.mockResolvedValue({ data: [doc("new", { title: "blood-test" })] });
    await user.click(within(dialog).getByRole("button", { name: "Upload" }));
    expect(screen.getByRole("progressbar", { name: "Upload progress" })).toHaveAttribute("aria-valuenow", "40");
    expect(screen.queryByText(/was uploaded/)).not.toBeInTheDocument(); // not before the server confirms
    finish();
    expect(await screen.findByText("“blood-test” was uploaded.")).toBeInTheDocument();
    const [, file, fields] = uploadDocument.mock.calls[0];
    expect(file.name).toBe("blood-test.pdf");
    expect(fields).toEqual({ title: "blood-test", document_type: "lab_report", document_date: "" });
    expect(await screen.findByRole("heading", { name: "My Medical Documents (1)" })).toBeInTheDocument();
    await waitFor(() => expect(overviewCount("Documents")).toHaveTextContent("1"));
  });

  it("an image uploads too", async () => {
    const user = userEvent.setup();
    uploadDocument.mockResolvedValue({ data: doc("img", { title: "scan", content_type: "image/png" }) });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Upload Document" }));
    const dialog = screen.getByRole("dialog");
    await user.upload(within(dialog).getByLabelText("File"), new File([new Uint8Array(10)], "scan.png", { type: "image/png" }));
    await user.click(within(dialog).getByRole("button", { name: "Upload" }));
    expect(await screen.findByText("“scan” was uploaded.")).toBeInTheDocument();
  });

  it("refuses an unsupported type and an oversized file before sending anything", async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Upload Document" }));
    const dialog = screen.getByRole("dialog");
    await user.upload(within(dialog).getByLabelText("File"), new File(["x"], "notes.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("This file type is not supported");
    await user.upload(within(dialog).getByLabelText("File"), pdfFile("huge.pdf", 21 * 1024 * 1024));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Documents can be up to 20 MB");
    await user.click(within(dialog).getByRole("button", { name: "Upload" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Choose a file to upload.");
    expect(uploadDocument).not.toHaveBeenCalled();
  });

  it.each([
    [{ response: { status: 413, data: {} } }, "The file is too large"],
    [new Error("Network Error"), "The upload was interrupted"],
    [{ response: { status: 401, data: {} } }, "Your session has expired"],
    [{ response: { status: 503, data: {} } }, "File storage is temporarily unavailable"],
    [{ response: { status: 400, data: { error: { code: "UNSUPPORTED_FILE", message: "The file content is not a valid PDF" } } } }, "not a valid PDF"],
  ])("explains a failed upload (%#)", async (failure, text) => {
    const user = userEvent.setup();
    uploadDocument.mockRejectedValue(failure);
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Upload Document" }));
    const dialog = screen.getByRole("dialog");
    await user.upload(within(dialog).getByLabelText("File"), pdfFile());
    await user.click(within(dialog).getByRole("button", { name: "Upload" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(text);
    expect(screen.queryByText(/was uploaded/)).not.toBeInTheDocument();
  });

  it("asks before uploading the same file again", async () => {
    const user = userEvent.setup();
    uploadDocument.mockResolvedValue({ data: doc("again") });
    renderPage({ docs: [doc("d1", { filename: "lab.pdf", size_bytes: 1000 })] });
    await user.click((await screen.findAllByRole("button", { name: "Upload Document" }))[0]);
    const dialog = screen.getByRole("dialog");
    await user.upload(within(dialog).getByLabelText("File"), pdfFile("lab.pdf", 1000));
    await user.click(within(dialog).getByRole("button", { name: "Upload" }));
    expect(within(dialog).getByText(/already in your records/)).toBeInTheDocument();
    expect(uploadDocument).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Upload anyway" }));
    expect(uploadDocument).toHaveBeenCalledTimes(1);
  });
});

describe("view, download, details, remove", () => {
  it("previews a PDF and an image from short-lived links, and downloads", async () => {
    const user = userEvent.setup();
    getDocumentDownload.mockImplementation((p, id, opts) => Promise.resolve({ data: { url: `https://r2.test/${id}?inline=${Boolean(opts?.inline)}` } }));
    renderPage({ docs: THREE });
    await user.click(await screen.findByRole("button", { name: "View Diabetes Assessment Report" }));
    let dialog = screen.getByRole("dialog", { name: "Diabetes Assessment Report" });
    expect(await within(dialog).findByTitle("Diabetes Assessment Report")).toHaveAttribute("src", "https://r2.test/d1?inline=true");
    expect(getDocumentDownload).toHaveBeenCalledWith("pat-1", "d1", { inline: true });
    await user.click(within(dialog).getByRole("button", { name: "Close" }));

    await user.click(screen.getByRole("button", { name: "View Complete Blood Count (CBC)" }));
    dialog = screen.getByRole("dialog", { name: "Complete Blood Count (CBC)" });
    expect(await within(dialog).findByRole("img", { name: "Complete Blood Count (CBC)" })).toHaveAttribute("src", "https://r2.test/d2?inline=true");
    await user.click(within(dialog).getByRole("button", { name: "Close" }));

    await user.click(screen.getByRole("button", { name: "Download Clinical Case" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://r2.test/d3?inline=false"));
  });

  it("an unauthorized or missing document is reported, not shown", async () => {
    const user = userEvent.setup();
    getDocumentDownload.mockRejectedValue({ response: { status: 404, data: { error: { message: "Document not found" } } } });
    renderPage({ docs: THREE });
    await user.click(await screen.findByRole("button", { name: "View Diabetes Assessment Report" }));
    expect(await screen.findByText("Document not found")).toBeInTheDocument();
    expect(screen.queryByTitle("Diabetes Assessment Report")).not.toBeInTheDocument();
  });

  it("details, and removing an own upload only after confirming with a reason", async () => {
    const user = userEvent.setup();
    retractDocument.mockResolvedValue({ data: {} });
    renderPage({ docs: THREE });
    await user.click(await screen.findByRole("button", { name: "More actions for Diabetes Assessment Report" }));
    await user.click(screen.getByRole("menuitem", { name: "View details" }));
    expect(screen.getByRole("dialog", { name: "Document details" })).toHaveTextContent("d1.pdf");
    await user.click(screen.getByRole("button", { name: "Close" }));

    // The clinic's document cannot be removed by the patient.
    await user.click(screen.getByRole("button", { name: "More actions for Clinical Case" }));
    expect(screen.queryByRole("menuitem", { name: "Remove document" })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "More actions for Diabetes Assessment Report" }));
    await user.click(screen.getByRole("menuitem", { name: "Remove document" }));
    const dialog = screen.getByRole("dialog", { name: "Remove this document?" });
    await user.click(within(dialog).getByRole("button", { name: "Remove document" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Say briefly why");
    expect(retractDocument).not.toHaveBeenCalled();
    listDocuments.mockResolvedValue({ data: THREE.slice(1) });
    await user.type(within(dialog).getByLabelText("Reason"), "wrong file");
    await user.click(within(dialog).getByRole("button", { name: "Remove document" }));
    expect(retractDocument).toHaveBeenCalledWith("pat-1", "d1", "wrong file");
    expect(await screen.findByText("“Diabetes Assessment Report” was removed from your records.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "My Medical Documents (2)" })).toBeInTheDocument();
  });
});

describe("tabs: allergies, diagnoses and medications", () => {
  it("four tabs (no summary), by click and arrow keys, kept in the address", async () => {
    const user = userEvent.setup();
    renderPage({ docs: THREE });
    await screen.findByRole("heading", { name: "My Medical Documents (3)" });
    expect(screen.getAllByRole("tab").map((t) => t.textContent.trim())).toEqual(["Documents", "Diagnoses", "Allergies", "Medications"]);
    await user.click(screen.getByRole("tab", { name: "Diagnoses" }));
    expect(screen.getByRole("tab", { name: "Diagnoses" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("No diagnoses recorded")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add diagnosis/ })).not.toBeInTheDocument(); // doctors only
    expect(screen.getByTestId("where")).toHaveTextContent("?tab=diagnoses");
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Allergies" })).toHaveFocus();
    expect(screen.getByText("No allergies recorded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add allergy/ })).toBeInTheDocument();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByText("No medications recorded")).toBeInTheDocument();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/profile\/medical-information$/);
  });

  it("shows who recorded each entry; the doctor's entries cannot be changed; the overview counts them", async () => {
    renderPage({
      docs: THREE,
      path: "/profile/medical-information?tab=medications",
      records: {
        ...NO_RECORDS,
        allergies: [entry("a1", { substance: "Penicillin", reaction: "Rash", severity: "severe" })],
        diagnoses: [entry("x1", { condition: "Asthma", status: "active", diagnosed_on: "2026-10-01", notes: null, source: "clinician", recorded_by: "Dr. Sarah Khan", recorded_by_me: false, can_edit: false })],
        medications: [
          entry("m1", { name: "Salbutamol", dosage: "100 mcg", frequency: "As needed", instructions: null, start_date: null, end_date: null, status: "active", source: "clinician", recorded_by: "Dr. Sarah Khan", recorded_by_me: false, can_edit: false }),
          entry("m2", { name: "Vitamin D", dosage: null, frequency: "Weekly", instructions: null, start_date: null, end_date: null, status: "active" }),
        ],
      },
    });
    const panel = screen.getByRole("tabpanel");
    const rows = await within(panel).findAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Salbutamol");
    expect(rows[0]).toHaveTextContent("100 mcg · As needed");
    expect(rows[0]).toHaveTextContent("Recorded by Dr. Sarah Khan");
    expect(within(rows[0]).queryByRole("button", { name: /Edit/ })).not.toBeInTheDocument();
    expect(rows[1]).toHaveTextContent("Reported by you");
    expect(within(rows[1]).getByRole("button", { name: "Edit Vitamin D" })).toBeInTheDocument();
    expect(overviewCount("Diagnoses")).toHaveTextContent("1");
    expect(overviewCount("Allergies")).toHaveTextContent("1");
    expect(overviewCount("Medications")).toHaveTextContent("2");
  });

  it("the patient reports an allergy; it is saved, announced and the list reloads", async () => {
    const user = userEvent.setup();
    renderPage({ path: "/profile/medical-information?tab=allergies" });
    addHealthRecord.mockResolvedValue({ data: entry("a1", { substance: "Peanuts", reaction: null, severity: "severe" }) });
    await user.click(await screen.findByRole("button", { name: /Add allergy/ }));
    const dialog = screen.getByRole("dialog", { name: "Add an allergy" });
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Enter what you are allergic to.")).toBeInTheDocument();
    expect(addHealthRecord).not.toHaveBeenCalled();
    await user.type(within(dialog).getByRole("textbox", { name: /Allergic to/ }), "Peanuts");
    await user.selectOptions(within(dialog).getByRole("combobox", { name: /Severity/ }), "severe");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(addHealthRecord).toHaveBeenCalledWith("pat-1", "allergies", { substance: "Peanuts", reaction: null, severity: "severe" });
    expect(await screen.findByText("“Peanuts” was added.")).toBeInTheDocument();
    await waitFor(() => expect(getHealthRecords).toHaveBeenCalledTimes(2));
  });

  it("the overview opens a tab, and My Allergies is a quick action", async () => {
    const user = userEvent.setup();
    renderPage({ docs: THREE });
    await user.click(await screen.findByRole("button", { name: /My Allergies/ }));
    expect(screen.getByRole("tab", { name: "Allergies" })).toHaveAttribute("aria-selected", "true");
    await user.click(within(screen.getByRole("region", { name: "Health Overview" })).getByRole("button", { name: /Diagnoses/ }));
    expect(screen.getByRole("tab", { name: "Diagnoses" })).toHaveAttribute("aria-selected", "true");
  });

  it("without a patient profile there is nothing to load", () => {
    renderPage({ patientId: null });
    expect(screen.getByRole("link", { name: "Go to My Profile" })).toHaveAttribute("href", "/profile");
    expect(listDocuments).not.toHaveBeenCalled();
    expect(getHealthRecords).not.toHaveBeenCalled();
  });
});
