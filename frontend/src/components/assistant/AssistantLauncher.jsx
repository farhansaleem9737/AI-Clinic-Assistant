import { useEffect, useRef, useState } from "react";
import avatar from "../../assets/clinic-ai-avatar.png";
import { clampPosition, DRAG_THRESHOLD, launcherSize, loadPosition, savePosition, snapToEdge } from "../../utils/assistant";

const viewport = () => ({ width: window.innerWidth, height: window.innerHeight });

/**
 * The floating Clinic AI Assistant button (D96): the official avatar,
 * bottom-right by default, draggable anywhere with mouse, touch or pen
 * (Pointer Events + pointer capture). A press that moves less than
 * DRAG_THRESHOLD pixels is a click and opens the assistant; anything more
 * is a drag and only moves it. The position is remembered on this device
 * and kept on screen when the window size changes.
 */
export default function AssistantLauncher({ open, onOpen, buttonRef }) {
  const [size, setSize] = useState(() => launcherSize(window.innerWidth));
  const [position, setPosition] = useState(() => loadPosition(viewport(), launcherSize(window.innerWidth)));
  const [dragging, setDragging] = useState(false);
  const drag = useRef(null); // { pointerId, startX, startY, originX, originY, moved }

  useEffect(() => {
    const onResize = () => {
      const next = launcherSize(window.innerWidth);
      setSize(next);
      setPosition((current) => clampPosition(current, viewport(), next));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const onPointerDown = (event) => {
    if (event.button !== undefined && event.button !== 0) return;
    drag.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, originX: position.x, originY: position.y, moved: false };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event) => {
    const d = drag.current;
    if (!d || d.pointerId !== event.pointerId) return;
    const dx = event.clientX - d.startX;
    const dy = event.clientY - d.startY;
    if (!d.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    if (!d.moved) {
      d.moved = true;
      setDragging(true);
    }
    event.preventDefault(); // no text selection or scrolling while dragging
    setPosition(clampPosition({ x: d.originX + dx, y: d.originY + dy }, viewport(), size));
  };

  const finish = (event) => {
    const d = drag.current;
    if (!d || d.pointerId !== event.pointerId) return;
    drag.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    if (d.moved) {
      setDragging(false);
      setPosition((current) => {
        const settled = snapToEdge(current, viewport(), size);
        savePosition(settled);
        return settled;
      });
    } else if (event.type === "pointerup") {
      onOpen();
    }
  };

  const onKeyDown = (event) => {
    // Keyboard users can nudge it too (Shift: bigger steps).
    const step = event.shiftKey ? 48 : 12;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (!moves[event.key]) return;
    event.preventDefault();
    setPosition((current) => {
      const next = clampPosition({ x: current.x + moves[event.key][0], y: current.y + moves[event.key][1] }, viewport(), size);
      savePosition(next);
      return next;
    });
  };

  return (
    <button
      ref={buttonRef}
      type="button"
      className={`ai-launcher${dragging ? " dragging" : ""}${open ? " is-open" : ""}`}
      hidden={open}
      style={{ left: position.x, top: position.y, width: size, height: size }}
      aria-label="Open Clinic AI Assistant (drag to move)"
      aria-expanded={open}
      aria-haspopup="dialog"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={finish}
      onKeyDown={onKeyDown}
      onClick={(event) => {
        // Pointer clicks are handled on pointerup; this is Enter / Space.
        if (event.detail === 0) onOpen();
      }}
      data-testid="ai-launcher"
    >
      <img src={avatar} alt="" draggable="false" />
    </button>
  );
}
