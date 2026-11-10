import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getPublicAvailability } from "../../services/doctorService";
import { queryClient } from "../../services/queryClient";
import { createRealtimeSync } from "../../services/realtimeSync";
import { isoDateIn } from "../../utils/datetime";
import DateTimePicker from "./DateTimePicker";

vi.mock("../../services/doctorService");

const DOCTOR = "11111111-1111-1111-1111-111111111111";
const today = isoDateIn(new Date(), "UTC");
const slot = (hhmm) => ({ starts_at: `${today}T${hhmm}:00Z`, ends_at: `${today}T${hhmm}:00Z` });
const offer = (...times) => ({
  data: { timezone: "UTC", days: [{ date: today, slots: times.map(slot), unavailable: [] }], bookable_until: null, consultation_minutes: 15 },
});

function Booking() {
  const [selected, setSelected] = useState(null);
  return (
    <>
      <DateTimePicker doctorId={DOCTOR} selected={selected} onSelect={setSelected} />
      <p data-testid="chosen">{selected?.starts_at ?? "none"}</p>
    </>
  );
}

beforeEach(() => {
  queryClient.clear();
  getPublicAvailability.mockResolvedValue(offer("22:00", "22:15"));
});
afterEach(() => vi.useRealTimers());

it("a time taken by someone else meanwhile is cleared with a clear message; the date stays", async () => {
  const user = userEvent.setup();
  render(<Booking />);
  const times = await screen.findByRole("group", { name: /Available times on/ });
  await user.click(within(times).getAllByRole("button")[0]);
  expect(screen.getByTestId("chosen")).toHaveTextContent("22:00");

  // Another patient books 22:00: the live event refreshes this doctor's times.
  getPublicAvailability.mockResolvedValue(offer("22:15"));
  const sync = createRealtimeSync(queryClient, 0);
  await act(async () => {
    sync({ type: "availability.changed", resource: "availability", payload: { doctor_id: DOCTOR, date: today } });
    await new Promise((r) => setTimeout(r, 20));
  });

  expect(await screen.findByText(/just booked by someone else/)).toBeInTheDocument();
  expect(screen.getByTestId("chosen")).toHaveTextContent("none");
  const left = screen.getByRole("group", { name: /Available times on/ }); // the same day, still shown
  expect(within(left).getAllByRole("button")).toHaveLength(1);
  await user.click(within(left).getByRole("button"));
  expect(screen.queryByText(/just booked by someone else/)).not.toBeInTheDocument();
});

it("another doctor's change does not re-read this one's times", async () => {
  render(<Booking />);
  await screen.findByRole("group", { name: /Available times on/ });
  const sync = createRealtimeSync(queryClient, 0);
  await act(async () => {
    sync({ type: "availability.changed", resource: "availability", payload: { doctor_id: "someone-else", date: today } });
    await new Promise((r) => setTimeout(r, 20));
  });
  expect(getPublicAvailability).toHaveBeenCalledTimes(1);
});
