export default function Alert({ kind = "error", children }) {
  if (!children) return null;
  return <div className={`alert ${kind}`}>{children}</div>;
}
