// One Idempotency-Key per intended booking (patient, doctor, time) for this
// browser session. Leaving the confirm step and coming back, or a reload, reuses
// it, so a booking the server saved but whose answer was lost is returned again
// instead of being made twice. Kept in sessionStorage when available; falls back
// to memory (private windows, blocked storage).

const STORE = "booking:idempotency-keys";
const memory = new Map();

function read() {
  try {
    return JSON.parse(sessionStorage.getItem(STORE) || "{}");
  } catch {
    return Object.fromEntries(memory);
  }
}

function write(all) {
  try {
    sessionStorage.setItem(STORE, JSON.stringify(all));
  } catch {
    memory.clear();
    for (const [k, v] of Object.entries(all)) memory.set(k, v);
  }
}

export const bookingScope = ({ patientId, doctorId, startsAt }) => `${patientId ?? "self"}|${doctorId}|${Date.parse(startsAt)}`;

export function bookingKey(scope) {
  const all = read();
  if (!all[scope]) {
    all[scope] = crypto.randomUUID();
    write(all);
  }
  return all[scope];
}

/** After a booking is saved, or the time is gone: the next attempt is a new booking. */
export function forgetBookingKey(scope) {
  const all = read();
  if (!(scope in all)) return;
  delete all[scope];
  write(all);
}
