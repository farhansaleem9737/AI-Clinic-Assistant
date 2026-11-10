import { useEffect } from "react";
import { useAuth } from "../../context/useAuth";
import realtime, { ACCOUNT_CHANGED } from "../../services/realtime";
import { createRealtimeSync } from "../../services/realtimeSync";

/**
 * Keeps this tab's live connection (D122) open while someone is signed in,
 * and turns its events into targeted cache refreshes. Signing out, or another
 * account signing in, closes it. React's development double-mount opens one
 * connection: the first start is stopped before its ticket is used.
 */
export default function RealtimeConnection({ userId }) {
  const { fetchCurrentUser } = useAuth();
  useEffect(() => {
    const sync = createRealtimeSync();
    const unsubscribe = realtime.subscribe((event) => {
      // Roles changed (e.g. an application approved): menus and permissions follow without signing in again.
      if (event.type === ACCOUNT_CHANGED) fetchCurrentUser?.().catch(() => {});
      else sync(event);
    });
    realtime.start();
    return () => {
      unsubscribe();
      realtime.stop();
    };
  }, [userId, fetchCurrentUser]);
  return null;
}
