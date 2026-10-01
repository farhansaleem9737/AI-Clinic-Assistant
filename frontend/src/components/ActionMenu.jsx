import { MoreVertical } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";

/**
 * A "⋯" menu. `items`: [{ label, to }] for links or [{ label, onSelect, danger }]
 * for actions. Opens with Enter/Space/ArrowDown, moves with the arrow keys,
 * closes with Escape, Tab or a click outside, and returns focus to the button.
 */
export default function ActionMenu({ label, items }) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const button = useRef(null);
  const menu = useRef(null);

  const focusItem = (index) => {
    const entries = menu.current?.querySelectorAll('[role="menuitem"]') ?? [];
    entries[(index + entries.length) % entries.length]?.focus();
  };

  useEffect(() => {
    if (!open) return;
    focusItem(0);
    const outside = (e) => {
      if (!menu.current?.contains(e.target) && !button.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [open]);

  const close = (refocus = true) => {
    setOpen(false);
    if (refocus) button.current?.focus();
  };

  const onMenuKey = (e) => {
    const entries = [...menu.current.querySelectorAll('[role="menuitem"]')];
    const index = entries.indexOf(document.activeElement);
    if (e.key === "ArrowDown") focusItem(index + 1);
    else if (e.key === "ArrowUp") focusItem(index - 1);
    else if (e.key === "Home") focusItem(0);
    else if (e.key === "End") focusItem(entries.length - 1);
    else if (e.key === "Escape") close();
    else if (e.key === "Tab") return close(false);
    else return;
    e.preventDefault();
  };

  return (
    <div className="action-menu">
      <button
        ref={button}
        type="button"
        className="icon-button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        <MoreVertical size={20} aria-hidden="true" />
      </button>
      {open && (
        <div ref={menu} id={menuId} className="action-menu-list" role="menu" aria-label={label} onKeyDown={onMenuKey}>
          {items.map((item) =>
            item.to ? (
              <Link key={item.label} to={item.to} role="menuitem" tabIndex={-1} onClick={() => setOpen(false)}>
                {item.label}
              </Link>
            ) : (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                tabIndex={-1}
                className={item.danger ? "danger" : ""}
                onClick={() => {
                  setOpen(false);
                  item.onSelect();
                }}
              >
                {item.label}
              </button>
            )
          )}
        </div>
      )}
    </div>
  );
}
