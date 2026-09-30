export default function EmptyState({ icon: Icon, children, action }) {
  return (
    <div className="empty">
      {Icon && <Icon className="icon" size={30} aria-hidden="true" />}
      <p>{children}</p>
      {action}
    </div>
  );
}
