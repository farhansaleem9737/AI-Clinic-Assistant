import { useId, useState } from "react";

const COLORS = ["#1d5fe0", "#0a7a43", "#9a4a06", "#7c3aed", "#be185d", "#0e7490"];
// Cool tones only for the illustration, so the figure never reads as a skin colour.
const ART_COLORS = ["#1d5fe0", "#0e7490", "#4f46e5", "#0f766e", "#7c3aed", "#334e8a"];

function colorFor(name, palette = COLORS) {
  const hash = [...name].reduce((sum, ch) => sum + ch.charCodeAt(0), 0);
  return palette[hash % palette.length];
}

function initialsOf(name) {
  return (
    name
      .split(/\s+/)
      .filter((part) => part && !part.endsWith("."))
      .slice(0, 2)
      .map((part) => part[0].toUpperCase())
      .join("") || "?"
  );
}

// A flat, faceless doctor in a white coat with a stethoscope. Drawn in one
// colour family so it suggests no particular gender, age or ethnicity.
function DoctorArt({ color }) {
  const clip = useId();
  return (
    <svg viewBox="0 0 64 64" width="100%" height="100%" aria-hidden="true" focusable="false">
      <defs>
        <clipPath id={clip}>
          <circle cx="32" cy="32" r="32" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clip})`}>
        <rect width="64" height="64" fill={color} opacity="0.16" />
        <g fill={color} opacity="0.5">
          <rect x="27.5" y="29" width="9" height="12" rx="4" />
          <circle cx="32" cy="22" r="11" />
        </g>
        <path d="M2 70C2 50 14 40 32 40s30 10 30 30z" fill="#fff" stroke="#cfd8e6" strokeWidth="1" />
        <path d="M25.5 40.6 32 52l6.5-11.4c-2.1-.4-4.3-.6-6.5-.6s-4.4.2-6.5.6z" fill={color} />
        <path d="M25.5 40.6 30 66M38.5 40.6 34 66" stroke="#cfd8e6" strokeWidth="1.1" fill="none" />
        <path
          d="M23.8 41.5c-3.4 6-2.8 11.6 2.6 14.4M40.2 41.5c2.8 4.8 2.6 8.6-.6 11.4"
          stroke="#23395d"
          strokeWidth="1.7"
          fill="none"
          strokeLinecap="round"
        />
        <circle cx="26.6" cy="56" r="2.8" fill="#23395d" />
        <circle cx="39.6" cy="53.2" r="1.6" fill="#23395d" />
      </g>
    </svg>
  );
}

/**
 * Profile picture with a safe fallback.
 *
 * - `src`: an image the person uploaded themselves. Shown when given; if it
 *   fails to load, the fallback is shown instead (never a broken image).
 * - Fallback: an illustrated doctor for `role="doctor"`, otherwise initials.
 *   Never a photo of a real-looking person.
 * - `alt`: give it when the avatar is the only place the name appears;
 *   otherwise the avatar is decorative and hidden from screen readers.
 */
export default function Avatar({ name = "", size = 40, role, src, alt }) {
  const [failedSrc, setFailedSrc] = useState(null);
  const color = colorFor(name);
  const dimensions = { width: size, height: size };
  const label = alt ? { role: "img", "aria-label": alt } : { "aria-hidden": true };

  if (src && failedSrc !== src) {
    return (
      <img
        className="avatar photo"
        src={src}
        alt={alt ?? ""}
        style={dimensions}
        onError={() => setFailedSrc(src)}
      />
    );
  }
  if (role === "doctor") {
    return (
      <span className="avatar illustrated" data-avatar="doctor" style={{ ...dimensions, background: "#fff" }} {...label}>
        <DoctorArt color={colorFor(name, ART_COLORS)} />
      </span>
    );
  }
  return (
    <span className="avatar" data-avatar="initials" style={{ ...dimensions, fontSize: size * 0.38, background: color }} {...label}>
      {initialsOf(name)}
    </span>
  );
}
