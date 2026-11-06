import { ChevronDown, Plus } from "lucide-react";
import { useId, useState } from "react";
import { NavLink, matchPath, useLocation } from "react-router-dom";

/**
 * A sidebar item with sections (e.g. the patient's My Profile). It is shown
 * active and open on any of its pages; the button opens or closes it
 * elsewhere. Its sections are ordinary links. Clicking the button does not
 * close the mobile drawer (only following a link does).
 */
export default function NavGroup({ item }) {
  const { pathname } = useLocation();
  const listId = useId();
  const inside = item.children.some((child) => matchPath({ path: child.to, end: child.end ?? false }, pathname));
  // A manual open/close lasts until the user goes to another page.
  const [toggled, setToggled] = useState({ path: null, open: false });
  const expanded = toggled.path === pathname ? toggled.open : inside;
  const Icon = item.icon;

  return (
    <div className={`nav-group${expanded ? " open" : ""}`}>
      <button
        type="button"
        className={`nav-group-toggle${inside ? " active" : ""}`}
        aria-expanded={expanded}
        aria-controls={listId}
        onClick={(e) => {
          e.stopPropagation(); // keep the mobile drawer open
          setToggled({ path: pathname, open: !expanded });
        }}
      >
        <Icon size={19} aria-hidden="true" />
        <span>{item.label}</span>
        <ChevronDown className="nav-group-chevron" size={17} aria-hidden="true" />
      </button>
      <ul id={listId} className="nav-sub" hidden={!expanded}>
        {item.children.map((child) => (
          <li key={child.to}>
            <NavLink to={child.to} end={child.end ?? false}>
              <Plus size={14} aria-hidden="true" />
              {child.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  );
}
