import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

/** A disclosure: a real button with aria-expanded controlling its region. */
export default function Accordion({ title, children, icon: Icon }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className={open ? "lp-acc open" : "lp-acc"}>
      <h3>
        <button type="button" aria-expanded={open} aria-controls={`${id}-panel`} id={`${id}-button`} onClick={() => setOpen(!open)}>
          {Icon && <Icon size={18} aria-hidden="true" className="lp-acc-icon" />}
          <span>{title}</span>
          <ChevronDown size={18} aria-hidden="true" className="lp-acc-chevron" />
        </button>
      </h3>
      <div id={`${id}-panel`} role="region" aria-labelledby={`${id}-button`} className="lp-acc-panel" hidden={!open}>
        {children}
      </div>
    </div>
  );
}
