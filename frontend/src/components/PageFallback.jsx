/**
 * Shown inside a layout while a page's code is downloading: a heading and
 * two cards in the page's usual place, so the shell never blanks and the
 * page does not jump when it arrives.
 */
export default function PageFallback() {
  return (
    <div className="page-fallback" role="status" aria-label="Loading page">
      <div className="skeleton page-fallback-title" />
      <div className="skeleton page-fallback-line" />
      <div className="page-fallback-grid">
        <div className="card skeleton" />
        <div className="card skeleton" />
      </div>
    </div>
  );
}
