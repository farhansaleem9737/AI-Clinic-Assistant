import { ArrowLeft, Bell, Settings2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getErrorMessage } from "../../services/api";
import {
  getNotificationPreferences,
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  updateNotificationPreferences,
} from "../../services/workspaceService";
import { safeLink } from "../../utils/notifications";

// The count refreshes every 2 minutes while the tab is visible, and when the
// user comes back to it (at most every 15 s): no requests from hidden tabs.
const POLL_MS = 120_000;
const MIN_GAP_MS = 15_000;
const PAGE = 15;
const ago = (iso) => new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));

const PREFERENCES = [
  ["appointment_updates", "Appointment updates", "Confirmations, changes and cancellations"],
  ["reminders", "Appointment reminders", "Before an upcoming appointment"],
  ["follow_ups", "Follow-up reminders", "When a recorded follow-up visit is due"],
  ["emails", "Also by email", "The ones switched on above, to your account's email address"],
];
const ALL_OFF = Object.fromEntries(PREFERENCES.map(([key]) => [key, false]));
const ALL_ON = Object.fromEntries(PREFERENCES.map(([key]) => [key, true]));

function Preferences({ onBack }) {
  const [prefs, setPrefs] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    getNotificationPreferences()
      .then((res) => live && setPrefs(res.data))
      .catch((err) => live && setError(getErrorMessage(err, "Could not load your notification settings")));
    return () => {
      live = false;
    };
  }, []);
  const allOff = Boolean(prefs) && PREFERENCES.every(([key]) => !prefs[key]);
  const change = async (changes) => {
    const before = prefs;
    setPrefs({ ...prefs, ...changes });
    setError("");
    try {
      setPrefs((await updateNotificationPreferences(changes)).data);
    } catch (err) {
      setPrefs(before);
      setError(getErrorMessage(err, "Could not save your notification settings"));
    }
  };
  return (
    <>
      <div className="bell-head">
        <button type="button" className="link-button bell-back" onClick={onBack}>
          <ArrowLeft size={15} aria-hidden="true" /> Notifications
        </button>
      </div>
      <fieldset className="bell-prefs" disabled={!prefs}>
        <legend>Notify me about</legend>
        <label className="bell-prefs-all">
          <input type="checkbox" checked={allOff} onChange={(e) => change(e.target.checked ? ALL_OFF : ALL_ON)} />
          <span>
            Turn off all notifications
            <small className="muted">No optional notifications or emails; untick to turn them all back on</small>
          </span>
        </label>
        {PREFERENCES.map(([key, label, hint]) => (
          <label key={key}>
            <input type="checkbox" checked={Boolean(prefs?.[key])} onChange={(e) => change({ [key]: e.target.checked })} />
            <span>
              {label}
              <small className="muted">{hint}</small>
            </span>
          </label>
        ))}
      </fieldset>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <p className="muted small">Essential notifications, such as a doctor&apos;s new bookings, are always sent.</p>
    </>
  );
}

/**
 * The bell (D86, D108): the caller's unread count from the server, the most
 * recent notifications (older ones on request), opening a notification's page
 * marks it read, and a small settings view for the optional categories.
 */
export default function NotificationBell() {
  const navigate = useNavigate();
  const box = useRef(null);
  const button = useRef(null);
  const lastCount = useRef(0);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState("list");
  const [page, setPage] = useState({ items: null, hasMore: false, loadingMore: false });
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  const refreshCount = useCallback((force = false) => {
    if (!force && Date.now() - lastCount.current < MIN_GAP_MS) return;
    lastCount.current = Date.now();
    getUnreadCount()
      .then((res) => setUnread(res.data.unread))
      .catch(() => {}); // the badge simply keeps its last value
  }, []);

  useEffect(() => {
    refreshCount(true);
    const timer = setInterval(() => document.visibilityState === "visible" && refreshCount(true), POLL_MS);
    const back = () => document.visibilityState === "visible" && refreshCount();
    document.addEventListener("visibilitychange", back);
    window.addEventListener("focus", back);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", back);
      window.removeEventListener("focus", back);
    };
  }, [refreshCount]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    listNotifications(PAGE)
      .then((res) => {
        if (cancelled) return;
        setPage({ items: res.data.items, hasMore: Boolean(res.data.has_more), loadingMore: false });
        setUnread(res.data.unread);
        setError("");
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err, "Could not load notifications")));
    const outside = (e) => !box.current?.contains(e.target) && setOpen(false);
    // Escape closes the panel wherever focus is (e.g. after a button inside it went away).
    const escape = (e) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      setView("list");
      button.current?.focus();
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      cancelled = true;
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open, attempt]);

  const close = () => {
    setOpen(false);
    setView("list");
    button.current?.focus();
  };
  const toggle = () => {
    if (open) return close();
    setPage({ items: null, hasMore: false, loadingMore: false });
    setError("");
    setOpen(true);
  };
  const retry = () => {
    setError("");
    setAttempt((n) => n + 1);
  };
  const older = async () => {
    setPage((p) => ({ ...p, loadingMore: true }));
    try {
      const res = await listNotifications(PAGE, page.items.length);
      const seen = new Set(page.items.map((n) => n.id));
      setPage((p) => ({ items: [...p.items, ...res.data.items.filter((n) => !seen.has(n.id))], hasMore: Boolean(res.data.has_more), loadingMore: false }));
    } catch (err) {
      setPage((p) => ({ ...p, loadingMore: false }));
      setError(getErrorMessage(err, "Could not load older notifications"));
    }
  };

  const openNotification = async (note) => {
    if (!note.read_at) {
      try {
        await markNotificationRead(note.id);
        setPage((p) => ({ ...p, items: p.items.map((n) => (n.id === note.id ? { ...n, read_at: new Date().toISOString() } : n)) }));
        setUnread((n) => Math.max(0, n - 1));
      } catch {
        // Opening the link still works; the badge corrects itself on the next refresh.
      }
    }
    const link = safeLink(note.link);
    if (link) {
      setOpen(false);
      setView("list");
      navigate(link); // the page itself still checks the user's permissions
    }
  };
  const readAll = async () => {
    try {
      await markAllNotificationsRead();
      setPage((p) => ({ ...p, items: p.items?.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })) ?? null }));
      setUnread(0);
    } catch (err) {
      setError(getErrorMessage(err, "Could not mark the notifications as read"));
    }
  };

  const { items } = page;
  return (
    <div className="bell" ref={box}>
      <button
        ref={button}
        type="button"
        className="icon-button bell-button"
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        onClick={toggle}
      >
        <Bell size={22} aria-hidden="true" />
        {unread > 0 && (
          <span className="bell-badge" aria-hidden="true">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="card bell-panel" role="dialog" aria-label="Notifications">
          {view === "settings" ? (
            <Preferences onBack={() => setView("list")} />
          ) : (
            <>
              <div className="bell-head">
                <strong>Notifications</strong>
                <span className="bell-actions">
                  {unread > 0 && (
                    <button type="button" className="link-button" onClick={readAll}>
                      Mark all as read
                    </button>
                  )}
                  <button type="button" className="icon-button bell-settings" aria-label="Notification settings" onClick={() => setView("settings")}>
                    <Settings2 size={17} aria-hidden="true" />
                  </button>
                </span>
              </div>
              {error && !items ? (
                <div className="bell-error" role="alert">
                  <p className="field-error">{error}</p>
                  <button type="button" className="secondary small-button" onClick={retry}>
                    Try again
                  </button>
                </div>
              ) : items === null ? (
                <p className="muted small" role="status">
                  Loading…
                </p>
              ) : items.length === 0 ? (
                <p className="muted small">You have no notifications.</p>
              ) : (
                <>
                  <ul className="bell-list">
                    {items.map((n) => (
                      <li key={n.id}>
                        <button type="button" className={`bell-item${n.read_at ? "" : " unread"}`} onClick={() => openNotification(n)}>
                          <strong>
                            {n.title}
                            {!n.read_at && <span className="sr-only"> (unread)</span>}
                          </strong>
                          <span>{n.message}</span>
                          <small className="muted">{ago(n.created_at)}</small>
                        </button>
                      </li>
                    ))}
                  </ul>
                  {error && (
                    <p className="field-error" role="alert">
                      {error}
                    </p>
                  )}
                  {page.hasMore && (
                    <button type="button" className="link-button bell-more" onClick={older} disabled={page.loadingMore}>
                      {page.loadingMore ? "Loading…" : "Show older notifications"}
                    </button>
                  )}
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
