import { ChevronDown, KeyRound, LogOut, Settings, UserRound, UserCog } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { useAuth } from "../../context/useAuth";
import { profilePath, roleLabel } from "../../routes/navigation";
import Avatar from "../Avatar";
import ChangePasswordModal from "../ChangePasswordModal";

/**
 * The signed-in user's name and role, opening a menu with their profile,
 * account settings, Change Password and Logout. Every item is a real page or
 * action for this user; the API enforces the same permissions.
 */
export default function AccountMenu({ onLogout }) {
  const { user, can } = useAuth();
  const [open, setOpen] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const [notice, setNotice] = useState("");
  const box = useRef(null);
  const button = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    box.current?.querySelector('[role="menuitem"]')?.focus();
    // pointerdown, not mousedown: iOS Safari sends no mousedown for a tap on a
    // non-clickable area, so tapping outside never closed the menu there.
    const outside = (e) => !box.current?.contains(e.target) && setOpen(false);
    // Escape closes it wherever focus is (also on the trigger).
    const escape = (e) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(timer);
  }, [notice]);

  const onMenuKey = (e) => {
    const items = [...box.current.querySelectorAll('[role="menuitem"]')];
    const index = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") items[(index + 1) % items.length]?.focus();
    else if (e.key === "ArrowUp") items[(index - 1 + items.length) % items.length]?.focus();
    else if (e.key === "Home") items[0]?.focus();
    else if (e.key === "End") items[items.length - 1]?.focus();
    else return;
    e.preventDefault();
  };
  // Tabbing out of the menu closes it. A null relatedTarget is not "leaving":
  // Safari (iOS and macOS) and Firefox on macOS don't focus a link or button on
  // click, so pressing an item blurred to nothing and the menu closed before
  // the click landed. Clicks outside are handled by the pointerdown listener.
  const onBlur = (e) => {
    if (open && e.relatedTarget && !box.current?.contains(e.relatedTarget)) setOpen(false);
  };

  const profile = profilePath(user, can);
  const role = roleLabel(user.roles);
  return (
    <div className="account-menu" ref={box} onBlur={onBlur}>
      <button
        ref={button}
        type="button"
        className="topbar-user"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? "account-menu-list" : undefined}
        aria-label={`${user.name}, ${role}: account menu`}
        onClick={() => setOpen((v) => !v)}
      >
        <Avatar name={user.name} role={user.doctor_id ? "doctor" : undefined} size={40} src={user.photo_url} />
        <span className="who">
          <strong>{user.name}</strong>
          <span>{role}</span>
        </span>
        <ChevronDown size={18} aria-hidden="true" className="account-chevron" />
      </button>
      {open && (
        <div className="card account-dropdown" id="account-menu-list" role="menu" aria-label="Account" onKeyDown={onMenuKey}>
          <div className="account-dropdown-head" role="presentation">
            <Avatar name={user.name} role={user.doctor_id ? "doctor" : undefined} size={40} src={user.photo_url} />
            <span>
              <strong>{user.name}</strong>
              <span className="muted small">{role}</span>
              {user.email && <span className="muted small account-email">{user.email}</span>}
            </span>
          </div>
          <Link role="menuitem" to={profile} onClick={() => setOpen(false)}>
            <UserRound size={17} aria-hidden="true" /> My Profile
          </Link>
          {/* Patients and doctors: the sign-in account page is separate from their profile. */}
          {profile !== "/account" && (
            <Link role="menuitem" to="/account" onClick={() => setOpen(false)}>
              <UserCog size={17} aria-hidden="true" /> Account Settings
            </Link>
          )}
          {can("settings:manage") && (
            <Link role="menuitem" to="/admin/settings" onClick={() => setOpen(false)}>
              <Settings size={17} aria-hidden="true" /> Clinic Settings
            </Link>
          )}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              setChangingPassword(true);
            }}
          >
            <KeyRound size={17} aria-hidden="true" /> Change Password
          </button>
          <button
            type="button"
            role="menuitem"
            className="danger"
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
          >
            <LogOut size={17} aria-hidden="true" /> Logout
          </button>
        </div>
      )}
      {/* In <body>: inside the top bar (z-index 20) the fixed sidebar would cover part of it. */}
      {changingPassword &&
        createPortal(
          <ChangePasswordModal
            onClose={() => {
              setChangingPassword(false);
              button.current?.focus();
            }}
            onChanged={setNotice}
          />,
          document.body
        )}
      {notice && (
        <p className="account-notice" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
