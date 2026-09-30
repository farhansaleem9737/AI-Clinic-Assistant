const COLORS = ["#1d5fe0", "#0a7a43", "#9a4a06", "#7c3aed", "#be185d", "#0e7490"];

// Initials on a colour derived from the name (the app stores no photos).
export default function Avatar({ name = "", size = 40 }) {
  const initials = name
    .split(/\s+/)
    .filter((part) => part && !part.endsWith("."))
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");
  const hash = [...name].reduce((sum, ch) => sum + ch.charCodeAt(0), 0);
  return (
    <span
      className="avatar"
      aria-hidden="true"
      style={{ width: size, height: size, fontSize: size * 0.38, background: COLORS[hash % COLORS.length] }}
    >
      {initials || "?"}
    </span>
  );
}
