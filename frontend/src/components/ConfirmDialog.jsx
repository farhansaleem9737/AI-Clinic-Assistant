import { useEffect, useId, useRef } from "react";
import Alert from "./Alert";

/**
 * A small modal confirmation. Focus moves into it, Escape cancels, and focus
 * goes back to whatever opened it when it closes.
 */
export default function ConfirmDialog({ title, children, confirmLabel, cancelLabel = "Cancel", danger, busy, error, onConfirm, onCancel }) {
  const titleId = useId();
  const dialog = useRef(null);

  useEffect(() => {
    const opener = document.activeElement;
    dialog.current?.querySelector("textarea, button")?.focus();
    return () => opener?.focus?.();
  }, []);

  const onKeyDown = (e) => {
    if (e.key === "Escape" && !busy) {
      e.preventDefault();
      onCancel();
    }
    // Keep Tab inside the dialog.
    if (e.key === "Tab") {
      const focusable = [...dialog.current.querySelectorAll("button, textarea, input, select, a[href]")].filter((el) => !el.disabled);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  return (
    <div className="dialog-backdrop">
      <div ref={dialog} className="card dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}>
        <h2 id={titleId}>{title}</h2>
        {children}
        <Alert>{error}</Alert>
        <div className="row dialog-actions">
          <button type="button" className="secondary" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button type="button" className={danger ? "danger-solid" : ""} onClick={onConfirm} disabled={busy}>
            {busy ? "Please wait…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
