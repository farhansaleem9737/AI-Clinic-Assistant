import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

// items: [{ label, to }]; the last item is the current page (not a link).
export default function Breadcrumb({ items }) {
  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      <ol>
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li key={item.label}>
              {last ? <span aria-current="page">{item.label}</span> : <Link to={item.to}>{item.label}</Link>}
              {!last && <ChevronRight size={14} aria-hidden="true" />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
