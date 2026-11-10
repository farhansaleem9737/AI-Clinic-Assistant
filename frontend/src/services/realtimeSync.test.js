import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RESYNC } from "./realtime";
import { COALESCE_MS, createRealtimeSync } from "./realtimeSync";

const DR_A = "11111111-1111-1111-1111-111111111111";
const DR_B = "22222222-2222-2222-2222-222222222222";

let client;
let sync;
const keys = [
  ["me", "appointments/list", { page: 1 }],
  ["me", "dashboard/summary"],
  ["me", "availability/public", DR_A, "2026-11-01"],
  ["me", "availability/public", DR_B, "2026-11-01"],
  ["me", "schedule/weekly", DR_B],
  ["me", "departments/public"],
  ["me", "profile/patient"],
  ["me", "local:r1", DR_A], // an unnamed fetch: never touched here
];

beforeEach(() => {
  vi.useFakeTimers();
  client = new QueryClient();
  keys.forEach((key) => client.setQueryData(key, { ok: true }));
  sync = createRealtimeSync(client);
});
afterEach(() => vi.useRealTimers());

const stale = () => keys.filter((key) => client.getQueryState(key).isInvalidated).map((key) => key.slice(1).join(" "));

describe("events refresh only what they affect", () => {
  it("an appointment refreshes lists, dashboards and that doctor's times, not directories or profiles", () => {
    sync({ type: "appointment.created", resource: "appointment", payload: { doctor_id: DR_A, date: "2026-11-10" } });
    vi.advanceTimersByTime(COALESCE_MS);
    expect(stale()).toEqual(["appointments/list [object Object]", "dashboard/summary", `availability/public ${DR_A} 2026-11-01`]);
  });

  it("a schedule change refreshes that doctor's schedule and times only", () => {
    sync({ type: "schedule.updated", resource: "schedule", payload: { doctor_id: DR_B } });
    vi.advanceTimersByTime(COALESCE_MS);
    expect(stale()).toEqual(["dashboard/summary", `availability/public ${DR_B} 2026-11-01`, `schedule/weekly ${DR_B}`]);
  });

  it("notifications and unknown events refresh nothing here", () => {
    sync({ type: "notification.created", resource: "notification", payload: {} });
    sync({ type: "invoice.paid", resource: "invoice", payload: {} });
    vi.advanceTimersByTime(COALESCE_MS);
    expect(stale()).toEqual([]);
  });

  it("a burst of events is one refresh", () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    for (let i = 0; i < 5; i++) sync({ type: "appointment.updated", resource: "appointment", payload: { doctor_id: DR_A } });
    sync({ type: "availability.changed", resource: "availability", payload: { doctor_id: DR_B } });
    expect(spy).not.toHaveBeenCalled();
    vi.advanceTimersByTime(COALESCE_MS);
    expect(spy).toHaveBeenCalledOnce();
    expect(stale()).toContain(`availability/public ${DR_B} 2026-11-01`);
  });

  it("after a reconnect everything that may have changed is re-read", () => {
    sync({ type: RESYNC });
    vi.advanceTimersByTime(COALESCE_MS);
    expect(stale()).toEqual([
      "appointments/list [object Object]",
      "dashboard/summary",
      `availability/public ${DR_A} 2026-11-01`,
      `availability/public ${DR_B} 2026-11-01`,
      `schedule/weekly ${DR_B}`,
    ]);
  });
});

it("a health record change refreshes the patient's own record page only", () => {
  const own = ["me", "patients/own-health-records", "pat-1"];
  const list = ["me", "patients/list"];
  client.setQueryData(own, {});
  client.setQueryData(list, {});
  sync({ type: "health_record.updated", resource: "health_record", payload: { patient_id: "pat-1", kind: "allergies" } });
  vi.advanceTimersByTime(COALESCE_MS);
  expect(client.getQueryState(own).isInvalidated).toBe(true);
  expect(client.getQueryState(list).isInvalidated).toBe(false);
});
