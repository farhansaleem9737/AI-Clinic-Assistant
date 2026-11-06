import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../../context/useAuth";
import { bookAppointment } from "../../services/appointmentService";
import {
  callNextPatient,
  getMyQueue,
  getQueueBoard,
  getQueueSessions,
  getSchedulingPolicy,
  previewSchedulingPolicy,
  queueAction,
  saveSchedulingPolicy,
} from "../../services/queueService";
import { authAs, PERMISSIONS } from "../../test/fixtures";
import SchedulingPolicyCard from "../schedule/SchedulingPolicyCard";
import MyQueueCard from "./MyQueueCard";
import OverrideBookingDialog from "./OverrideBookingDialog";
import QueuePanel from "./QueuePanel";

vi.mock("../../context/useAuth");
vi.mock("../../services/queueService");
vi.mock("../../services/appointmentService");
vi.mock("../booking/PatientPickerDialog", () => ({
  default: ({ onSelect }) => (
    <button type="button" onClick={() => onSelect({ id: "p-9", first_name: "Rae", last_name: "Patient" })}>
      pick Rae
    </button>
  ),
}));

const TZ = "Asia/Karachi";
const POLICY = {
  doctor_id: "d-1", mode: "hybrid", consultation_minutes: 15, buffer_minutes: 0, accept_walk_ins: true, walk_in_capacity: null,
  late_grace_minutes: 10, max_overbook: 1, allow_receptionist_overrides: true, configured: true, legacy_slot_minutes: null,
  standard_durations: [15, 20, 30],
};
const preview = (minutes, affected = []) => ({
  data: {
    doctor_id: "d-1", date: "2026-11-10", timezone: TZ, consultation_minutes: minutes, buffer_minutes: 0,
    working_hours: [["09:00", "17:00"]],
    slots: Array.from({ length: 480 / minutes }, (_, i) => ({
      starts_at: new Date(Date.parse("2026-11-10T04:00:00Z") + i * minutes * 60000).toISOString(),
      ends_at: new Date(Date.parse("2026-11-10T04:00:00Z") + (i + 1) * minutes * 60000).toISOString(),
      status: i === 1 ? "booked" : "free",
    })),
    free_count: 480 / minutes - 1, booked_count: 1, affected_count: affected.length, affected,
  },
});
const entry = (token, extra = {}) => ({
  id: `e-${token}`, token_number: token, kind: "walk_in", state: "waiting", session_date: "2026-11-09", doctor_id: "d-1",
  patient_id: `p-${token}`, patient_name: `Patient ${token}`, checked_in_at: "2026-11-09T05:00:00Z", prioritized: false, late: false,
  position: token, estimated_wait: { min_minutes: 10, max_minutes: 25 }, ...extra,
});
const BOARD = {
  doctor_id: "d-1", doctor_name: "Dr. Sarah Khan", session_date: "2026-11-09", timezone: TZ, policy: POLICY,
  current: null, called: null, waiting: [entry(1), entry(2, { kind: "scheduled", scheduled_at: "2026-11-09T05:30:00Z", late: true })],
  registered: [], finished: [], running_late_minutes: 0,
  not_arrived: [{ appointment_id: "a-7", patient_id: "p-7", patient_name: "Absent Booked", scheduled_at: "2026-11-09T05:00:00Z", status: "scheduled", late: true }],
};

beforeEach(() => {
  vi.resetAllMocks();
  useAuth.mockReturnValue(authAs("Rita", ["receptionist"], PERMISSIONS.receptionist));
  getQueueSessions.mockResolvedValue({ data: [{ doctor_id: "d-1", doctor_name: "Dr. Sarah Khan", department_name: "Heart", mode: "hybrid", hours: [["09:00", "17:00"]], waiting: 2, in_consultation: false }] });
  getQueueBoard.mockResolvedValue({ data: BOARD });
});

describe("QueuePanel (front desk)", () => {
  it("shows tokens in the server's order, lateness and who has not arrived", async () => {
    render(<QueuePanel role="staff" canOverride />);
    const waiting = await screen.findAllByRole("listitem");
    expect(waiting[0]).toHaveTextContent("#1");
    expect(waiting[0]).toHaveTextContent("Walk-in");
    expect(waiting[0]).toHaveTextContent("About 10–25 min (estimate)");
    expect(waiting[1]).toHaveTextContent("Late");
    expect(screen.getByText("Absent Booked").closest("li")).toHaveTextContent("Late"); // not auto no-show: still listed
    expect(screen.getByRole("button", { name: /Register walk-in/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Custom booking/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument(); // only the doctor starts
  });

  it("calls next through the server and says when a booked patient may wait", async () => {
    callNextPatient.mockResolvedValue({ data: { entry: entry(1), may_delay_scheduled: true } });
    render(<QueuePanel role="staff" />);
    await userEvent.click(await screen.findByRole("button", { name: /Call next/ }));
    expect(callNextPatient).toHaveBeenCalledWith("d-1");
    expect(await screen.findByText(/Token #1 \(Patient 1\) called\. A booked patient is due soon/)).toBeInTheDocument();
  });

  it("queue adjustments go to the server and errors are shown", async () => {
    queueAction.mockResolvedValueOnce({ data: entry(2) }).mockRejectedValueOnce({ response: { data: { error: { message: "Only a waiting patient can be moved" } } } });
    render(<QueuePanel role="staff" />);
    const second = (await screen.findAllByRole("listitem"))[1];
    await userEvent.click(within(second).getByRole("button", { name: "Move up" }));
    expect(queueAction).toHaveBeenCalledWith("e-2", "prioritize", {});
    await userEvent.click(within(second).getByRole("button", { name: "Defer" }));
    expect(await screen.findByText("Only a waiting patient can be moved")).toBeInTheDocument();
  });
});

describe("QueuePanel (doctor)", () => {
  it("lets the doctor start and complete, without front-desk actions", async () => {
    useAuth.mockReturnValue(authAs("Sarah Khan", ["doctor"], PERMISSIONS.doctor));
    getQueueBoard.mockResolvedValue({ data: { ...BOARD, current: entry(3, { state: "in_consultation" }) } });
    queueAction.mockResolvedValue({ data: entry(3, { state: "completed" }) });
    render(<QueuePanel role="doctor" doctorId="d-1" />);
    await userEvent.click(await screen.findByRole("button", { name: /Complete/ }));
    expect(queueAction).toHaveBeenCalledWith("e-3", "complete", undefined);
    expect(getQueueSessions).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Register walk-in/ })).not.toBeInTheDocument();
    // One consultation at a time: Start is disabled while someone is in.
    for (const start of screen.getAllByRole("button", { name: "Start" })) expect(start).toBeDisabled();
  });
});

describe("OverrideBookingDialog", () => {
  const open = () =>
    render(<OverrideBookingDialog doctorId="d-1" doctorName="Dr. Sarah Khan" timezone={TZ} policy={POLICY} onClose={vi.fn()} onBooked={vi.fn()} />);

  it("a double booking needs a reason and an explicit confirmation, and is sent as one", async () => {
    bookAppointment.mockResolvedValue({ data: { capacity_exception: true } });
    const user = userEvent.setup();
    open();
    await user.click(screen.getByRole("button", { name: "Patient" }));
    await user.click(screen.getByRole("button", { name: "pick Rae" }));
    await user.type(screen.getByLabelText("Start time"), "10:05");
    await user.click(screen.getByRole("checkbox", { name: /Double booking/ }));
    expect(screen.getByRole("note")).toHaveTextContent("one of them will wait longer");
    await user.click(screen.getByRole("button", { name: "Confirm double booking" }));
    expect(screen.getByText("Say why this double booking is needed.")).toBeInTheDocument();
    expect(screen.getByText("Confirm that you understand the extra wait.")).toBeInTheDocument();
    expect(bookAppointment).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Reason (required)"), "Urgent follow-up");
    await user.click(screen.getByRole("checkbox", { name: /capacity exception/ }));
    await user.click(screen.getByRole("button", { name: "Confirm double booking" }));
    await waitFor(() => expect(bookAppointment).toHaveBeenCalledOnce());
    const [body, key] = bookAppointment.mock.calls[0];
    expect(body).toMatchObject({ doctor_id: "d-1", patient_id: "p-9", custom_time: true, duration_minutes: 15, double_booking: true, override_reason: "Urgent follow-up" });
    expect(key).toBeTruthy(); // idempotent
  });

  it("refuses times off the 5-minute grid before asking the server", async () => {
    const user = userEvent.setup();
    open();
    await user.click(screen.getByRole("button", { name: "Patient" }));
    await user.click(screen.getByRole("button", { name: "pick Rae" }));
    await user.type(screen.getByLabelText("Start time"), "10:07");
    await user.click(screen.getByRole("button", { name: "Book" }));
    expect(screen.getByText("Use a 5-minute mark, e.g. 10:05.")).toBeInTheDocument();
    expect(bookAppointment).not.toHaveBeenCalled();
  });
});

describe("SchedulingPolicyCard", () => {
  const renderCard = (props) =>
    render(
      <MemoryRouter>
        <SchedulingPolicyCard doctorId="d-1" {...props} />
      </MemoryRouter>
    );

  it("the doctor picks 15, 20 or 30 minutes, previews the real day and saves", async () => {
    getSchedulingPolicy.mockResolvedValue({ data: { ...POLICY, configured: false, legacy_slot_minutes: 60 } });
    previewSchedulingPolicy.mockImplementation((_, body) => Promise.resolve(preview(body.consultation_minutes)));
    saveSchedulingPolicy.mockResolvedValue({ data: { ...POLICY, consultation_minutes: 20 } });
    const onSaved = vi.fn();
    renderCard({ canEdit: true, onSaved });
    expect(await screen.findByText(/still use your weekly hours' 60-minute slots/)).toBeInTheDocument();
    const duration = screen.getByLabelText("Appointment Duration");
    expect([...duration.options].map((o) => o.textContent)).toEqual(["15 minutes", "20 minutes", "30 minutes"]);
    expect(await screen.findByText("32")).toBeInTheDocument(); // 9-5 in 15-minute appointments

    await userEvent.selectOptions(duration, "20");
    expect(await screen.findByText("24")).toBeInTheDocument();
    expect(previewSchedulingPolicy).toHaveBeenLastCalledWith("d-1", expect.objectContaining({ consultation_minutes: 20, buffer_minutes: 0 }));
    const times = screen.getByRole("list", { name: /Appointment times on/ });
    expect(within(times).getAllByRole("listitem")[1]).toHaveAccessibleName(/booked$/);

    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(saveSchedulingPolicy).toHaveBeenCalledWith(
      "d-1", expect.objectContaining({ mode: "hybrid", consultation_minutes: 20, buffer_minutes: 0, keep_existing_appointments: false })
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("a length that strands upcoming bookings needs the explicit choice to keep them", async () => {
    const stranded = [{ id: "a-1", starts_at: "2026-11-10T04:15:00Z", ends_at: "2026-11-10T04:30:00Z", duration_minutes: 15 }];
    getSchedulingPolicy.mockResolvedValue({ data: POLICY });
    previewSchedulingPolicy.mockImplementation((_, body) => Promise.resolve(preview(body.consultation_minutes, body.consultation_minutes === 20 ? stranded : [])));
    saveSchedulingPolicy
      .mockRejectedValueOnce({ response: { status: 409, data: { error: { code: "SCHEDULE_CONFLICTS", message: "1 upcoming", details: { count: 1, appointments: stranded } } } } })
      .mockResolvedValueOnce({ data: { ...POLICY, consultation_minutes: 20 } });
    renderCard({ canEdit: true, onSaved: vi.fn() });
    await userEvent.selectOptions(await screen.findByLabelText("Appointment Duration"), "20");
    expect(await screen.findByText(/1 upcoming appointment do not match this length/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByText(/Saving will not move or cancel them/)).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save and keep existing appointments" });
    expect(save).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Keep these appointments at their booked times/ }));
    await userEvent.click(save);
    expect(saveSchedulingPolicy).toHaveBeenLastCalledWith("d-1", expect.objectContaining({ consultation_minutes: 20, keep_existing_appointments: true }));
  });

  it("is read-only for staff who may not change it", async () => {
    getSchedulingPolicy.mockResolvedValue({ data: POLICY });
    previewSchedulingPolicy.mockResolvedValue(preview(15));
    renderCard({ canEdit: false });
    expect(await screen.findByText("Only the doctor or an administrator can change these settings.")).toBeInTheDocument();
    expect(screen.getByLabelText("Appointment Duration")).toBeDisabled();
  });

  it("a length saved before D120 stays selectable as the current one", async () => {
    getSchedulingPolicy.mockResolvedValue({ data: { ...POLICY, consultation_minutes: 45 } });
    previewSchedulingPolicy.mockResolvedValue(preview(15));
    renderCard({ canEdit: true });
    const duration = await screen.findByLabelText("Appointment Duration");
    expect(duration).toHaveValue("45");
    expect([...duration.options].map((o) => o.textContent)).toContain("45 minutes (current)");
  });
});

describe("MyQueueCard", () => {
  it("shows the patient's own token, place and an estimate, and nothing about others", async () => {
    getMyQueue.mockResolvedValue({
      data: [{ id: "q-1", token_number: 7, kind: "walk_in", state: "waiting", session_date: new Date().toISOString().slice(0, 10), doctor_id: "d-1", doctor_name: "Dr. Sarah Khan", timezone: TZ, scheduled_at: null, position: 3, estimated_wait: { min_minutes: 20, max_minutes: 45 } }],
    });
    render(
      <MemoryRouter>
        <MyQueueCard />
      </MemoryRouter>
    );
    expect(await screen.findByText("#7")).toBeInTheDocument();
    expect(screen.getByText(/About 20–45 min \(estimate\)/)).toBeInTheDocument();
    expect(screen.getByText(/not a fixed time/)).toBeInTheDocument();
    queueAction.mockResolvedValue({ data: {} });
    await userEvent.click(screen.getByRole("button", { name: "Cancel this token" }));
    expect(queueAction).toHaveBeenCalledWith("q-1", "cancel");
  });

  it("renders nothing without tokens", async () => {
    getMyQueue.mockResolvedValue({ data: [] });
    const { container } = render(<MyQueueCard />);
    await waitFor(() => expect(getMyQueue).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
