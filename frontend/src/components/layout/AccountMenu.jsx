import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../context/useAuth";
import { profilePath, roleLabel } from "../../routes/navigation";
import Avatar from "../Avatar";

/** The signed-in user's name and role, opening View Profile / Settings / Logout. */
export default function AccountMenu({ onLogout }) {
  const { user, can } = useAuth();
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  const button = useRef(null);

  useEffect(() => {
    if (!open) return;
    box.current?.querySelector('[role="menuitem"]')?.focus();
    const outside = (e) => !box.current?.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [open]);

  const close = () => {
    setOpen(false);
    button.current?.focus();
  };
  const onMenuKey = (e) => {
    const items = [...box.current.querySelectorAll('[role="menuitem"]')];
    const index = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") items[(index + 1) % items.length]?.focus();
    else if (e.key === "ArrowUp") items[(index - 1 + items.length) % items.length]?.focus();
    else if (e.key === "Escape") close();
    else return;
    e.preventDefault();
  };

  return (
    <div className="account-menu" ref={box}>
      <button
        ref={button}
        type="button"
        className="topbar-user"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`${user.name}, ${roleLabel(user.roles)}: account menu`}
        onClick={() => setOpen((v) => !v)}
      >
        <Avatar name={user.name} role={user.doctor_id ? "doctor" : undefined} size={40} src={user.photo_url} />
        <span className="who">
          <strong>{user.name}</strong>
          <span>{roleLabel(user.roles)}</span>
        </span>
        <ChevronDown size={18} aria-hidden="true" />
      </button>
      {open && (
        <div className="card account-dropdown" role="menu" aria-label="Account" onKeyDown={onMenuKey}>
          <Link role="menuitem" to={profilePath(user, can)} onClick={() => setOpen(false)}>
            View Profile
          </Link>
          {can("settings:manage") && (
            <Link role="menuitem" to="/admin/settings" onClick={() => setOpen(false)}>
              Settings
            </Link>
          )}
          <button
            type="button"
            role="menuitem"
            className="danger"
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
          >
            Logout
          </button>
        </div>
      )}
    </div>
  );
}
