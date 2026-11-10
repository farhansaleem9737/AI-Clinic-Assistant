import { useEffect, useRef, useSyncExternalStore } from "react";
import realtime, { RESYNC } from "../services/realtime";

/**
 * Call `handler(event)` for live events (D122) whose type starts with one of
 * `prefixes` (e.g. ["notification."]), and after a reconnect (RESYNC). The
 * latest handler is used without re-subscribing, so renders never add
 * listeners. `enabled: false` listens to nothing.
 */
export function useRealtimeEvent(prefixes, handler, { enabled = true } = {}) {
  const latest = useRef(handler);
  useEffect(() => {
    latest.current = handler;
  });
  const key = prefixes.join("|");
  useEffect(() => {
    if (!enabled) return undefined;
    const wanted = key.split("|");
    return realtime.subscribe((event) => {
      if (event.type === RESYNC || wanted.some((p) => event.type.startsWith(p))) latest.current(event);
    });
  }, [key, enabled]);
}

/** While mounted, hear changes to this patient's health record (if the server allows it). */
export function useRealtimeWatch(patientId, { enabled = true } = {}) {
  useEffect(() => {
    if (!enabled || !patientId) return undefined;
    return realtime.watch(patientId);
  }, [patientId, enabled]);
}

/** True while the live connection is open: polling can pause. */
export function useRealtimeConnected() {
  return useSyncExternalStore(
    (onChange) => realtime.onStatus(onChange),
    () => realtime.connected,
    () => false
  );
}
