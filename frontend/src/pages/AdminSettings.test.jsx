import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../context/useAuth";
import { getClinicSettings, updateClinicSettings } from "../services/workspaceService";
import { authAs, PERMISSIONS } from "../test/fixtures";
import AccountProfile from "./AccountProfile";
import AdminSettings from "./AdminSettings";

vi.mock("../context/useAuth");
vi.mock("../services/workspaceService");

const SETTINGS = {
  clinic_name: "Riverside Clinic",
  contact_phone: "+92 42 111 222",
  contact_email: null,
  address: null,
  updated_at: null,
  operational: {
    timezone: "Asia/Karachi",
    default_slot_minutes: 30,
    booking_min_lead_minutes: 60,
    booking_max_advance_days: 90,
    patient_cancellation_cutoff_minutes: 120,
  },
};

beforeEach(() => {
  vi.resetAllMocks();
  useAuth.mockReturnValue(authAs("Ada Admin", ["admin"], [...PERMISSIONS.admin, "settings:manage"]));
  getClinicSettings.mockResolvedValue({ data: SETTINGS });
});

describe("Settings", () => {
  it("loads the saved clinic details and shows the server configuration read-only", async () => {
    render(<AdminSettings />);
    expect(await screen.findByLabelText("Clinic name")).toHaveValue("Riverside Clinic");
    expect(screen.getByLabelText("Contact phone")).toHaveValue("+92 42 111 222");
    const ops = screen.getByRole("region", { name: /Scheduling/ });
    expect(ops).toHaveTextContent("Asia/Karachi");
    expect(ops).toHaveTextContent("30 minutes");
    expect(within(ops).queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("validates, then saves through the API", async () => {
    const user = userEvent.setup();
    updateClinicSettings.mockResolvedValue({ data: { ...SETTINGS, contact_email: "desk@riverside.example", updated_at: "2027-04-23T05:00:00Z" } });
    render(<AdminSettings />);
    const email = await screen.findByLabelText("Contact email");
    await user.type(email, "not-an-email");
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument();
    expect(updateClinicSettings).not.toHaveBeenCalled();

    await user.clear(email);
    await user.type(email, "desk@riverside.example");
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    expect(updateClinicSettings).toHaveBeenCalledWith({
      clinic_name: "Riverside Clinic",
      contact_phone: "+92 42 111 222",
      contact_email: "desk@riverside.example",
      address: null,
    });
    expect(await screen.findByText("Settings saved.")).toBeInTheDocument();
  });

  it("explains a refusal", async () => {
    const user = userEvent.setup();
    updateClinicSettings.mockRejectedValue({ response: { status: 403, data: { error: { message: "You do not have permission to perform this action" } } } });
    render(<AdminSettings />);
    await user.click(await screen.findByRole("button", { name: "Save settings" }));
    expect(await screen.findByText(/do not have permission/)).toBeInTheDocument();
  });
});

describe("My Profile (account)", () => {
  it("shows the signed-in account", () => {
    const auth = authAs("Ada Admin", ["admin"], PERMISSIONS.admin);
    auth.user.created_at = "2026-01-15T09:00:00Z";
    useAuth.mockReturnValue(auth);
    render(
      <MemoryRouter>
        <AccountProfile />
      </MemoryRouter>
    );
    const account = screen.getByRole("region", { name: "Signed-in account" });
    expect(account).toHaveTextContent("Ada Admin");
    expect(account).toHaveTextContent("Administrator");
    expect(screen.getByText("January 15, 2026")).toBeInTheDocument();
  });
});
