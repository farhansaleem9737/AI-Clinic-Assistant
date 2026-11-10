import { queryClient } from "./queryClient";
import { RESYNC } from "./realtime";

// Which cached data (query categories, services/queryClient.js) an event makes
// out of date. Only queries on screen re-read now; the rest when next opened.
// Pages with their own loading (the bell, the queue, the booking check) also
// listen to events themselves (hooks/useRealtime.js).
const AFFECTS = {
  appointment: ["appointments", "dashboard", "availability", "schedule", "patients"],
  availability: ["availability"],
  schedule: ["schedule", "availability", "dashboard", "doctors/schedules-list"],
  queue: ["dashboard"],
  notification: [],
  // The patient's own Medical Information page; a doctor's open patient page listens itself.
  health_record: ["patients/own-health-records"],
  doctor_application: ["dashboard"], // the admin's pending count
};
// What may have changed while the socket was down.
const RESYNC_ALL = ["appointments", "dashboard", "availability", "schedule", "patients", "doctors/schedules-list"];
// Categories whose queries are per doctor: only that doctor's are refreshed.
const PER_DOCTOR = new Set(["availability", "schedule"]);

export const COALESCE_MS = 250;

const category = (name) => String(name).split("/")[0];
const matches = (targets, name) => targets.has(name) || targets.has(category(name));

/**
 * Collects events for COALESCE_MS, then marks their data stale in one pass:
 * a burst (a reschedule = a cancel, a booking and two availability changes)
 * costs one re-read per query, not four.
 */
export function createRealtimeSync(client = queryClient, wait = COALESCE_MS) {
  let timer = null;
  let everything = new Set(); // categories to refresh for every doctor
  let byDoctor = new Map(); // category → doctor ids

  const flush = () => {
    timer = null;
    const all = everything;
    const doctors = byDoctor;
    everything = new Set();
    byDoctor = new Map();
    client.invalidateQueries({
      predicate: (query) => {
        const name = query.queryKey[1];
        if (typeof name !== "string" || name.startsWith("local:")) return false;
        if (matches(all, name)) return true;
        const ids = doctors.get(category(name));
        return Boolean(ids) && query.queryKey.slice(2).some((dep) => ids.has(dep));
      },
    });
  };

  return function onEvent(event) {
    let targets;
    let doctorId = null;
    if (event.type === RESYNC) targets = RESYNC_ALL;
    else {
      targets = AFFECTS[event.resource];
      if (!targets) return; // unknown kind of event: nothing to do
      doctorId = event.payload?.doctor_id ?? null;
    }
    if (targets.length === 0) return;
    for (const target of targets) {
      if (doctorId && PER_DOCTOR.has(target) && !everything.has(target)) {
        if (!byDoctor.has(target)) byDoctor.set(target, new Set());
        byDoctor.get(target).add(doctorId);
      } else everything.add(target);
    }
    if (!timer) timer = setTimeout(flush, wait);
  };
}
