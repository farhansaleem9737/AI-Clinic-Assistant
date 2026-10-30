import { Bell } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getErrorMessage } from "../../services/api";
import {
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "../../services/workspaceService";

const POLL_MS = 60_000;
const ago = (iso) => new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));

/**
 * The bell (D86): the caller's real unread count, refreshed every minute and
 * on opening; the panel lists recent notifications, opens their link and
 * marks them read.
 */
export default function NotificationBell() {
  const navigate = useNavigate();
  const box = useRef(null);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  const refreshCount = useCallback(() => {
    getUnreadCount()
      .then((res) => setUnread(res.data.unread))
      .catch(() => {}); // the badge simply keeps its last value
  }, []);

  useEffect(() => {
    refreshCount();
    const timer = setInterval(refreshCount, POLL_MS);
    return () => clearInterval(timer);
  }, [refreshCount]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    listNotifications()
      .then((res) => {
        if (cancelled) return;
        setItems(res.data.items);
        setUnread(res.data.unread);
        setError("");
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err, "Could not load notifications")));
    const outside = (e) => !box.current?.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", outside);
    return () => {
      cancelled = true;
      document.removeEventListener("mousedown", outside);
    };
  }, [open]);

  const openNotification = async (note) => {
    if (!note.read_at) {
      try {
        await markNotificationRead(note.id);
        setItems((list) => list.map((n) => (n.id === note.id ? { ...n, read_at: new Date().toISOString() } : n)));
        setUnread((n) => Math.max(0, n - 1));
      } catch {
        // Opening the link still works; the badge corrects itself on the next refresh.
      }
    }
    if (note.link) {
      setOpen(false);
      navigate(note.link);
    }
  };
  const readAll = async () => {
    try {
      await markAllNotificationsRead();
      setItems((list) => list.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })));
      setUnread(0);
    } catch (err) {
      setError(getErrorMessage(err, "Could not mark the notifications as read"));
    }
  };

  return (
    <div className="bell" ref={box}>
      <button
        type="button"
        className="icon-button bell-button"
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
      >
        <Bell size={22} aria-hidden="true" />
        {unread > 0 && (
          <span className="bell-badge" aria-hidden="true">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="card bell-panel" role="dialog" aria-label="Notifications" onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
          <div className="bell-head">
            <strong>Notifications</strong>
            {unread > 0 && (
              <button type="button" className="link-button" onClick={readAll}>
                Mark all as read
              </button>
            )}
          </div>
          {error ? (
            <p className="field-error" role="alert">
              {error}
            </p>
          ) : items === null ? (
            <p className="muted small" role="status">
              Loading…
            </p>
          ) : items.length === 0 ? (
            <p className="muted small">You have no notifications.</p>
          ) : (
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
          )}
        </div>
      )}
    </div>
  );
}
