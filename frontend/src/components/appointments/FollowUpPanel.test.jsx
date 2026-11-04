import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { dismissFollowUp, getFollowUp, saveFollowUp } from "../../services/appointmentService";
import FollowUpPanel from "./FollowUpPanel";

vi.mock("../../services/appointmentService");

const renderPanel = () =>
  render(
    <MemoryRouter>
      <FollowUpPanel appointmentId="appt-1" doctorId="doc-1" />
    </MemoryRouter>
  );

beforeEach(() => vi.resetAllMocks());

describe("follow-up visit", () => {
  it("the patient sees it is due and not booked, can book it or dismiss it", async () => {
    getFollowUp
      .mockResolvedValueOnce({ data: { follow_up: { id: "f-1", due_date: "2027-05-10", doctor_id: "doc-1" }, can_manage: false } })
      .mockResolvedValue({ data: { follow_up: null, can_manage: false } });
    dismissFollowUp.mockResolvedValue({});
    renderPanel();
    expect(await screen.findByText(/Due by/)).toHaveTextContent("Not booked yet.");
    expect(screen.getByRole("link", { name: "Book follow-up" })).toHaveAttribute("href", "/appointments/book?doctor=doc-1");
    expect(screen.queryByLabelText("Follow-up due by")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(dismissFollowUp).toHaveBeenCalledWith("f-1");
    await waitFor(() => expect(screen.queryByText(/Follow-up visit/)).not.toBeInTheDocument());
  });

  it("the doctor records a date; nothing shows for someone who can neither see one nor add one", async () => {
    getFollowUp.mockResolvedValueOnce({ data: { follow_up: null, can_manage: true } });
    getFollowUp.mockResolvedValue({ data: { follow_up: { id: "f-1", due_date: "2027-05-10", doctor_id: "doc-1" }, can_manage: true } });
    saveFollowUp.mockResolvedValue({ data: {} });
    renderPanel();
    expect(await screen.findByText("No follow-up recorded.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Follow-up due by"), "2027-05-10");
    await userEvent.click(screen.getByRole("button", { name: "Record follow-up" }));
    expect(saveFollowUp).toHaveBeenCalledWith("appt-1", "2027-05-10");
    expect(await screen.findByRole("button", { name: "Change date" })).toBeInTheDocument();
  });

  it("is hidden when there is no follow-up and the caller cannot record one", async () => {
    getFollowUp.mockResolvedValue({ data: { follow_up: null, can_manage: false } });
    const { container } = renderPanel();
    await waitFor(() => expect(getFollowUp).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
